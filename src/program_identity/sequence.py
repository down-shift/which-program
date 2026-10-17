"""Resume the expanded pilot sequence using saved batches as checkpoints."""
from __future__ import annotations

import argparse
import itertools
import json
import signal
import subprocess
from pathlib import Path

import yaml

from .agents.local_chat import adapter_metadata
from .local import experiment_settings, harness_hashes, resume_runs
from .tasks import ROOT


def matching_batches(root, cfg, stage, mode):
    wanted = dict(cfg)
    if stage == "check":
        wanted.update(conditions=["clean"], treatments=["ordinary"])
    matches = []
    for batch in root.iterdir() if root.exists() else []:
        if not batch.is_dir():
            continue
        try:
            launch = json.loads((batch / "launch.json").read_text())
            saved = batch / "config.yaml"
            if not saved.exists():
                saved = batch / "requested-config.yaml"
            previous = yaml.safe_load(saved.read_text())
            if launch["stage"] != stage or launch["mode"] != mode:
                continue
            if experiment_settings(previous) != experiment_settings(wanted):
                continue
            if (previous["model"].get("prompt_sha256") and
                    previous["model"]["prompt_sha256"] != adapter_metadata()["prompt_sha256"]):
                continue
            retained, retry = resume_runs(batch, wanted, mode == "guard")
            expected = len(list(itertools.product(wanted["tasks"], wanted["conditions"], wanted["treatments"])))
            complete = len(retained) == expected and not retry
            if stage == "check":
                receipt = json.loads((batch / "readiness.json").read_text())
                if (not complete or launch["status"] != "check_passed" or receipt.get("passed") is not True
                        or launch.get("harness_source_hashes") != harness_hashes()):
                    continue
            matches.append((batch, launch, complete))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(matches, key=lambda item: item[1].get("started_at", 0), reverse=True)


def launch(arguments):
    """Keep launcher output live, recording its exact batch path."""
    command = ["uv", "run", "program-identity-local", *map(str, arguments)]
    batch = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        try:
            for line in process.stdout:
                print(line, end="", flush=True)
                if line.startswith("Batch: "):
                    batch = Path(line.removeprefix("Batch: ").strip())
            code = process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if code:
        raise subprocess.CalledProcessError(code, command)
    if batch is None:
        raise RuntimeError("launcher returned no batch path")
    return batch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/local-qwen-expanded.yaml")
    parser.add_argument("--seeds", type=int, nargs="+", default=[18, 19, 20])
    parser.add_argument("--dry-run", action="store_true", help="show reuse/resume decisions without writes or GPU use")
    args = parser.parse_args(argv)
    base = yaml.safe_load(args.config.read_text())
    root = Path(base["runs_dir"])
    root = root if root.is_absolute() else ROOT / root
    try:
        for seed in args.seeds:
            cfg = {**base, "seed": seed}
            matrices = {}
            for mode in ("treatment", "guard"):
                candidates = matching_batches(root, cfg, "matrix", mode)
                complete = next((item for item in candidates if item[2]), None)
                matrices[mode] = complete or (candidates[0] if candidates else None)
            if all(item and item[2] for item in matrices.values()):
                print(f"Seed {seed}: both matrices complete; retained")
                continue
            checks = matching_batches(root, cfg, "check", "treatment")
            check = checks[0][0] if checks else None
            print(f"Seed {seed}: check {check if check else 'new clean check required'}", flush=True)
            config_path = root / "configs" / f"seed-{seed}.yaml"
            if not args.dry_run:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
                if check is None:
                    check = launch(["--config", config_path, "--stage", "check"])
            for mode, item in matrices.items():
                if item and item[2]:
                    print(f"Seed {seed} {mode}: retained {item[0]}", flush=True)
                    continue
                print(f"Seed {seed} {mode}: {'resume ' + str(item[0]) if item else 'new matrix'}", flush=True)
                if args.dry_run:
                    continue
                command = ["--config", config_path, "--stage", "matrix", "--check", check]
                if mode == "guard":
                    command.append("--guard")
                if item:
                    command.extend(["--resume", item[0]])
                launch(command)
    except subprocess.CalledProcessError as exc:
        print(f"Sequence stopped (exit {exc.returncode}); rerun the same command to resume.", flush=True)
        return 1
    except KeyboardInterrupt:
        print("Sequence interrupted; rerun the same command to resume.", flush=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
