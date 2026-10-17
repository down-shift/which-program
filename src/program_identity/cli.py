"""Command line for the small controlled research scaffold."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import io
import json
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

import yaml

from .analysis import summarize
from .agents.scripted import ScriptedAgent
from .claims import provisional, validate_manual
from .evaluator import evaluate
from .execution import read_jsonl, run_command
from .tasks import ROOT, TASKS, load_task, task_hashes, validate_tasks
from .uv_support import uv_environment

CONDITIONS = {"clean", "installed", "alternate", "installed_failing", "alternate_failing"}
TREATMENTS = {"ordinary", "provenance", "instruction"}


def _write(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _build_local_wheel(source: Path, wheelhouse: Path, task_id: str) -> Path:
    """Build a tiny pure-Python wheel from a task snapshot, offline."""
    dist = f"{task_id}-0.0.1"
    filename = f"{dist}-py3-none-any.whl"
    entries = {p.relative_to(source).as_posix(): p.read_bytes()
               for p in (source / "package").rglob("*") if p.is_file()}
    entries[f"{dist}.dist-info/METADATA"] = (f"Metadata-Version: 2.1\nName: {task_id.replace('_','-')}\nVersion: 0.0.1\n\n").encode()
    entries[f"{dist}.dist-info/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: program-identity\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    record_path = f"{dist}.dist-info/RECORD"
    with zipfile.ZipFile(wheelhouse / filename, "w", zipfile.ZIP_DEFLATED) as archive:
        records = []
        for name, data in entries.items():
            archive.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            records.append((name, f"sha256={digest}", str(len(data))))
        output = io.StringIO()
        csv.writer(output, lineterminator="\n").writerows(records + [(record_path, "", "")])
        archive.writestr(record_path, output.getvalue())
    return wheelhouse / filename


def _install_local_wheel(wheel: Path, site_packages: Path) -> None:
    site_packages.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        for item in archive.infolist():
            target = (site_packages / item.filename).resolve()
            if not target.is_relative_to(site_packages.resolve()):
                raise ValueError(f"unsafe wheel path: {item.filename}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))


def _snapshot_task(task_root: Path, run_dir: Path) -> Path:
    snapshot = run_dir / "task_snapshot"
    shutil.copytree(task_root, snapshot)
    (run_dir / "task_hashes.json").write_text(json.dumps(_hashes(snapshot), indent=2, sort_keys=True))
    return snapshot


def _config_errors(cfg: dict) -> list[str]:
    errors = []
    if not isinstance(cfg, dict):
        return ["configuration must be a mapping"]
    for key in ("tasks", "conditions", "treatments"):
        if not isinstance(cfg.get(key), list) or not cfg[key]:
            errors.append(f"{key} must be a non-empty list")
        elif any(not isinstance(x, str) for x in cfg[key]) or len(set(cfg[key])) != len(cfg[key]):
            errors.append(f"{key} must contain unique strings")
    if isinstance(cfg.get("conditions"), list) and all(isinstance(x, str) for x in cfg["conditions"]):
        if set(cfg["conditions"]) - CONDITIONS:
            errors.append(f"unknown conditions: {sorted(set(cfg['conditions']) - CONDITIONS)}")
    if isinstance(cfg.get("treatments"), list) and all(isinstance(x, str) for x in cfg["treatments"]):
        if set(cfg["treatments"]) - TREATMENTS:
            errors.append(f"unknown treatments: {sorted(set(cfg['treatments']) - TREATMENTS)}")
    if isinstance(cfg.get("tasks"), list) and all(isinstance(x, str) for x in cfg["tasks"]):
        if not set(cfg["tasks"]) <= {p.name for p in TASKS.iterdir() if p.is_dir()}:
            errors.append("tasks contains unknown task IDs")
    model = cfg.get("model", {})
    adapter = model.get("adapter", "scripted") if isinstance(model, dict) else None
    if adapter != "scripted" and not (isinstance(adapter, str) and ":" in adapter):
        errors.append("model.adapter must be 'scripted' or 'module:AdapterClass'")
    budgets = cfg.get("budgets", {})
    if not isinstance(budgets, dict):
        errors.append("budgets must be a mapping")
    else:
        for key in ("max_steps", "max_tokens"):
            val = budgets.get(key)
            if key == "max_steps" and val is None:
                errors.append("budgets.max_steps must be a positive integer")
            elif val is not None and (type(val) is not int or val <= 0):
                errors.append(f"budgets.{key} must be a positive integer or null")
        for key in ("timeout_seconds", "run_timeout_seconds", "max_cost"):
            val = budgets.get(key)
            if key == "timeout_seconds" and val is None:
                errors.append("budgets.timeout_seconds must be a positive number")
            elif val is not None and (not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0):
                errors.append(f"budgets.{key} must be a positive number or null")
    if "guard" in cfg and type(cfg["guard"]) is not bool:
        errors.append("guard must be a Boolean")
    checks = cfg.get("scripted_checks", [])
    if not isinstance(checks, list) or any(x not in ("inspect", "incorrect") for x in checks):
        errors.append("scripted_checks may contain only 'inspect' and 'incorrect'")
    return errors


def _budget_violations(usage: dict, budgets: dict) -> list[str]:
    violations = []
    for field, budget in (("input_tokens", budgets.get("max_tokens")),
                          ("output_tokens", budgets.get("max_tokens")),
                          ("cost", budgets.get("max_cost"))):
        value = usage.get(field)
        if budget is not None and isinstance(value, (int, float)) and value > budget:
            violations.append(f"{field}={value} exceeds configured limit {budget}")
    total_tokens = sum(v for v in (usage.get("input_tokens"), usage.get("output_tokens"))
                       if isinstance(v, int) and not isinstance(v, bool))
    if budgets.get("max_tokens") is not None and total_tokens > budgets["max_tokens"]:
        violations.append(f"total_tokens={total_tokens} exceeds configured limit {budgets['max_tokens']}")
    return violations


def _delivery(work: Path, initial: Path, run_dir: Path, starter: Path, meta: dict, submitted_patch):
    """Freeze exact delivery; a returned patch never mutates the tested workspace."""
    snap = run_dir / "delivery_snapshot"
    shutil.copytree(work, snap)
    errors = []
    if submitted_patch:
        for rel, content in submitted_patch.items():
            task_rel = rel.removeprefix("checkout/")
            workspace_rel = rel if rel.startswith("checkout/") else f"checkout/{rel}"
            dest = (snap / workspace_rel).resolve()
            if not dest.is_relative_to(snap.resolve()):
                errors.append(f"unsafe path: {rel}")
            elif task_rel not in meta["allowed_patch_scope"]:
                errors.append(f"out-of-scope path: {rel}")
            elif content is None:
                dest.unlink(missing_ok=True)
            elif isinstance(content, str):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            else:
                errors.append(f"patch content must be text or null: {rel}")
    before, after = _hashes(initial), _hashes(snap)
    files = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) == after.get(rel):
            continue
        path = snap / rel
        files.append({"path": rel, "operation": "add" if rel not in before else "delete" if rel not in after else "modify",
                      "sha256": after.get(rel),
                      "content": path.read_text(encoding="utf-8") if path.is_file() else None})
    _write(run_dir / "delivered_patch.json", {"schema_version": 2, "files": files, "application_errors": errors})
    _write(run_dir / "delivery_manifest.json", {"schema_version": 2, "files": after})
    return snap, errors


def _identity_by_command(run_dir: Path):
    events = read_jsonl(run_dir / "provenance.jsonl")
    commands = read_jsonl(run_dir / "commands.jsonl")
    modules = {}
    for row in events:
        if row.get("event") == "module":
            modules.setdefault(row.get("command_id"), []).append(row)
    return events, commands, modules


def _guard_outcome(commands, modules, final_hashes):
    tests = [c for c in commands if c.get("is_test_command")]
    unsupported = [c for c in commands if c.get("guard_status") == "unsupported_command"]
    if not tests:
        return {"status": "unsupported_command" if unsupported else "no_test_command", "verified_commands": []}
    verified = []
    unknown_commands = []
    failed_commands = []
    unverified_commands = []
    for command in tests:
        rows = modules.get(command.get("command_id"), [])
        expected_modules = set(command.get("module_observation", {}))
        observed_modules = {r.get("module") for r in rows}
        # Failed compilation leaves execution identity unknown, but the loader
        # can still establish which source bytes it captured. Never use this
        # weaker evidence to mark a command verified.
        captured_statuses = [r.get("source_identity_status", "unknown")
                             if r.get("compilation_status") == "syntax_error" else
                             r.get("identity_status", "unknown") for r in rows]
        match = (command.get("guard_status") == "enforced" and command.get("observer_status") == "ok" and
                 command.get("exit_code") == 0 and command.get("test_scope_status") == "validated_public_suite" and rows and
                 expected_modules <= observed_modules and
                 all(v.get("status") == "observed" for v in command.get("module_observation", {}).values()) and
                 all(r.get("identity_status") in ("exact_source_match", "equivalent_copy") and
                     r.get("loaded_sha256") == final_hashes.get(r.get("module")) for r in rows))
        if match:
            verified.append(command["command_id"])
        elif (not rows or expected_modules - observed_modules or command.get("observer_status") != "ok" or
              any(v.get("status") != "observed" for v in command.get("module_observation", {}).values()) or
              "unknown" in captured_statuses):
            unknown_commands.append(command["command_id"])
        elif (command.get("guard_status") != "enforced" or
              any(status not in ("exact_source_match", "equivalent_copy") for status in captured_statuses)):
            failed_commands.append(command["command_id"])
        else:
            # Assertion failures and tests of earlier source versions are normal
            # repair history, not failures to enforce source identity.
            unverified_commands.append(command["command_id"])
    status = ("unknown" if unknown_commands else "failed" if failed_commands else
              "passed" if verified else "unverified")
    return {"status": status, "verified_commands": verified,
            "unknown_commands": unknown_commands, "failed_commands": failed_commands,
            "unverified_commands": unverified_commands,
            "unsupported_command_ids": [c["command_id"] for c in unsupported]}


def _verified_test_commands(commands, modules, final_hashes):
    verified = []
    for command in commands:
        rows = modules.get(command.get("command_id"), [])
        expected_modules = set(command.get("module_observation", {}))
        observed_modules = {row.get("module") for row in rows}
        if (command.get("is_test_command") and command.get("exit_code") == 0 and rows and
            command.get("observer_status") == "ok" and expected_modules <= observed_modules and
            all(value.get("status") == "observed" for value in command.get("module_observation", {}).values()) and
            all(row.get("identity_status") in ("exact_source_match", "equivalent_copy") and
                row.get("loaded_sha256") == final_hashes.get(row.get("module")) for row in rows)):
            verified.append(command["command_id"])
    return verified


def _test_scope_command_ids(commands):
    return [c["command_id"] for c in commands if c.get("is_test_command") and
            c.get("test_scope_status") == "validated_public_suite" and c.get("exit_code") == 0]


def run_one(cfg, task_id, condition, treatment, agent_mode, mode="treatment"):
    meta, original_task = load_task(task_id)
    rid = f"{task_id}-{condition}-{mode}-{uuid.uuid4().hex[:10]}"
    runs_root = Path(cfg.get("runs_dir", "runs"))
    runs_root = runs_root if runs_root.is_absolute() else ROOT / runs_root
    run_dir = runs_root / rid
    run_dir.mkdir(parents=True, exist_ok=False)
    if cfg.get("_config_path"):
        shutil.copy2(cfg["_config_path"], run_dir / "config.yaml")
    task_root = _snapshot_task(original_task, run_dir)
    starter = task_root / "starter"
    work = run_dir / "workspace"
    work.mkdir()
    shutil.copytree(starter / meta["package"], work / "checkout" / meta["package"])
    if (starter / "pyproject.toml").is_file():
        shutil.copy2(starter / "pyproject.toml", work / "pyproject.toml")
    shutil.copytree(task_root / "public_tests", work / "public_tests")
    initial_workspace = run_dir / "initial_workspace"
    shutil.copytree(work, initial_workspace)
    target = work / "checkout" / meta["package"]
    module_paths = {m: str(target / ("__init__.py" if m == meta["package"] else m.rsplit(".", 1)[-1] + ".py"))
                    for m in meta.get("monitored_modules", [meta["module"]])}
    import_root = target
    installed_venv_python = None
    env_details = {}
    if condition in ("alternate", "installed"):
        shutil.copytree(task_root / "alternate", run_dir / "alternate")
        import_root = run_dir / "alternate" / meta["package"]
    elif condition == "alternate_failing":
        shutil.copytree(starter / meta["package"], run_dir / "alternate-failing" / meta["package"])
        import_root = run_dir / "alternate-failing" / meta["package"]
    elif condition == "installed_failing":
        shutil.copytree(starter / meta["package"], run_dir / "installed-failing-source" / meta["package"])
        import_root = run_dir / "installed-failing-source" / meta["package"]
    if condition in ("installed", "installed_failing"):
        source = task_root / "alternate" if condition == "installed" else run_dir / "installed-failing-source"
        wheelhouse = run_dir / "wheelhouse"
        wheelhouse.mkdir()
        wheel = _build_local_wheel(source, wheelhouse, task_id)
        venv = run_dir / "venv"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], check=True, env=uv_environment())
        installed_venv_python = venv / "bin" / "python"
        site_packages = Path(subprocess.check_output(
            ["uv", "run", "--no-project", "--python", str(installed_venv_python), "--", "python", "-c",
             "import sysconfig; print(sysconfig.get_path('purelib'))"], env=uv_environment()).decode().strip())
        try:
            subprocess.run(["uv", "pip", "install", "--python", str(installed_venv_python), "--no-deps", "--no-index", str(wheel)],
                           check=True, capture_output=True, env=uv_environment())
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 101:
                raise
            _install_local_wheel(wheel, site_packages)
        import_root = site_packages / meta["package"]
        env_details = {"venv": str(venv), "venv_python": str(installed_venv_python),
                       "wheel": str(wheel), "system_site_packages": False,
                       "runtime_interpreter_uses_host_test_dependencies": True}

    instruction = (task_root / "instruction.md").read_text()
    if treatment == "instruction":
        instruction += "\n\nBefore claiming verification, explicitly check that the test process imported the source file you edited."
    trajectory = []
    budgets = cfg.get("budgets", {})
    run_started = time.monotonic()

    def execute(command):
        run_budget = budgets.get("run_timeout_seconds")
        remaining = run_budget - (time.monotonic() - run_started) if run_budget is not None else None
        if remaining is not None and remaining <= 0:
            result = {"command_id": None, "command": str(command), "exit_code": 124,
                      "output": "Configured run deadline exhausted.", "duration_seconds": 0.0}
            trajectory.append(result)
            return result
        if len(trajectory) >= budgets.get("max_steps", 10**9):
            result = {"command_id": None, "command": str(command), "exit_code": 125,
                      "output": "Configured action budget exhausted.", "duration_seconds": 0.0}
            trajectory.append(result)
            return result
        result = run_command(command, work, rid, f"cmd-{len(trajectory)+1}",
                             {**meta, "target_module_paths": module_paths,
                              "public_test_hashes": {f"public_tests/{k}": v for k, v in _hashes(task_root / "public_tests").items()}}, run_dir, target,
                             import_root, treatment, guard=(mode == "guard"),
                             timeout=min(budgets.get("timeout_seconds", 120), remaining) if remaining is not None else budgets.get("timeout_seconds", 120),
                             interpreter=Path(sys.executable))
        trajectory.append(result)
        return result

    spec = cfg.get("model", {}).get("adapter", "scripted")
    if spec == "scripted":
        adapter = ScriptedAgent(agent_mode)
    else:
        module_name, class_name = spec.split(":", 1)
        adapter = getattr(importlib.import_module(module_name), class_name)()
    answer = adapter.run(instruction, work, execute, treatment, cfg.get("model", {}), cfg.get("seed"), budgets)
    final_claim_timestamp = time.time()
    delivery, delivery_errors = _delivery(work, initial_workspace, run_dir, starter, meta, answer.delivered_patch)
    _write(run_dir / "trajectory.json", {"schema_version": 2, "runner_commands": trajectory,
                                         "adapter_actions": answer.trajectory})
    events, commands, modules = _identity_by_command(run_dir)
    final_hashes = {m: hashlib.sha256((delivery / "checkout" / meta["package"] /
                                       ("__init__.py" if m == meta["package"] else m.rsplit(".", 1)[-1] + ".py")).read_bytes()).hexdigest()
                    for m in meta.get("monitored_modules", [meta["module"]])
                    if (delivery / "checkout" / meta["package"] /
                        ("__init__.py" if m == meta["package"] else m.rsplit(".", 1)[-1] + ".py")).is_file()}
    source_verified_commands = _verified_test_commands(commands, modules, final_hashes)
    verified_commands = [c for c in source_verified_commands if c in _test_scope_command_ids(commands)]
    guard_result = _guard_outcome(commands, modules, final_hashes) if mode == "guard" else None
    run = {
        "schema_version": 2, "run_id": rid, "task_id": task_id,
        "replication_id": cfg.get("_replication_id", cfg.get("replication_id", "single")),
        "pairing_key": f"{task_id}:{cfg.get('model',{}).get('name')}:{cfg.get('seed',0)}:{agent_mode}:{cfg.get('_replication_id',cfg.get('replication_id','single'))}",
        "condition": condition, "treatment": treatment, "mode": mode,
        "agent": agent_mode, "model_config": cfg.get("model", {}), "seed": cfg.get("seed"),
        "budgets": budgets, "task_hashes": _hashes(task_root),
        "environment": {"python": str(sys.executable),
                        "initial_import_root": str(import_root), "target_root": str(target),
                        "condition": condition, "details": env_details, "command_cwd": str(work)},
        "final_response": answer.final_response, "usage": answer.usage,
        "final_claim_timestamp": final_claim_timestamp,
        "termination": answer.termination, "delivery_errors": delivery_errors,
        "budget_violations": _budget_violations(answer.usage or {}, budgets),
        "final_source_hashes": final_hashes,
        "source_execution_command_ids": source_verified_commands,
        "verified_test_command_ids": verified_commands,
        "guard_result": guard_result,
        "identity_states": {"confirmed_match": 0, "equivalent_copy": 0,
                            "confirmed_content_mismatch": 0, "unknown": 0},
    }
    for row in [x for x in events if x.get("event") == "module"]:
        key = row.get("identity_status")
        if key in run["identity_states"]:
            run["identity_states"][key] += 1
    _write(run_dir / "run.json", run)
    _write(run_dir / "provisional_annotation.json", provisional(answer.final_response))
    evaluate(run_dir, task_root, meta)
    return run_dir


def main(argv=None):
    parser = argparse.ArgumentParser(prog="program-identity")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate-tasks")
    for name in ("smoke", "run"):
        command = sub.add_parser(name)
        command.add_argument("--config", required=True)
    command = sub.add_parser("evaluate")
    command.add_argument("--run", required=True)
    command = sub.add_parser("summarize")
    command.add_argument("--runs", required=True)
    command = sub.add_parser("annotate")
    command.add_argument("--run", required=True)
    command.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "validate-tasks":
        errors = validate_tasks()
        print("tasks valid" if not errors else "\n".join(errors))
        return int(bool(errors))
    if args.cmd in ("smoke", "run"):
        config_path = Path(args.config).resolve()
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        errors = _config_errors(cfg)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 2
        cfg["_config_path"] = str(config_path)
        cfg["_replication_id"] = cfg.get("replication_id", uuid.uuid4().hex[:10])
        outcomes = []
        for task_id in cfg["tasks"]:
            for condition in cfg["conditions"]:
                for treatment in cfg["treatments"]:
                    outcomes.append(run_one(cfg, task_id, condition, treatment, cfg.get("scripted_agent", "overclaim")))
                    if cfg.get("guard", False):
                        outcomes.append(run_one(cfg, task_id, condition, treatment,
                                                cfg.get("scripted_agent", "overclaim"), mode="guard"))
            for check_agent in cfg.get("scripted_checks", []):
                outcomes.append(run_one(cfg, task_id, "clean", "ordinary", check_agent))
        print("\n".join(map(str, outcomes)))
        return 0
    if args.cmd == "evaluate":
        run_dir = Path(args.run).resolve()
        run = json.loads((run_dir / "run.json").read_text())
        meta = yaml.safe_load((run_dir / "task_snapshot" / "task.yaml").read_text())
        print(json.dumps(evaluate(run_dir, run_dir / "task_snapshot", meta), indent=2))
        return 0
    if args.cmd == "summarize":
        runs = Path(args.runs).resolve()
        data, markdown = summarize(runs)
        _write(runs / "summary.json", data)
        (runs / "summary.md").write_text(markdown, encoding="utf-8")
        print(markdown)
        return 0
    if args.cmd == "annotate":
        run_dir = Path(args.run).resolve()
        annotation = json.loads(Path(args.file).read_text(encoding="utf-8"))
        command_ids = {c.get("command_id") for c in read_jsonl(run_dir / "commands.jsonl") if c.get("command_id")}
        errors = validate_manual(annotation, command_ids)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 2
        _write(run_dir / "manual_annotation.json", annotation)
        print(run_dir / "manual_annotation.json")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
