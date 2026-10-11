import json, os, shlex, subprocess, sys, time, uuid
from pathlib import Path
from .uv_support import uv_environment

def run_command(command: str, cwd: Path, run_id: str, cmd_id: str, task: dict, logs: Path, target_root: Path, import_root: Path, treatment: str, guard=False, timeout=120, interpreter: Path|None=None):
    env=uv_environment(); env.update({"PYTHONPATH":os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).parent.parent),str(import_root.parent),env.get("PYTHONPATH","")]),"PI_PROVENANCE_FILE":str(logs/"provenance.jsonl"),"PI_RUN_ID":run_id,"PI_COMMAND_ID":cmd_id,"PI_RELEVANT_MODULES":task["module"],"PI_TARGET_ROOT":str(target_root),"PI_IMPORT_ROOT":str(import_root),"PYTHONDONTWRITEBYTECODE":"1"})
    shown_env={k:env[k] for k in ("PATH","PYTHONPATH","PI_PROVENANCE_FILE","PI_RELEVANT_MODULES","PI_TARGET_ROOT","PI_IMPORT_ROOT")}
    actual=command
    if command.startswith(("python3 ","python ")):
        selected=interpreter or Path(sys.executable)
        original_interpreter="python3 " if command.startswith("python3 ") else "python "
        actual=f"uv run --no-project --python {shlex.quote(str(selected))} -- python "+command[len(original_interpreter):]
    if guard and "-- python -m pytest" in actual:
        forced=os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).parent.parent),str(target_root.parent)])
        actual=f"PYTHONPATH={shlex.quote(forced)} "+actual.replace("-- python -m pytest","-- python -B -m pytest",1)
    start=time.time()
    try: p=subprocess.run(actual,shell=True,cwd=cwd,env=env,text=True,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired as e: p=None; stdout=e.stdout or ""; stderr=(e.stderr or "")+"\nTIMEOUT"; code=124
    else: stdout,stderr,code=p.stdout,p.stderr,p.returncode
    record={"schema_version":1,"command_id":cmd_id,"command":command,"executed_command":actual,"cwd":str(cwd),"environment":shown_env,"exit_code":code,"stdout":stdout,"stderr":stderr,"duration_seconds":time.time()-start}
    with (logs/"commands.jsonl").open("a") as f:f.write(json.dumps(record)+"\n")
    displayed=stdout+stderr
    if treatment=="ordinary": displayed=stdout+stderr
    elif treatment in ("provenance","instruction"):
        prov=read_jsonl(logs/"provenance.jsonl")
        rows=[x for x in prov if x.get("command_id")==cmd_id]
        displayed += "\n[Runtime provenance]\n"+json.dumps(rows,indent=2)
    return {"command_id":cmd_id,"command":command,"exit_code":code,"output":displayed,"duration_seconds":record["duration_seconds"]}

def read_jsonl(path):
    if not path.exists(): return []
    return [json.loads(x) for x in path.read_text().splitlines() if x]
