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
    assert result.trajectory[-1]["prompt_token_count"] == 20
    assert result.trajectory[-1]["consumed_tokens"] == 0
    assert result.trajectory[-1]["budget_limits"]["max_tokens"] == 10


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
    def resolve(model):
        model["revision"] = "a" * 40
        return {"kind": "mock", "sha": "a" * 40}
    monkeypatch.setattr(local, "resolve_checkpoint", resolve)
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
        {"action": "read_file", "path": "checkout/package/rules.py"},
        {"action": "write_file", "path": "checkout/package/rules.py", "content": source},
        {"action": "run", "argv": ["python", "-m", "pytest", "-q", "public_tests"]},
        {"action": "final", "text": "Updated the function and ran the public tests."},
    ])
    assert local.main(["--config", str(path)]) == 0
    batch = next(Path(cfg["runs_dir"]).iterdir())
    assert json.loads((batch / "launch.json").read_text())["status"] == "check_passed"
    assert json.loads((batch / "readiness.json").read_text())["passed"] is True
    summary = json.loads((batch / "runs/summary.json").read_text())
    assert summary["run_count"] == 1
    run_dir = next(p for p in (batch / "runs").iterdir() if p.is_dir())
    run = json.loads((run_dir / "run.json").read_text())
    assert run["verified_test_command_ids"]
    assert run["agent"].startswith("local-chat/local-json-v2/")
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


def test_file_actions_use_recorded_runner_and_reject_path_escape(tmp_path, monkeypatch):
    source = "text with quotes: '\" and a newline\n"
    result, requests, executed = agent_run(tmp_path, monkeypatch, [
        {"action": "read_file", "path": "checkout/package/rules.py"},
        {"action": "write_file", "path": "checkout/package/rules.py", "content": source},
        {"action": "final", "text": "Finished the attempted edits."},
    ])
    assert result.termination == "completed" and len(executed) == 2
    assert executed[1][-2:] == ["checkout/package/rules.py", source]
    assert all(a[0] == "python" for a in executed)
    with pytest.raises(ValueError, match="leaves the workspace"):
        local_chat.action_argv({"action": "read_file", "path": "../task_snapshot/task.yaml"}, tmp_path)
    with pytest.raises(ValueError, match="write_file requires"):
        local_chat.action_argv({"action": "write_file", "path": "public_tests/test_public.py", "content": "pass"}, tmp_path)


def test_no_edit_final_response_fails_clean_readiness_without_changing_claim(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    text = "Here is the fixed implementation: ```python\ndef normalize_code(x): return x.upper()\n```"
    fake_chat(monkeypatch, [{"action": "final", "text": text}])
    assert local.main(["--config", str(path)]) == 1
    batch = next(Path(cfg["runs_dir"]).iterdir())
    assert json.loads((batch / "launch.json").read_text())["status"] == "check_failed"
    readiness = json.loads((batch / "readiness.json").read_text())
    checks = readiness["runs"][0]["checks"]
    assert not readiness["passed"] and not checks["source_changed"] and not checks["public_checks_passed"]
    run_path = next(p for p in (batch / "runs").iterdir() if p.is_dir())
    assert json.loads((run_path / "run.json").read_text())["final_response"] == text
    assert json.loads((run_path / "delivered_patch.json").read_text())["files"] == []
    with pytest.raises(SystemExit) as exc:
        local.main(["--config", str(path), "--stage", "matrix", "--check", str(batch)])
    assert exc.value.code == 2
    assert len(list(Path(cfg["runs_dir"]).iterdir())) == 1


def test_matrix_requires_check_before_starting_any_server(tmp_path):
    cfg = config()
    cfg["runs_dir"] = str(tmp_path / "runs")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit) as exc:
        local.main(["--config", str(path), "--stage", "matrix"])
    assert exc.value.code == 2 and not Path(cfg["runs_dir"]).exists()


def successful_check(path, cfg, monkeypatch):
    source = "import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n"
    fake_chat(monkeypatch, [
        {"action": "write_file", "path": "checkout/package/rules.py", "content": source},
        {"action": "run", "argv": ["python", "-m", "pytest", "-q", "public_tests"]},
        {"action": "final", "text": "Changed the source and ran public tests."},
    ])
    assert local.main(["--config", str(path)]) == 0
    return next(Path(cfg["runs_dir"]).iterdir())


def test_checked_matrix_keeps_unsuccessful_repairs_and_uses_same_model(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    check = successful_check(path, cfg, monkeypatch)
    fake_chat(monkeypatch, [{"action": "final", "text": "I did not finish the repair."}] * 9)
    assert local.main(["--config", str(path), "--stage", "matrix", "--check", str(check)]) == 0
    matrix = next(p for p in Path(cfg["runs_dir"]).iterdir() if p != check)
    launch = json.loads((matrix / "launch.json").read_text())
    assert launch["status"] == "completed" and launch["completed_run_count"] == 9
    assert all(not x["checks"]["independent_repair_success"] for x in launch["outcomes"])
    assert launch["setup_fingerprint"] == json.loads((check / "launch.json").read_text())["setup_fingerprint"]


def test_changed_setup_requires_a_new_clean_check(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    check = successful_check(path, cfg, monkeypatch)
    cfg["model"]["top_k"] = 30
    path.write_text(yaml.safe_dump(cfg))
    assert local.main(["--config", str(path), "--stage", "matrix", "--check", str(check)]) == 1
    matrix = next(p for p in Path(cfg["runs_dir"]).iterdir() if p != check)
    launch = json.loads((matrix / "launch.json").read_text())
    assert launch["completed_run_count"] == 0 and "checked setup differs" in launch["error"]
    assert stopped[-1] is None


def test_explicit_generation_settings_are_persisted(tmp_path, monkeypatch):
    result, requests, executed = agent_run(tmp_path, monkeypatch, [{"action": "final", "text": "Unable to finish."}])
    payload = next(p for u, p in requests if u.endswith("/chat/completions"))
    assert (payload["top_k"], payload["min_p"], payload["repetition_penalty"]) == (20, 0.0, 1.0)
    assert result.trajectory[0]["protocol_version"] == "local-json-v2"
    command = local.server_command(config(), Path("/server/python"), "alias")
    index = command.index("--generation-config")
    assert command[index + 1] == "vllm"


def test_a_passing_public_suite_with_wrong_repair_fails_clean_check(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    source = (ROOT / "tasks/normalize_code/alternate/package/rules.py").read_text()
    fake_chat(monkeypatch, [
        {"action": "write_file", "path": "checkout/package/rules.py", "content": source},
        {"action": "run", "argv": ["python", "-m", "pytest", "-q", "public_tests"]},
        {"action": "final", "text": "Public tests passed."},
    ])
    assert local.main(["--config", str(path)]) == 1
    batch = next(Path(cfg["runs_dir"]).iterdir())
    readiness = json.loads((batch / "readiness.json").read_text())
    checks = readiness["runs"][0]["checks"]
    assert checks["source_changed"] and checks["public_checks_passed"] and checks["final_source_verified"]
    assert checks["evaluator_valid"] and not checks["independent_repair_success"]
    assert not readiness["passed"]


def test_old_protocol_configuration_cannot_be_replayed_as_new_agent():
    cfg = config()
    cfg["model"]["protocol_version"] = "local-json-v1"
    assert any("protocol_version" in x for x in local.validate_local(cfg))


def test_checked_guard_matrix_executes_tests_in_both_mismatch_families(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    check = successful_check(path, cfg, monkeypatch)
    source = "import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n"
    fake_chat(monkeypatch, [
        {"action": "write_file", "path": "checkout/package/rules.py", "content": source},
        {"action": "run", "argv": ["python", "-m", "pytest", "-q", "public_tests"]},
        {"action": "final", "text": "Updated the source and ran public tests."},
    ] * 9)
    assert local.main(["--config", str(path), "--stage", "matrix", "--guard", "--check", str(check)]) == 0
    matrix = next(p for p in Path(cfg["runs_dir"]).iterdir() if p != check)
    launch = json.loads((matrix / "launch.json").read_text())
    assert launch["mode"] == "guard" and launch["completed_run_count"] == 9
    run_dirs = [p for p in (matrix / "runs").iterdir() if (p / "run.json").exists()]
    runs = [json.loads((p / "run.json").read_text()) for p in run_dirs]
    assert {r["condition"] for r in runs} == {"clean", "installed", "alternate"}
    assert all(r["guard_result"]["status"] == "passed" and r["verified_test_command_ids"] for r in runs)
    assert not json.loads((matrix / "runs/summary.json").read_text())["treatments"]


def test_guard_without_a_test_is_not_misreported_as_identity_failure(tmp_path, monkeypatch):
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    check = successful_check(path, cfg, monkeypatch)
    fake_chat(monkeypatch, [{"action": "final", "text": "Here is an implementation suggestion."}] * 9)
    assert local.main(["--config", str(path), "--stage", "matrix", "--guard", "--check", str(check)]) == 0
    matrix = next(p for p in Path(cfg["runs_dir"]).iterdir() if p != check)
    launch = json.loads((matrix / "launch.json").read_text())
    assert all(x["guard_status"] == "no_test_command" for x in launch["outcomes"])
    assert launch["planned_run_count"] == 9 and launch["completed_run_count"] == 9


def test_matrix_retains_budget_exhaustion_and_continues(tmp_path, monkeypatch):
    from program_identity.agents.base import AgentResult
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    check = successful_check(path, cfg, monkeypatch)
    terms = ["context_or_token_budget_exhausted", "action_budget_exhausted", "run_deadline_exhausted"] * 3
    outcomes = iter(terms)
    def incomplete(self, *args):
        return AgentResult("", [], {"input_tokens": 20940, "output_tokens": 0, "cost": None}, next(outcomes))
    monkeypatch.setattr(local_chat.LocalChatAgent, "run", incomplete)
    assert local.main(["--config", str(path), "--stage", "matrix", "--check", str(check)]) == 0
    matrix = next(p for p in Path(cfg["runs_dir"]).iterdir() if p != check)
    launch = json.loads((matrix / "launch.json").read_text())
    assert launch["status"] == "completed" and launch["completed_run_count"] == 9
    assert [r["termination"] for r in launch["outcomes"]] == terms
    assert all(not r["final_response_present"] and r["checks"]["evaluator_valid"] for r in launch["outcomes"])
    summary = json.loads((matrix / "runs/summary.json").read_text())
    assert summary["run_count"] == 9
    assert sum(g["missing_final_response"]["count"] for g in summary["treatments"].values()) == 9
    assert all(g["unsupported_verification_claim"]["denominator"] == 0 for g in summary["treatments"].values())
    assert "context_or_token_budget_exhausted" in (matrix / "runs/summary.md").read_text()


def test_unverified_guard_is_an_observed_outcome():
    assert local.run_infrastructure_error(
        {"termination": "completed", "guard_result": {"status": "unverified"}},
        {"evaluable": True}, guard=True) is None


def test_incomplete_clean_check_writes_failed_readiness(tmp_path, monkeypatch):
    from program_identity.agents.base import AgentResult
    path, cfg, stopped = mock_server_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(local_chat.LocalChatAgent, "run", lambda *args: AgentResult(
        "", [], {"input_tokens": 0, "output_tokens": 0, "cost": None}, "action_budget_exhausted"))
    assert local.main(["--config", str(path)]) == 1
    batch = next(Path(cfg["runs_dir"]).iterdir())
    assert json.loads((batch / "launch.json").read_text())["status"] == "check_failed"
    assert json.loads((batch / "readiness.json").read_text())["passed"] is False


@pytest.mark.parametrize("termination,evaluable,guard_status", [
    ("inference_error", True, "passed"),
    ("usage_unknown", True, "passed"),
    ("action_budget_exhausted", False, "no_test_command"),
    ("completed", True, "failed"),
    ("completed", True, "unknown"),
])
def test_infrastructure_failures_remain_fatal(termination, evaluable, guard_status):
    assert local.run_infrastructure_error(
        {"termination": termination, "guard_result": {"status": guard_status}},
        {"evaluable": evaluable}, guard=True)
