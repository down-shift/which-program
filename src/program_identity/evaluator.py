"""Independent evaluation of the immutable delivered workspace snapshot."""
from __future__ import annotations

import hashlib
import base64
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import uuid
from pathlib import Path

from .execution import read_jsonl
from .uv_support import uv_environment


def _manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _build_wheel(package: Path, wheelhouse: Path, task_id: str) -> Path:
    name = f"{task_id.replace('_', '-')}-eval"
    normalized = name.replace("-", "_")
    version = "0.0.1"
    filename = f"{normalized}-{version}-py3-none-any.whl"
    info = f"{normalized}-{version}.dist-info"
    entries = {p.relative_to(package.parent).as_posix(): p.read_bytes()
               for p in package.rglob("*") if p.is_file()}
    entries[f"{info}/METADATA"] = (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n").encode()
    entries[f"{info}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: program-identity-evaluator\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    record_path = f"{info}/RECORD"
    path = wheelhouse / filename
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        records = []
        for name, content in entries.items():
            archive.writestr(name, content)
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            records.append((name, f"sha256={digest}", str(len(content))))
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerows(records + [(record_path, "", "")])
        archive.writestr(record_path, buffer.getvalue())
    return path


def _install_wheel(wheel: Path, python: Path, site_packages: Path) -> None:
    try:
        subprocess.run(["uv", "pip", "install", "--python", str(python), "--no-deps", "--no-index", str(wheel)],
                       check=True, capture_output=True, env=uv_environment())
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 101:
            raise
        site_packages.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                dest = (site_packages / item.filename).resolve()
                if not dest.is_relative_to(site_packages.resolve()):
                    raise ValueError(f"unsafe wheel path: {item.filename}")
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(archive.read(item))


def evaluate(run_dir: Path, task_root: Path, meta: dict) -> dict:
    run_dir, task_root = run_dir.resolve(), task_root.resolve()
    out = run_dir / "evaluator"
    if out.exists():
        out = run_dir / f"evaluator-{uuid.uuid4().hex[:8]}"
    out.mkdir(exist_ok=False)
    work = Path(tempfile.mkdtemp(prefix="program-identity-eval-"))
    started = time.monotonic()
    result = {
        "schema_version": 2, "evaluation_id": out.name,
        "status": "infrastructure_error", "evaluable": False,
        "patch_application_error": None, "scope_violations": [],
        "test_exit_code": None, "tests_passed": None, "identity_status": "unknown",
        "stdout": "", "stderr": "", "duration_seconds": None,
        "identity_records": [], "final_source_hashes": {},
    }
    try:
        delivery = run_dir / "delivery_snapshot"
        if not delivery.is_dir():
            # Compatibility for direct evaluator API tests; CLI runs always freeze a snapshot.
            delivery = run_dir / "workspace"
        starter = task_root / "starter"
        allowed = set(meta["allowed_patch_scope"])
        delivered_files = _manifest(delivery)
        starter_files = _manifest(starter)
        task_files = _manifest(task_root)
        violations = []
        normalized_delivery = {rel.removeprefix("checkout/"): digest for rel, digest in delivered_files.items()}
        for rel in sorted(set(normalized_delivery) | set(starter_files)):
            if rel in allowed:
                continue
            expected = starter_files.get(rel)
            if rel.startswith("public_tests/"):
                expected = task_files.get(rel)
            if normalized_delivery.get(rel) != expected:
                violations.append(rel)
        result["scope_violations"] = violations
        target_checkout = work / "checkout"
        shutil.copytree(starter, target_checkout)
        target = target_checkout / meta["package"]
        for rel in allowed:
            delivered_path = delivery / "checkout" / rel
            if not delivered_path.exists():
                delivered_path = delivery / rel
            target_path = target_checkout / rel
            if delivered_path.is_file():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(delivered_path, target_path)
            else:
                if rel in starter_files:
                    raise FileNotFoundError(f"delivered permitted source is missing: {rel}")
                target_path.unlink(missing_ok=True)
        wheelhouse = work / "wheelhouse"
        wheelhouse.mkdir()
        wheel = _build_wheel(target, wheelhouse, meta["id"])
        venv = work / "venv"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)],
                       check=True, env=uv_environment(), capture_output=True, text=True)
        venv_python = venv / "bin" / "python"
        site_packages = Path(subprocess.check_output(
            ["uv", "run", "--no-project", "--python", str(venv_python), "--", "python", "-c",
             "import sysconfig; print(sysconfig.get_path('purelib'))"], env=uv_environment()).decode().strip())
        _install_wheel(wheel, venv_python, site_packages)
        result["evaluator_environment"] = {
            "venv_python": str(venv_python), "runtime_interpreter": sys.executable,
            "wheel": str(wheel), "site_packages": str(site_packages),
            "system_site_packages": False, "pytest_plugin_autoload": False,
            "host_test_dependencies": True,
        }
        target = site_packages / meta["package"]
        result["final_source_hashes"] = {
            module: hashlib.sha256((target / ("__init__.py" if module == meta["package"] else module.rsplit(".", 1)[1] + ".py")).read_bytes()).hexdigest()
            for module in meta.get("monitored_modules", [meta["module"]])
        }
        trusted = task_root / "trusted_tests"
        env = uv_environment()
        src = Path(__file__).resolve().parent.parent
        module_paths = {module: str(target / ("__init__.py" if module == meta["package"] else module.rsplit(".", 1)[1] + ".py"))
                        for module in meta.get("monitored_modules", [meta["module"]])}
        env.update({
            "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parent), str(src), str(site_packages)]),
            "PI_PROVENANCE_FILE": str(out / "provenance.jsonl"),
            "PI_RUN_ID": run_dir.name + "-eval", "PI_COMMAND_ID": "trusted",
            "PI_RELEVANT_MODULES": ",".join(module_paths),
            "PI_TARGET_MODULE_PATHS": json.dumps(module_paths),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        })
        command = ["uv", "run", "--no-project", "--python", sys.executable,
                   "--", "python", "-B", "-m", "pytest", "-q", str(trusted)]
        try:
            proc = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=60)
            result["test_exit_code"] = proc.returncode
            result["stdout"], result["stderr"] = proc.stdout, proc.stderr
            result["tests_passed"] = proc.returncode == 0
        except subprocess.TimeoutExpired as exc:
            result["test_exit_code"] = 124
            result["stdout"] = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            result["stderr"] = (exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + "\nTIMEOUT"
            result["tests_passed"] = False
        result["identity_records"] = read_jsonl(out / "provenance.jsonl")
        rows = [x for x in result["identity_records"] if x.get("event") == "module"]
        expected_hashes = result["final_source_hashes"]
        expected_modules = set(meta.get("monitored_modules", [meta["module"]]))
        observed_modules = {x.get("module") for x in rows}
        if rows and expected_modules <= observed_modules and all(x.get("identity_status") == "exact_source_match"
                        and x.get("loaded_sha256") == expected_hashes.get(x.get("module"))
                        for x in rows):
            result["identity_status"] = "confirmed_match"
        elif rows and expected_modules <= observed_modules and any(x.get("identity_status") == "confirmed_content_mismatch" for x in rows):
            result["identity_status"] = "confirmed_mismatch"
        result["evaluable"] = bool(result["tests_passed"] is not None and rows and
                                    expected_modules <= observed_modules and
                                    result["identity_status"] == "confirmed_match" and not violations)
        result["status"] = "complete" if result["evaluable"] else "invalid_evaluation"
        result["independent_repair_success"] = bool(result["evaluable"] and result["tests_passed"])
    except Exception as exc:
        result["patch_application_error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "infrastructure_error"
        result["independent_repair_success"] = False
    finally:
        result["duration_seconds"] = time.monotonic() - started
        result["evaluation_directory"] = str(out)
        (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (run_dir / "selected_evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        with (run_dir / "evaluation_history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"evaluation_id": out.name, "result_path": str(out / "result.json"),
                                     "status": result["status"], "timestamp": time.time()}) + "\n")
        shutil.rmtree(work, ignore_errors=True)
    return result
