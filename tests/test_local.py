"""Offline adapter and launcher regressions; no real model or GPU is used."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from program_identity import local
from program_identity.agents import local_chat
from program_identity.tasks import ROOT


def config():
    return yaml.safe_load((ROOT / "configs/local-qwen.yaml").read_text())


def fake_chat(monkeypatch, actions, usage=True):
    responses = iter(actions)
    requests = []
    def call(url, payload=None, timeout=30):
        requests.append((url, payload))
        if url.endswith("/tokenize"):
            return {"count": 20}
        action = next(responses)
        if isinstance(action, Exception):
            raise action
        response = {"choices": [{"message": {"content": json.dumps(action)}, "finish_reason": "stop"}]}
        if usage:
            response["usage"] = {"prompt_tokens": 20, "completion_tokens": 10}
        return response
    monkeypatch.setattr(local_chat, "local_json", call)
    return requests


def agent_run(tmp_path, monkeypatch, actions, *, treatment="ordinary", cap=200, usage=True):
    cfg = config()
    cfg["model"].update(base_url="http://127.0.0.1:8000/v1", api_model="test")
    cfg["budgets"]["max_tokens"] = cap
    calls = fake_chat(monkeypatch, actions, usage=usage)
    executed = []
    def execute(argv):
        executed.append(argv)
        return {"command_id": "cmd-1", "exit_code": 0, "output": "ok", "command": "python -c ..."}
    answer = local_chat.LocalChatAgent().run("Repair the function.", tmp_path, execute,
                                            treatment, cfg["model"], 17, cfg["budgets"])
    return answer, calls, executed


def test_adapter_commands_final_response_and_usage_are_recorded(tmp_path, monkeypatch):
    actions = [{"action": "run", "argv": ["python", "-c", "print(1)"]},
               {"action": "final", "text": "Implemented; public checks passed."}]
    result, requests, executed = agent_run(tmp_path, monkeypatch, actions)
    assert result.termination == "completed"
    assert executed == [["python", "-c", "print(1)"]]
    assert result.usage == {"input_tokens": 40, "output_tokens": 20, "cost": None}
    completions = [payload for url, payload in requests if url.endswith("/chat/completions")]
    assert all(p["seed"] == 17 and p["chat_template_kwargs"] == {"enable_thinking": False} for p in completions)
    assert "cmd-1" in completions[-1]["messages"][-1]["content"]
    assert "loaded_sha256" not in json.dumps(completions)
    assert any(e.get("response") for e in result.trajectory)


def test_adapter_enforces_token_cap_before_generation(tmp_path, monkeypatch):
    result, requests, executed = agent_run(tmp_path, monkeypatch, [], cap=10)
    assert result.termination == "context_or_token_budget_exhausted"
    assert not executed
    assert not any(url.endswith("/chat/completions") for url, _ in requests)


def test_adapter_usage_is_nullable_and_errors_do_not_become_claims(tmp_path, monkeypatch):
    result, _, _ = agent_run(tmp_path, monkeypatch, [RuntimeError("server unavailable")])
    assert result.termination == "inference_error" and result.final_response == ""
    assert result.usage["input_tokens"] is None and result.usage["output_tokens"] is None
    result, _, _ = agent_run(tmp_path, monkeypatch, [{"action": "final", "text": "Done."}], cap=None, usage=False)
    assert result.termination == "completed" and result.usage["input_tokens"] is None
    result, _, _ = agent_run(tmp_path, monkeypatch, [{"action": "final", "text": "Done."}], usage=False)
    assert result.termination == "usage_unknown" and not result.final_response


def test_invalid_action_is_logged_and_repaired(tmp_path, monkeypatch):
    result, _, executed = agent_run(tmp_path, monkeypatch, ["invalid", {"action": "final", "text": "Unable to complete."}])
    assert not executed and result.termination == "completed"
    assert result.trajectory[0]["protocol_error"]


def test_local_dry_run_has_nine_cells_without_side_effects(capsys):
    assert local.main(["--stage", "matrix", "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["runs"]) == 9 and plan["mode"] == "treatment"
    assert "Qwen/Qwen3-4B" in plan["server_command"]
    assert "127.0.0.1" in plan["server_command"]
    assert local.main(["--stage", "matrix", "--guard", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "guard"


def test_local_validation_rejects_unbounded_or_invalid_configuration():
    cfg = config()
    assert local.validate_local(cfg) == []
    cfg["budgets"]["run_timeout_seconds"] = None
    assert local.validate_local(cfg)
    cfg = config()
    cfg["server"] = None
    assert local.validate_local(cfg) == ["server must be a mapping"]
    cfg = config()
    cfg["model"]["top_p"] = "invalid"
    assert local.validate_local(cfg)


def test_revision_is_resolved_to_commit(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({"sha": "a" * 40}).encode()
    monkeypatch.setattr(local.urllib.request, "urlopen", lambda *a, **k: Response())
    model = config()["model"]
    identity = local.resolve_checkpoint(model)
    assert model["revision"] == "a" * 40 and identity["requested_revision"] == "main"


def mock_server_environment(tmp_path, monkeypatch):
    cfg = config()
    cfg["runs_dir"] = str(tmp_path / "batches")
    cfg["server"]["environment"] = str(tmp_path / "model-env")
    python = tmp_path / "model-env/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    path = tmp_path / "local.yaml"
    path.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(local.sys, "platform", "linux")
    monkeypatch.setattr(local, "resolve_checkpoint", lambda model: {"kind": "mock", "sha": "a" * 40})
    original_run, original_output, original_popen = subprocess.run, subprocess.check_output, subprocess.Popen
    def run(argv, *args, **kwargs):
        if argv[0] == "nvidia-smi":
            return subprocess.CompletedProcess(argv, 0, "Mock GPU, 16 GiB, mock driver\n", "")
        if argv[:3] == ["uv", "pip", "install"] and str(python) in argv:
            return subprocess.CompletedProcess(argv, 0)
        return original_run(argv, *args, **kwargs)
    def output(argv, *args, **kwargs):
        if argv[:3] == ["uv", "pip", "freeze"]:
            return "vllm==0.29.0\n"
        if "import importlib.metadata; print(importlib.metadata.version('vllm'))" in argv:
            return "0.29.0\n"
        return original_output(argv, *args, **kwargs)
    class FakeProcess:
        pid = 999999
        def poll(self):
            return None
    def popen(argv, *args, **kwargs):
        if "vllm" in argv and "serve" in argv:
            return FakeProcess()
        return original_popen(argv, *args, **kwargs)
    stopped = []
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "check_output", output)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(local, "stop_server", lambda process: stopped.append(process))
    monkeypatch.setattr(local, "wait_ready", lambda process, base, alias, timeout: {"data": [{"id": alias}]})
    # The preflight socket is independent from the inference server; avoid a real listener.
    class Probe:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def setsockopt(self, *args):
            pass
        def bind(self, *args):
            pass
    monkeypatch.setattr(local.socket, "socket", Probe)
    return path, cfg, stopped


def test_launcher_end_to_end_with_mock_model_and_real_evaluator(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    source = "import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n"
    fake_chat(monkeypatch, [
        {"action": "run", "argv": ["python", "-c", f"from pathlib import Path; Path('checkout/package/rules.py').write_text({source!r})"]},
        {"action": "run", "argv": ["python", "-m", "pytest", "-q", "public_tests"]},
        {"action": "final", "text": "Updated the function and ran the public tests."},
    ])
    assert local.main(["--config", str(path)]) == 0
    batch = next(Path(cfg["runs_dir"]).iterdir())
    assert json.loads((batch / "launch.json").read_text())["status"] == "completed"
    summary = json.loads((batch / "runs/summary.json").read_text())
    assert summary["run_count"] == 1
    run_dir = next(p for p in (batch / "runs").iterdir() if p.is_dir())
    run = json.loads((run_dir / "run.json").read_text())
    assert run["verified_test_command_ids"]
    assert json.loads((run_dir / "selected_evaluation.json").read_text())["independent_repair_success"]
    assert stopped and stopped[0] is not None


def test_launcher_retains_failure_and_cleans_up_on_readiness_error(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    def fail(*args):
        raise TimeoutError("mock readiness timeout")
    monkeypatch.setattr(local, "wait_ready", fail)
    assert local.main(["--config", str(path)]) == 1
    batch = next(Path(cfg["runs_dir"]).iterdir())
    launch = json.loads((batch / "launch.json").read_text())
    assert launch["status"] == "failed" and "timeout" in launch["error"]
    assert stopped and stopped[0] is not None
    assert (batch / "runs/summary.json").is_file()


def test_local_api_rejects_external_endpoints():
    with pytest.raises(ValueError, match="local HTTP"):
        local_chat.local_json("https://example.com/v1/models")


def test_launcher_interrupt_stops_server_and_saves_partial_batch(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    def interrupt(*args):
        raise KeyboardInterrupt("mock interrupt")
    monkeypatch.setattr(local, "wait_ready", interrupt)
    assert local.main(["--config", str(path)]) == 130
    batch = next(Path(cfg["runs_dir"]).iterdir())
    assert json.loads((batch / "launch.json").read_text())["status"] == "interrupted"
    assert stopped[0] is not None


def test_shutdown_kills_remaining_worker_group_even_if_parent_exits(monkeypatch):
    signals = []
    monkeypatch.setattr(local.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    class Process:
        pid = 123456
        def wait(self, timeout):
            return 0
    local.stop_server(Process())
    assert signals == [(123456, local.signal.SIGTERM), (123456, local.signal.SIGKILL)]


def test_interrupted_command_terminates_its_process_group(monkeypatch, tmp_path):
    from program_identity.execution import run_process_group
    signals = []
    class Process:
        pid = 123456
        calls = 0
        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt()
            return "", ""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(local.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        run_process_group(["mock"], tmp_path, {}, 1)
    assert signals == [(123456, local.signal.SIGTERM)]


def test_readiness_requires_expected_alias_and_checks_server_exit(monkeypatch):
    class Process:
        returncode = 1
        exited = False
        def poll(self):
            return self.returncode if self.exited else None
    process = Process()
    monkeypatch.setattr(local, "local_json", lambda *a, **k: {"data": [{"id": "expected"}]})
    assert local.wait_ready(process, "http://127.0.0.1:8000/v1", "expected", 1)["data"]
    process.exited = True
    with pytest.raises(RuntimeError, match="exited with code 1"):
        local.wait_ready(process, "http://127.0.0.1:8000/v1", "expected", 1)
