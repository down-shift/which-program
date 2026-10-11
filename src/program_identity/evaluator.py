import json, shutil, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from .execution import read_jsonl, run_command
from .uv_support import uv_environment

def evaluate(run_dir: Path, task_root: Path, meta: dict) -> dict:
    run_dir=run_dir.resolve(); task_root=task_root.resolve()
    out=run_dir/"evaluator"
    if out.exists(): out=run_dir/f"evaluator-{uuid.uuid4().hex[:8]}"
    out.mkdir(exist_ok=False)
    work=Path(tempfile.mkdtemp(prefix="pi-eval-")); shutil.copytree(task_root/"starter",work/"src")
    delivered=run_dir/"workspace"
    violations=[]
    for rel in meta["allowed_patch_scope"]:
        if (delivered/rel).exists(): shutil.copy2(delivered/rel,work/"src"/rel)
    for p in delivered.rglob("*"):
        if p.is_file():
            rel=str(p.relative_to(delivered)); original=task_root/"starter"/rel
            if rel.startswith("public_tests/"): original=task_root/rel
            if rel not in meta["allowed_patch_scope"] and (not original.exists() or p.read_bytes()!=original.read_bytes()): violations.append(rel)
    target=work/"src"; logs=out
    task={**meta,"module":meta["module"]}
    # Use a fresh venv-style source path and trusted tests external to evaluator workspace.
    envroot=work/"env"; envroot.mkdir()
    srcpkg=target/meta["package"]; shutil.copytree(srcpkg,envroot/meta["package"])
    import os
    env=uv_environment(); env.update({"PYTHONPATH":os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).parent.parent),str(envroot)]),"PI_PROVENANCE_FILE":str(out/"provenance.jsonl"),"PI_RUN_ID":run_dir.name+"-eval","PI_COMMAND_ID":"trusted","PI_RELEVANT_MODULES":meta["module"],"PI_TARGET_ROOT":str(envroot/meta["package"]),"PI_IMPORT_ROOT":str(envroot/meta["package"]),"PYTHONDONTWRITEBYTECODE":"1"})
    start=time.time()
    try: p=subprocess.run(["uv","run","--no-project","--python",sys.executable,"--","python","-B","-m","pytest","-q",str(task_root/"trusted_tests")],cwd=work,env=env,capture_output=True,text=True,timeout=60); code=p.returncode; stdout=p.stdout; stderr=p.stderr
    except subprocess.TimeoutExpired as e: code=124; stdout=e.stdout or ""; stderr=e.stderr or "TIMEOUT"
    prov=read_jsonl(out/"provenance.jsonl")
    identity="unknown" if not prov else ("match" if all(x.get("instrumentation")=="ok" and x.get("content_match") is True and x.get("path_match") is True for x in prov) else "mismatch_or_unknown")
    result={"schema_version":1,"patch_application_error":None,"scope_violations":violations,"test_exit_code":code,"tests_passed":code==0,"stdout":stdout,"stderr":stderr,"duration_seconds":time.time()-start,"identity":identity,"identity_records":prov,"evaluation_directory":str(out)}
    (out/"result.json").write_text(json.dumps(result,indent=2)); shutil.rmtree(work,ignore_errors=True); return result
