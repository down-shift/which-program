import hashlib, json, os, subprocess, sys
from pathlib import Path
from program_identity.tasks import ROOT, load_task, validate_tasks
from program_identity.execution import run_command, read_jsonl
from program_identity.evaluator import evaluate
from program_identity.analysis import summarize

def test_tasks_valid(): assert validate_tasks()==[]

def test_clean_and_alternate_identity(tmp_path):
    meta,tp=load_task("normalize_code"); target=tmp_path/"target"/"package"; target.mkdir(parents=True)
    import shutil
    shutil.copytree(tp/"starter/package",target,dirs_exist_ok=True)
    logs=tmp_path/"logs"; logs.mkdir(); work=tmp_path/"work"; work.mkdir()
    # Import target from an explicit parent so pytest/cwd cannot mask its origin.
    r=run_command("python3 -c 'import package.rules'",work,"r","c1",meta,logs,target,target,"ordinary")
    row=read_jsonl(logs/"provenance.jsonl")[-1]
    assert row["instrumentation"]=="ok" and row["content_match"] is True
    other=tmp_path/"other"/"package"; other.parent.mkdir(); shutil.copytree(tp/"alternate/package",other)
    run_command("python3 -c 'import package.rules'",work,"r","c2",meta,logs,target,other,"ordinary")
    row=read_jsonl(logs/"provenance.jsonl")[-1]
    assert row["content_match"] is False

def test_installed_copy_mismatch(tmp_path):
    import shutil
    meta,tp=load_task("normalize_code"); target=tmp_path/"checkout/package"; target.parent.mkdir(); shutil.copytree(tp/"starter/package",target)
    installed=tmp_path/"venv/lib/site-packages/package"; installed.parent.mkdir(parents=True); shutil.copytree(tp/"alternate/package",installed)
    logs=tmp_path/"logs"; logs.mkdir(); work=tmp_path/"work"; work.mkdir()
    run_command("python3 -c 'import package.rules'",work,"r","installed",meta,logs,target,installed,"ordinary")
    row=read_jsonl(logs/"provenance.jsonl")[-1]
    assert row["source_path"].startswith(str(installed)) and row["content_match"] is False

def test_same_content_different_path(tmp_path):
    meta,tp=load_task("normalize_code"); target=tmp_path/"target"/"package"; target.mkdir(parents=True)
    import shutil
    shutil.copytree(tp/"starter/package",target,dirs_exist_ok=True); same=tmp_path/"copy"/"package"; same.parent.mkdir(); shutil.copytree(target,same)
    logs=tmp_path/"logs"; logs.mkdir(); work=tmp_path/"work"; work.mkdir()
    run_command("python3 -c 'import package.rules'",work,"r","c",meta,logs,target,same,"ordinary")
    row=read_jsonl(logs/"provenance.jsonl")[-1]
    assert row["path_match"] is False and row["content_match"] is True

def test_instrumentation_unknown_and_loaded_hash_boundary(tmp_path):
    meta,tp=load_task("normalize_code"); target=tmp_path/"p"/"package"; target.mkdir(parents=True)
    import shutil
    shutil.copytree(tp/"starter/package",target,dirs_exist_ok=True); logs=tmp_path/"l"; logs.mkdir(); work=tmp_path/"w"; work.mkdir()
    command="python3 -c 'import package.rules, pathlib; pathlib.Path(package.rules.__file__).write_text(\"changed = True\\n\")'"
    run_command(command,work,"r","c",meta,logs,target,target,"ordinary")
    row=read_jsonl(logs/"provenance.jsonl")[-1]
    assert row["loaded_sha256"] != hashlib.sha256((target/"rules.py").read_bytes()).hexdigest()
    assert row["content_match"] is True

def test_ordinary_does_not_show_provenance(tmp_path):
    meta,tp=load_task("normalize_code"); logs=tmp_path/"l"; logs.mkdir(); work=tmp_path/"w"; work.mkdir(); target=tp/"starter/package"
    r=run_command("python3 -c 'import package.rules'",work,"r","c",meta,logs,target,target,"ordinary")
    assert "Runtime provenance" not in r["output"] and "loaded_sha256" not in r["output"]
    assert read_jsonl(logs/"commands.jsonl")[0]["executed_command"].startswith("uv run --no-project")

def test_aggregation_keeps_guard_separate(tmp_path):
    for i,mode in enumerate(("treatment","guard")):
        d=tmp_path/str(i); (d/"evaluator").mkdir(parents=True); (d/"run.json").write_text(json.dumps({"mode":mode})); (d/"evaluator/result.json").write_text(json.dumps({"tests_passed":True}))
    result,_=summarize(tmp_path); assert result["runs"]==2 and result["guard_runs"]==1 and result["treatment_runs"]==1 and result["unknown_or_missing_provenance_runs"]==2

def test_fresh_evaluator_accepts_correct_and_rejects_incorrect(tmp_path):
    import shutil
    meta,tp=load_task("normalize_code")
    for label,source,expected in (("good","import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n",True),("bad","def normalize_code(code):\n    return code\n",False)):
        d=tmp_path/label; (d/"workspace/package").mkdir(parents=True); shutil.copytree(tp/"starter",d/"workspace",dirs_exist_ok=True)
        (d/"workspace/package/rules.py").write_text(source)
        result=evaluate(d,tp,meta); assert result["tests_passed"] is expected
        assert result["identity"]=="match"

def test_initial_mismatch_then_valid_target_execution(tmp_path):
    import shutil
    meta,tp=load_task("normalize_code"); target=tmp_path/"target/package"; target.parent.mkdir(); shutil.copytree(tp/"starter/package",target)
    other=tmp_path/"other/package"; other.parent.mkdir(); shutil.copytree(tp/"alternate/package",other)
    logs=tmp_path/"logs"; logs.mkdir(); work=tmp_path/"work"; work.mkdir()
    run_command("python3 -c 'import package.rules'",work,"r","initial",meta,logs,target,other,"provenance")
    (target/"rules.py").write_text("import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n")
    checked=run_command(f"python3 -m pytest -q {tp/'public_tests'}",work,"r","verified",meta,logs,target,target,"provenance")
    rows=read_jsonl(logs/"provenance.jsonl")
    assert rows[0]["content_match"] is False and rows[-1]["content_match"] is True and checked["exit_code"]==0

