"""Ubuntu GPU launcher: isolated vLLM environment, local agent, saved experiment batch."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import signal
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .agents.local_chat import local_json, adapter_metadata, PROTOCOL_VERSION
from .analysis import summarize
from .cli import _config_errors, run_one
from .execution import read_jsonl
from .tasks import ROOT, task_hashes
from .uv_support import uv_environment


def _save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def harness_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/program_identity").rglob("*.py"))}


def setup_fingerprint(cfg):
    """Exclude transient aliases/paths, retain everything defining the checked setup."""
    keys = ("adapter", "name", "checkpoint", "revision", "dtype", "quantization",
            "context_length", "enable_thinking", "temperature", "top_p", "top_k", "min_p",
            "repetition_penalty", "max_output_tokens", "request_timeout_seconds", "server_packages_sha256")
    identity = dict(cfg["model"].get("model_identity", {}))
    identity.pop("requested_revision", None)
    setup = {"model": {k: cfg["model"].get(k) for k in keys}, "model_identity": identity,
             "agent": adapter_metadata(), "budgets": cfg["budgets"], "seed": cfg["seed"],
             "tasks": {t: task_hashes(t) for t in cfg["tasks"]},
             "server": {k: cfg["server"].get(k) for k in ("package", "python", "gpu_memory_utilization")},
             "harness": harness_hashes()}
    return hashlib.sha256(json.dumps(setup, sort_keys=True).encode()).hexdigest()


def integration_readiness(run_path):
    run = json.loads((run_path / "run.json").read_text())
    evaluation = json.loads((run_path / "selected_evaluation.json").read_text())
    patch = json.loads((run_path / "delivered_patch.json").read_text())
    commands = read_jsonl(run_path / "commands.jsonl")
    checks = {
        "final_response_returned": run.get("termination") == "completed" and bool(run.get("final_response", "").strip()),
        "source_changed": any(f.get("path") == "checkout/package/rules.py" and f.get("operation") == "modify"
                              for f in patch.get("files", [])),
        "public_checks_passed": any(c.get("is_test_command") and c.get("exit_code") == 0 and
                                    c.get("test_scope_status") == "validated_public_suite" for c in commands),
        "final_source_verified": bool(run.get("verified_test_command_ids")),
        "evaluator_valid": evaluation.get("evaluable") is True,
        "independent_repair_success": evaluation.get("independent_repair_success") is True,
    }
    return {"run_id": run["run_id"], "termination": run.get("termination"),
            "final_response_present": bool(run.get("final_response", "").strip()),
            "checks": checks, "passed": all(checks.values()),
            "guard_status": (run.get("guard_result") or {}).get("status")}


def run_infrastructure_error(run, evaluation, guard=False):
    """Budget exhaustion is an observed agent outcome, not a collection failure."""
    if run.get("termination") not in {
        "completed", "action_budget_exhausted", "context_or_token_budget_exhausted",
        "run_deadline_exhausted",
    }:
        return f"agent stopped with {run.get('termination')}"
    if not evaluation.get("evaluable"):
        return "independent evaluation is invalid"
    if guard:
        status = (run.get("guard_result") or {}).get("status")
        if status not in {"passed", "unverified", "unsupported_command", "no_test_command"}:
            return f"identity guard reported {status}"
    return None


def load_check(path, cfg):
    """A matrix requires an explicit successful integration check from this setup."""
    receipt = json.loads((path / "readiness.json").read_text())
    launch = json.loads((path / "launch.json").read_text())
    checked = yaml.safe_load((path / "config.yaml").read_text())
    if receipt.get("schema_version") != 1 or receipt.get("passed") is not True or launch.get("status") != "check_passed":
        raise ValueError("--check must reference a successful current-version clean integration check")
    if cfg["model"]["checkpoint"] == checked["model"]["checkpoint"] and cfg["model"]["revision"] == "main":
        # Pin subsequent matrices to the exact model that passed the check.
        cfg["model"]["revision"] = checked["model"]["revision"]
    return receipt


def validate_local(cfg):
    errors = _config_errors(cfg)
    if errors:
        return errors
    model, server = cfg.get("model", {}), cfg.get("server", {})
    if not isinstance(server, dict):
        return ["server must be a mapping"]
    if model.get("adapter") != "program_identity.agents.local_chat:LocalChatAgent":
        errors.append("local launcher requires the LocalChatAgent adapter")
    if model.get("protocol_version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        errors.append(f"this launcher requires protocol_version: {PROTOCOL_VERSION}; old batches remain unchanged")
    for key in ("checkpoint", "revision", "dtype"):
        if not isinstance(model.get(key), str) or not model[key].strip():
            errors.append(f"model.{key} must be a nonempty string")
    for key in ("context_length", "max_output_tokens"):
        if type(model.get(key)) is not int or model[key] <= 0:
            errors.append(f"model.{key} must be a positive integer")
    if model.get("enable_thinking") is not False:
        errors.append("initial local adapter requires enable_thinking: false")
    if model.get("quantization") is not None and not isinstance(model["quantization"], str):
        errors.append("model.quantization must be a string or null")
    if type(cfg.get("seed")) is not int:
        errors.append("seed must be an integer")
    for key in ("request_timeout_seconds", "temperature", "top_p"):
        value = model.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            errors.append(f"model.{key} must be a positive number")
    if type(model.get("top_p")) in (int, float) and model["top_p"] > 1:
        errors.append("model.top_p must not exceed 1")
    if type(model.get("top_k")) is not int or model["top_k"] not in (-1,) and model["top_k"] <= 0:
        errors.append("model.top_k must be -1 or a positive integer")
    if type(model.get("min_p")) not in (int, float) or not 0 <= model["min_p"] <= 1:
        errors.append("model.min_p must be in 0..1")
    if (type(model.get("repetition_penalty")) not in (int, float) or
            not math.isfinite(model["repetition_penalty"]) or model["repetition_penalty"] <= 0):
        errors.append("model.repetition_penalty must be positive and finite")
    if type(server.get("port")) is not int or not 1 <= server["port"] <= 65535:
        errors.append("server.port must be an integer in 1..65535")
    if type(server.get("gpu_memory_utilization")) not in (int, float) or not 0 < server["gpu_memory_utilization"] < 1:
        errors.append("server.gpu_memory_utilization must be between zero and one")
    if not isinstance(server.get("package"), str) or not server["package"].startswith("vllm=="):
        errors.append("server.package must pin vllm with ==")
    if not isinstance(server.get("python"), str) or not isinstance(server.get("environment"), str):
        errors.append("server.python and server.environment must be strings")
    if (type(server.get("startup_timeout_seconds")) not in (int, float) or
            not math.isfinite(server["startup_timeout_seconds"]) or server["startup_timeout_seconds"] <= 0):
        errors.append("server.startup_timeout_seconds must be positive")
    if cfg["budgets"].get("run_timeout_seconds") is None:
        errors.append("local runs require a finite run_timeout_seconds")
    for key in ("timeout_seconds", "run_timeout_seconds", "max_tokens"):
        value = cfg["budgets"].get(key)
        if value is not None and not math.isfinite(value):
            errors.append(f"budgets.{key} must be finite")
    if cfg["budgets"].get("max_cost") is not None:
        errors.append("local inference has no monetary cost accounting; max_cost must be null")
    return errors


def server_command(cfg, python, alias):
    model, server = cfg["model"], cfg["server"]
    command = ["uv", "run", "--no-project", "--python", str(python), "--", "vllm", "serve",
               model["checkpoint"], "--host", "127.0.0.1", "--port", str(server["port"]),
               "--served-model-name", alias, "--dtype", model["dtype"],
               "--max-model-len", str(model["context_length"]), "--max-num-seqs", "1",
               "--gpu-memory-utilization", str(server["gpu_memory_utilization"]), "--enforce-eager"]
    command += ["--generation-config", "vllm"]
    if not Path(model["checkpoint"]).is_dir():
        command += ["--revision", model["revision"], "--tokenizer-revision", model["revision"]]
    if model.get("quantization"):
        command += ["--quantization", model["quantization"]]
    return command


def resolve_checkpoint(model):
    """Bind remote model and tokenizer to a Hub commit, or hash a local snapshot."""
    checkpoint = Path(model["checkpoint"]).expanduser()
    if checkpoint.is_dir():
        model["checkpoint"] = str(checkpoint.resolve())
        files = {}
        for path in sorted(checkpoint.rglob("*")):
            if path.is_file() and not set(path.relative_to(checkpoint).parts) & {".git", ".cache"}:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                files[path.relative_to(checkpoint).as_posix()] = digest.hexdigest()
        if not files:
            raise ValueError("local checkpoint is empty")
        return {"kind": "local_snapshot", "sha256": files}
    repo, revision = model["checkpoint"], model["revision"]
    if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
        return {"kind": "huggingface_commit", "repo": repo, "requested_revision": revision, "sha": revision}
    url = ("https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/") +
           "/revision/" + urllib.parse.quote(revision, safe=""))
    with urllib.request.urlopen(url, timeout=60) as response:
        info = json.load(response)
    sha = info.get("sha")
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Hub did not return an immutable model commit")
    model["revision"] = sha
    return {"kind": "huggingface_commit", "repo": repo, "requested_revision": revision, "sha": sha}


def stop_server(process):
    """Stop only the process group created by this launcher, including workers."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass
    # Workers can outlive the vLLM parent. Kill any remaining group members too.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def wait_ready(process, base_url, alias, timeout):
    deadline = time.monotonic() + timeout
    last_error = "server has not responded"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited with code {process.returncode}; inspect server.log")
        try:
            models = local_json(base_url + "/models", timeout=min(2, max(0.1, deadline - time.monotonic())))
            if any(m.get("id") == alias for m in models.get("data", [])):
                return models
            last_error = "server did not advertise the expected model alias"
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"vLLM readiness timed out: {last_error}; inspect server.log")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs/local-qwen.yaml"))
    parser.add_argument("--stage", choices=("check", "matrix"), default="check")
    parser.add_argument("--guard", action="store_true", help="run guard mode only, in its own batch")
    parser.add_argument("--check", type=Path, help="successful clean-check batch required before running a matrix")
    parser.add_argument("--model", help="override Hugging Face checkpoint ID or local checkpoint directory")
    parser.add_argument("--revision", help="override Hub revision (resolved to a commit before launch)")
    parser.add_argument("--dry-run", action="store_true", help="print plan without installs, downloads, GPU use, or writes")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    cfg = yaml.safe_load(config_path.read_text())
    if not isinstance(cfg, dict):
        parser.error("configuration must be a mapping")
    errors = validate_local(cfg)
    if errors:
        parser.error("; ".join(errors))
    if args.model:
        cfg["model"]["checkpoint"] = cfg["model"]["name"] = args.model
    if args.revision:
        cfg["model"]["revision"] = args.revision
    if args.stage == "check":
        cfg["conditions"], cfg["treatments"] = ["clean"], ["ordinary"]
    errors = validate_local(cfg)
    if errors:
        parser.error("; ".join(errors))
    cfg["model"].update(adapter_metadata())
    receipt = None
    if args.stage == "matrix" and not args.dry_run:
        if args.check is None:
            parser.error("matrix requires --check <successful-clean-check-batch>; run the default clean check first")
        try:
            receipt = load_check(args.check.resolve(), cfg)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
    server = cfg["server"]
    environment = Path(server["environment"])
    environment = environment if environment.is_absolute() else ROOT / environment
    python = environment / "bin/python"
    base_url = f"http://127.0.0.1:{server['port']}/v1"
    combinations = list(itertools.product(cfg["tasks"], cfg["conditions"], cfg["treatments"]))
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    alias = "program-identity-" + batch_id
    if args.dry_run:
        print(json.dumps({"stage": args.stage, "mode": "guard" if args.guard else "treatment",
                          "runs": combinations, "server_command": server_command(cfg, python, alias),
                          "server_package": server["package"], "environment": str(environment),
                          "agent": adapter_metadata(), "requires_successful_check": args.stage == "matrix"}, indent=2))
        return 0
    if sys.platform != "linux":
        parser.error("GPU launcher requires Linux; --dry-run and adapter tests also work without a GPU")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", server["port"]))
        except OSError:
            parser.error(f"port {server['port']} is in use; change server.port (existing servers are never adopted)")
    base = Path(cfg.get("runs_dir", "runs/local-qwen"))
    batch = (base if base.is_absolute() else ROOT / base) / batch_id
    batch.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, batch / "requested-config.yaml")
    cfg.update(runs_dir=str(batch / "runs"), replication_id=batch_id, _replication_id=batch_id)
    (batch / "runs").mkdir()
    launch = {"schema_version": 2, "status": "starting", "stage": args.stage,
              "mode": "guard" if args.guard else "treatment", "batch_id": batch_id,
              "started_at": time.time(), "source_config": str(config_path), "run_count": len(combinations),
              "planned_run_count": len(combinations), "completed_run_count": 0, "outcomes": [],
              "check_batch": str(args.check.resolve()) if args.check else None}
    launch["harness_python"] = {"executable": sys.executable, "version": sys.version}
    launch["harness_source_hashes"] = harness_hashes()
    process = None
    interrupted = False
    def handle_signal(signum, frame):
        raise KeyboardInterrupt(f"received signal {signum}")
    old_term = signal.signal(signal.SIGTERM, handle_signal)
    env = uv_environment()
    try:
        print(f"Batch: {batch}", flush=True)
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv"],
                             capture_output=True, text=True, timeout=15, check=True)
        launch["gpu"] = gpu.stdout
        launch["model_identity"] = resolve_checkpoint(cfg["model"])
        cfg["model"]["model_identity"] = launch["model_identity"]
        if not python.exists():
            print("Creating model environment and installing pinned vLLM (first launch only).", flush=True)
            subprocess.run(["uv", "venv", "--python", server["python"], str(environment)], env=env, check=True)
        # uv reuses installed dependencies, and also recovers an interrupted first install.
        subprocess.run(["uv", "pip", "install", "--python", str(python), server["package"]], env=env, check=True)
        version = subprocess.check_output(["uv", "run", "--no-project", "--python", str(python), "--", "python", "-c",
                                           "import importlib.metadata; print(importlib.metadata.version('vllm'))"], env=env, text=True).strip()
        if version != server["package"].split("==", 1)[1]:
            raise ValueError(f"model environment has vLLM {version}, expected {server['package']}; use a fresh server.environment")
        freeze = subprocess.check_output(["uv", "pip", "freeze", "--python", str(python)], env=env, text=True)
        (batch / "server-packages.txt").write_text(freeze)
        cfg["model"]["server_packages_sha256"] = hashlib.sha256(freeze.encode()).hexdigest()
        launch["setup_fingerprint"] = setup_fingerprint(cfg)
        launch["agent_id"] = f"local-chat/{PROTOCOL_VERSION}/{launch['setup_fingerprint'][:12]}"
        if receipt and receipt.get("setup_fingerprint") != launch["setup_fingerprint"]:
            raise ValueError("checked setup differs: model, prompt, task snapshots, sampling, budgets, dependencies, or harness changed; run a new clean check")
        cfg["model"].update(base_url=base_url, api_model=alias, server_package=server["package"],
                             model_identity=launch["model_identity"])
        cfg["guard"] = args.guard
        effective = batch / "config.yaml"
        effective.write_text(yaml.safe_dump({k: v for k, v in cfg.items() if not k.startswith("_")}, sort_keys=False))
        cfg["_config_path"] = str(effective)
        launch["server_command"] = server_command(cfg, python, alias)
        _save(batch / "launch.json", launch)
        server_env = {k: v for k, v in env.items() if not k.startswith("PI_") and k != "PYTHONPATH"}
        with (batch / "server.log").open("w") as log:
            process = subprocess.Popen(launch["server_command"], env=server_env, cwd=ROOT,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            print("Waiting for model download/loading; details in server.log.", flush=True)
            launch["served_models"] = wait_ready(process, base_url, alias, server["startup_timeout_seconds"])
            launch["status"] = "running"
            _save(batch / "launch.json", launch)
            for index, (task, condition, treatment) in enumerate(combinations, 1):
                print(f"[{index}/{len(combinations)}] {task} {condition} {treatment}", flush=True)
                if process.poll() is not None:
                    raise RuntimeError("model server exited during experiment; inspect server.log")
                run_path = run_one(cfg, task, condition, treatment, launch["agent_id"],
                                   mode="guard" if args.guard else "treatment")
                run = json.loads((run_path / "run.json").read_text())
                outcome = integration_readiness(run_path)
                launch["outcomes"].append(outcome)
                launch["completed_run_count"] += 1
                print(f"  source_changed={outcome['checks']['source_changed']} public_checks_passed={outcome['checks']['public_checks_passed']} "
                      f"repair_success={outcome['checks']['independent_repair_success']}", flush=True)
                evaluation = json.loads((run_path / "selected_evaluation.json").read_text())
                error = run_infrastructure_error(run, evaluation, guard=args.guard)
                _save(batch / "launch.json", launch)
                if error:
                    raise RuntimeError(f"{error}; inspect {run_path}")
                if run["termination"] != "completed":
                    print(f"  retained incomplete outcome: {run['termination']}; continuing", flush=True)
            launch["status"] = "completed"
            if args.stage == "check":
                readiness = {"schema_version": 1, "setup_fingerprint": launch["setup_fingerprint"],
                             "passed": bool(launch["outcomes"]) and all(x["passed"] for x in launch["outcomes"]),
                             "runs": launch["outcomes"]}
                _save(batch / "readiness.json", readiness)
                launch["status"] = "check_passed" if readiness["passed"] else "check_failed"
                if not readiness["passed"]:
                    launch["error"] = "clean integration check failed; inspect readiness.json and trajectory.json before running a matrix"
    except KeyboardInterrupt as exc:
        interrupted = True
        launch.update(status="interrupted", error=str(exc))
    except Exception as exc:
        launch.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            stop_server(process)
        except Exception as exc:
            launch.update(status="failed", cleanup_error=f"{type(exc).__name__}: {exc}")
        finally:
            signal.signal(signal.SIGTERM, old_term)
            launch["finished_at"] = time.time()
            _save(batch / "launch.json", launch)
            data, markdown = summarize(batch / "runs")
            _save(batch / "runs/summary.json", data)
            (batch / "runs/summary.md").write_text(markdown)
    print(f"{launch['status']}: {batch}")
    if launch.get("error"):
        print(launch["error"], file=sys.stderr)
    if launch.get("cleanup_error"):
        print(launch["cleanup_error"], file=sys.stderr)
    if launch["status"] == "check_passed":
        next_command = ["uv", "run", "program-identity-local", "--config", str(config_path),
                        "--model", cfg["model"]["checkpoint"], "--revision", cfg["model"]["revision"],
                        "--stage", "matrix", "--check", str(batch)]
        print("After reviewing the clean-check trajectory, run:\n" + shlex.join(next_command))
    return 130 if interrupted else 0 if launch["status"] in ("completed", "check_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
