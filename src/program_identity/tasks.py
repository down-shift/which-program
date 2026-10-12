"""Task loading, immutable hash helpers, and baseline fixture validation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from .uv_support import uv_environment

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"


def load_task(task_id: str) -> tuple[dict, Path]:
    path = TASKS / task_id
    return yaml.safe_load((path / "task.yaml").read_text()), path


def task_hashes(task_id: str) -> dict[str, str]:
    _, path = load_task(task_id)
    return _hashes(path)


def _hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _run_public(task: Path, import_root: Path) -> subprocess.CompletedProcess:
    env = uv_environment()
    env["PYTHONPATH"] = str(import_root.resolve())
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(["uv", "run", "--no-project", "--python", sys.executable, "--",
                           "python", "-B", "-m", "pytest", "-q", str(task / "public_tests")],
                          cwd=task, env=env, capture_output=True, text=True, timeout=45)


def _import_origin(task: Path, import_root: Path) -> Path | None:
    env = uv_environment()
    env["PYTHONPATH"] = str(import_root.resolve())
    proc = subprocess.run(["uv", "run", "--no-project", "--python", sys.executable, "--",
                           "python", "-B", "-c", "import package.rules; print(package.rules.__file__)"],
                          cwd=task, env=env, capture_output=True, text=True, timeout=20)
    if proc.returncode:
        return None
    return Path(proc.stdout.strip().splitlines()[-1]).resolve()


def validate_tasks() -> list[str]:
    errors = []
    for task in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        try:
            meta = yaml.safe_load((task / "task.yaml").read_text())
            required = ("package", "module", "editable_paths", "allowed_patch_scope", "monitored_modules", "dependency_scope")
            for key in required:
                if key not in meta:
                    errors.append(f"{task.name}: missing {key}")
            for rel in ("instruction.md", "starter/package/__init__.py", "starter/package/rules.py",
                        "public_tests/test_public.py", "trusted_tests/test_regression.py",
                        "alternate/package/rules.py", "reference.patch", "alternate/differences.md"):
                if not (task / rel).is_file():
                    errors.append(f"{task.name}: missing {rel}")
            patch = (task / "reference.patch").read_text()
            if "@@ -" not in patch or "+++ b/" not in patch:
                errors.append(f"{task.name}: reference.patch is not a ranged unified diff")
            else:
                with tempfile.TemporaryDirectory(prefix="pi-task-patch-") as temp:
                    tmp = Path(temp)
                    shutil.copytree(task / "starter", tmp / "starter")
                    subprocess.run(["git", "init", "-q", str(tmp / "starter")], check=True, capture_output=True)
                    diff = tmp / "reference.patch"
                    shutil.copy2(task / "reference.patch", diff)
                    check = subprocess.run(["git", "-C", str(tmp / "starter"), "apply", "--check", str(diff)], capture_output=True)
                    if check.returncode:
                        errors.append(f"{task.name}: reference.patch does not apply: {check.stderr.decode(errors='replace')}")
                    else:
                        apply = subprocess.run(["git", "-C", str(tmp / "starter"), "apply", str(diff)], capture_output=True)
                        if apply.returncode:
                            errors.append(f"{task.name}: reference.patch application failed")
                        else:
                            # The reference output must pass trusted tests in its own target tree.
                            env = uv_environment()
                            env["PYTHONPATH"] = str((tmp / "starter").resolve())
                            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
                            trusted = subprocess.run(["uv", "run", "--no-project", "--python", sys.executable,
                                                      "--", "python", "-B", "-m", "pytest", "-q",
                                                      str(task / "trusted_tests")], cwd=tmp / "starter",
                                                     env=env, capture_output=True, text=True, timeout=45)
                            if trusted.returncode:
                                errors.append(f"{task.name}: reference patch fails trusted tests: {trusted.stdout}{trusted.stderr}")
            baseline = _run_public(task, task / "starter")
            baseline_output = baseline.stdout + baseline.stderr
            if baseline.returncode == 0 or "FAILED" not in baseline_output or "ERROR" in baseline_output:
                errors.append(f"{task.name}: starter public checks must fail as assertion failures")
            alternate = _run_public(task, task / "alternate")
            if alternate.returncode != 0:
                errors.append(f"{task.name}: alternate public checks expected pass: {alternate.stdout}{alternate.stderr}")
            alternate_trusted = subprocess.run(["uv", "run", "--no-project", "--python", sys.executable,
                                                "--", "python", "-B", "-m", "pytest", "-q",
                                                str(task / "trusted_tests")], cwd=task,
                                               env={**uv_environment(), "PYTHONPATH": str((task / "alternate").resolve()),
                                                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                                               capture_output=True, text=True, timeout=45)
            alt_output = alternate_trusted.stdout + alternate_trusted.stderr
            if alternate_trusted.returncode == 0 or "FAILED" not in alt_output or "ERROR" in alt_output:
                errors.append(f"{task.name}: alternate trusted checks must fail as assertion failures")
            starter_origin = _import_origin(task, task / "starter")
            alternate_origin = _import_origin(task, task / "alternate")
            expected_starter = (task / "starter" / meta["package"] / "rules.py").resolve()
            expected_alternate = (task / "alternate" / meta["package"] / "rules.py").resolve()
            if starter_origin != expected_starter:
                errors.append(f"{task.name}: clean import resolved to {starter_origin}, expected {expected_starter}")
            if alternate_origin != expected_alternate:
                errors.append(f"{task.name}: alternate import resolved to {alternate_origin}, expected {expected_alternate}")
            for module in meta.get("monitored_modules", []):
                filename = "__init__.py" if module == meta["package"] else module.rsplit(".", 1)[-1] + ".py"
                target = task / "starter" / meta["package"] / filename
                if not target.exists():
                    errors.append(f"{task.name}: monitored target is missing: {module}")
        except Exception as exc:
            errors.append(f"{task.name}: {type(exc).__name__}: {exc}")
    return errors
