from pathlib import Path
import hashlib, json, subprocess, sys, os
from .uv_support import uv_environment
import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"

def load_task(task_id: str) -> tuple[dict, Path]:
    path = TASKS / task_id
    meta = yaml.safe_load((path / "task.yaml").read_text())
    return meta, path

def task_hashes(task_id: str) -> dict[str, str]:
    _, path = load_task(task_id)
    out = {}
    for p in sorted(path.rglob("*")):
        if p.is_file(): out[str(p.relative_to(path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def validate_tasks() -> list[str]:
    errors=[]
    for p in sorted(TASKS.iterdir()):
        if not p.is_dir(): continue
        try:
            meta=yaml.safe_load((p/"task.yaml").read_text())
            for key in ("package", "module", "editable_paths", "allowed_patch_scope"):
                if key not in meta: errors.append(f"{p.name}: missing {key}")
            for f in ("instruction.md", "starter/package/__init__.py", "public_tests/test_public.py", "trusted_tests/test_regression.py", "alternate/package/rules.py", "reference.patch"):
                if not (p/f).exists(): errors.append(f"{p.name}: missing {f}")
            if meta.get("alternate_public_tests_expected"):
                env=os.environ.copy(); env["PYTHONPATH"]=str((p/"alternate").resolve())
                env=uv_environment(env)
                check=subprocess.run(["uv","run","--no-project","--python",sys.executable,"--","python","-B","-m","pytest","-q",str(p/"public_tests")],cwd=p,env=env,capture_output=True,timeout=30)
                actual="pass" if check.returncode==0 else "fail"
                if actual!=meta["alternate_public_tests_expected"]: errors.append(f"{p.name}: alternate public tests expected {meta['alternate_public_tests_expected']}, got {actual}")
        except Exception as e: errors.append(f"{p.name}: {e}")
    return errors
