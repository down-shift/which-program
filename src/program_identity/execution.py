"""Structured local command runner and command-level provenance association."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .uv_support import uv_environment


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _is_python(token: str) -> bool:
    name = Path(token).name
    return name in {"python", "python3", Path(sys.executable).name} or name.startswith("python3.")


def _test_command(argv: list[str]) -> bool:
    if not argv:
        return False
    if Path(argv[0]).name == "pytest":
        return True
    if Path(argv[0]).name == "uv" and "run" in argv:
        if "--" in argv:
            return _test_command(argv[argv.index("--") + 1:])
        index = argv.index("run") + 1
        return _test_command(argv[index:])
    if _is_python(argv[0]):
        return any(argv[i:i + 2] == ["-m", "pytest"] for i in range(len(argv) - 1))
    return False


def run_command(command: str | list[str], cwd: Path, run_id: str, cmd_id: str, task: dict,
                logs: Path, target_root: Path, import_root: Path, treatment: str,
                guard=False, timeout=120, interpreter: Path | None = None):
    original = command if isinstance(command, str) else shlex.join(command)
    try:
        argv = shlex.split(command) if isinstance(command, str) else list(command)
        if any(x in ("|", ";", "&&", "||", ">", "<") for x in argv):
            raise ValueError("shell operators are unsupported; pass a direct command")
    except Exception as exc:
        argv = []
        parse_error = f"{type(exc).__name__}: {exc}"
    else:
        parse_error = None
    requested_argv = list(argv)
    command_env = {}
    while argv and "=" in argv[0] and argv[0].split("=", 1)[0].replace("_", "a").isalnum():
        key, value = argv.pop(0).split("=", 1)
        command_env[key] = os.path.expandvars(value)
    recognized_test = _test_command(argv)
    guard_status = None
    if guard:
        if recognized_test:
            guard_status = "enforced"
            if Path(argv[0]).name == "uv":
                if "--" in argv:
                    inner = argv.index("--") + 1
                else:
                    inner = argv.index("run") + 1
                    while inner < len(argv) and argv[inner].startswith("-"):
                        inner += 2 if argv[inner] in ("--python", "--directory", "--project") else 1
                if inner < len(argv) and Path(argv[inner]).name == "pytest":
                    argv[inner:inner + 1] = ["python", "-B", "-m", "pytest"]
                elif inner < len(argv) and _is_python(argv[inner]) and "-B" not in argv[inner:]:
                    argv.insert(inner + 1, "-B")
            elif Path(argv[0]).name == "pytest":
                argv = ["python", "-B", "-m", "pytest", *argv[1:]]
            # -B ensures Python will not read or write bytecode caches.
            if _is_python(argv[0]) and "-B" not in argv:
                argv.insert(1, "-B")
        else:
            guard_status = "unsupported_command"

    selected = interpreter or Path(sys.executable)
    env = uv_environment()
    env.update(command_env)
    py = _is_python(argv[0]) if argv else False
    if py:
        tail = argv[1:]
        if command_env.get("PATH"):
            resolved = shutil.which(argv[0], path=env["PATH"])
            if resolved:
                selected = Path(resolved)
        if argv[0] != "python" and argv[0] != "python3" and Path(argv[0]).is_absolute():
            selected = Path(argv[0])
        actual = ["uv", "run", "--no-project", "--python", str(selected), "--", "python", *tail]
    elif argv and Path(argv[0]).name == "pytest":
        actual = ["uv", "run", "--no-project", "--python", str(selected), "--", "python", "-m", "pytest", *argv[1:]]
    else:
        actual = argv

    requested_import_path = command_env.get("PYTHONPATH")
    runtime_import = target_root.parent if guard and recognized_test else import_root.parent
    src = Path(__file__).resolve().parent.parent
    import_parts = [str(Path(__file__).resolve().parent), str(src)]
    if requested_import_path and not (guard and recognized_test):
        import_parts.extend(str((cwd / item).resolve()) if not Path(item).is_absolute() else item
                            for item in requested_import_path.split(os.pathsep) if item)
    else:
        import_parts.append(str(runtime_import))
    env.update({
        "PYTHONPATH": os.pathsep.join(import_parts),
        "PI_PROVENANCE_FILE": str(logs / "provenance.jsonl"),
        "PI_RUN_ID": run_id,
        "PI_COMMAND_ID": cmd_id,
        "PI_RELEVANT_MODULES": ",".join(task.get("monitored_modules", [task["module"]])),
        "PI_TARGET_MODULE_PATHS": json.dumps(task.get("target_module_paths", {task["module"]: str(target_root / "rules.py")})),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    # Evidence treatments govern what is shown, never what is retained by the observer.
    recorded_env = {k: env[k] for k in (
        "PATH", "PYTHONPATH", "PI_PROVENANCE_FILE", "PI_RUN_ID", "PI_COMMAND_ID",
        "PI_RELEVANT_MODULES", "PI_TARGET_MODULE_PATHS", "PYTHONDONTWRITEBYTECODE",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD")}
    start_wall, start = time.time(), time.monotonic()
    stdout = stderr = ""
    code = 127
    launch_error = parse_error
    if not parse_error:
        try:
            process = subprocess.Popen(actual, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                       errors="replace", start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                code = process.returncode
            except subprocess.TimeoutExpired as exc:
                partial_out, partial_err = _text(exc.stdout), _text(exc.stderr)
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    stdout, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                code = 124
                stdout = stdout or partial_out
                stderr = (stderr or partial_err) + "\nTIMEOUT"
        except OSError as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            stderr, code = launch_error, 127
    duration = time.monotonic() - start
    finished_wall = time.time()
    events = [x for x in read_jsonl(logs / "provenance.jsonl") if x.get("command_id") == cmd_id]
    module_rows = [x for x in events if x.get("event") == "module"]
    starts = [x for x in events if x.get("event") == "process_start"]
    ends = [x for x in events if x.get("event") == "process_end"]
    pids = {x.get("pid") for x in starts + ends}
    process_statuses = {pid: ("complete" if any(x.get("pid") == pid for x in starts) and
                              any(x.get("pid") == pid for x in ends) else
                              "process_incomplete" if any(x.get("pid") == pid for x in starts) else
                              "observer_missing") for pid in pids}
    if py or recognized_test:
        observer_status = "ok" if starts and ends and all(x == "complete" for x in process_statuses.values()) else "partial_or_missing"
    else:
        observer_status = "not_applicable"
    module_observation = {
        module: {"status": "observed" if any(r.get("module") == module for r in module_rows) else
                 "no_module_event" if starts and ends else "observer_missing",
                 "records": sum(r.get("module") == module for r in module_rows)}
        for module in task.get("monitored_modules", [task["module"]])
    }
    record = {
        "schema_version": 2, "command_id": cmd_id, "command": original,
        "argv": requested_argv, "normalized_argv": argv, "executed_argv": actual, "cwd": str(cwd),
        "environment": recorded_env, "exit_code": code, "stdout": stdout, "stderr": stderr,
        "launch_error": launch_error, "started_at": start_wall, "finished_at": finished_wall,
        "duration_seconds": duration,
        "is_test_command": recognized_test, "guard_status": guard_status,
        "observer_status": observer_status, "provenance_event_count": len(module_rows),
        "process_statuses": process_statuses, "module_observation": module_observation,
    }
    with (logs / "commands.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    shown = stdout + stderr
    if treatment in ("provenance", "instruction"):
        shown += "\n[Runtime provenance]\n" + json.dumps(module_rows, indent=2)
    return {"command_id": cmd_id, "command": original, "exit_code": code,
            "output": shown, "duration_seconds": duration, "is_test_command": recognized_test,
            "guard_status": guard_status}


def read_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"event": "malformed_record", "raw": line})
    return out
