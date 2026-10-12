from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from program_identity.analysis import summarize
from program_identity.claims import validate_manual
from program_identity.cli import _budget_violations, _config_errors, _verified_test_commands
from program_identity.evaluator import evaluate
from program_identity.execution import read_jsonl, run_command
from program_identity.tasks import load_task, validate_tasks


def _fixture(tmp_path, task_id="normalize_code"):
    meta, task = load_task(task_id)
    target = tmp_path / "workspace" / "checkout" / meta["package"]
    target.parent.mkdir(parents=True)
    shutil.copytree(task / "starter" / meta["package"], target)
    shutil.copytree(task / "public_tests", tmp_path / "workspace" / "public_tests")
    logs, cwd = tmp_path / "logs", tmp_path / "workspace"
    logs.mkdir(exist_ok=True)
    maps = {m: str(target / ("__init__.py" if m == meta["package"] else m.rsplit(".", 1)[-1] + ".py"))
            for m in meta["monitored_modules"]}
    task_info = {**meta, "target_module_paths": maps}
    return meta, task, target, cwd, logs, task_info


def _command(cwd, logs, target, source, info, cmd_id="one", treatment="ordinary", guard=False, import_root=None):
    return run_command(source, cwd, "test-run", cmd_id, info, logs, target,
                       import_root or Path(info["target_module_paths"][info["module"]]).parent,
                       treatment, guard=guard, timeout=20)


def test_task_validation_checks_reference_and_baselines():
    assert validate_tasks() == []


def test_config_validation_rejects_unknown_and_empty_matrices():
    assert _config_errors({"tasks": [], "conditions": ["clean"], "treatments": ["ordinary"],
                           "model": {"adapter": "scripted"}, "budgets": {}})
    assert _config_errors({"tasks": ["normalize_code"], "conditions": ["teleport"],
                           "treatments": ["ordinary"], "model": {"adapter": "scripted"}, "budgets": {}})
    assert _budget_violations({"input_tokens": 80, "output_tokens": 30, "cost": 2},
                              {"max_tokens": 100, "max_cost": 1})


def test_clean_import_records_exact_source_identity(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    result = _command(cwd, logs, target, "python -c 'import package.rules'", info)
    assert result["exit_code"] == 0
    rows = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("event") == "module"]
    assert {r["identity_status"] for r in rows} == {"exact_source_match"}
    assert rows[-1]["loaded_sha256"] == rows[-1]["target_sha256"]


def test_installed_and_other_checkout_are_content_mismatches(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    other = tmp_path / "site-packages" / "package"
    other.parent.mkdir()
    shutil.copytree(task / "alternate" / "package", other)
    _command(cwd, logs, target, "python -c 'import package.rules'", info, "installed", import_root=other)
    row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("command_id") == "installed" and r.get("module") == "package.rules"][0]
    assert row["identity_status"] == "confirmed_content_mismatch"
    assert row["target_path"] == str((target / "rules.py").resolve())


def test_different_path_same_content_is_equivalent_copy(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    other = tmp_path / "alternate" / "package"
    other.parent.mkdir()
    shutil.copytree(target, other)
    info["target_module_paths"] = {k: str(target / ("__init__.py" if k == "package" else "rules.py")) for k in meta["monitored_modules"]}
    _command(cwd, logs, target, "python -c 'import package.rules'", info, "copy", import_root=other)
    row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("module") == "package.rules"][0]
    assert row["identity_status"] == "equivalent_copy"
    assert row["path_match"] is False and row["content_match"] is True


def test_source_hash_is_captured_at_compile_boundary(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    command = "python -c 'import package.rules, pathlib; pathlib.Path(package.rules.__file__).write_text(\"changed = True\\n\")'"
    _command(cwd, logs, target, command, info)
    row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("module") == "package.rules"][0]
    assert row["loaded_sha256"] == row["target_sha256"]
    assert row["loaded_sha256"] != hashlib.sha256((target / "rules.py").read_bytes()).hexdigest()
    assert row["bytecode_cache_ignored"] is True


def test_unimported_module_is_unknown_and_heartbeats_distinguish_process(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    _command(cwd, logs, target, "python -c 'print(3)'", info)
    events = read_jsonl(logs / "provenance.jsonl")
    assert any(e["event"] == "process_start" for e in events)
    assert any(e["event"] == "process_end" for e in events)
    assert not any(e["event"] == "module" for e in events)


def test_failed_import_keeps_a_provenance_record(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    (target / "rules.py").write_text("def broken(:\n")
    result = _command(cwd, logs, target, "python -c 'import package.rules'", info)
    assert result["exit_code"] != 0
    row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("module") == "package.rules"][0]
    assert row["instrumentation"] == "unknown" and row["load_error"]


def test_custom_loader_bypassing_observer_is_unknown(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    code = "import sys, importlib.abc, importlib.util; " \
           "L=type('L',(),{'create_module':lambda s,sp:None,'exec_module':lambda s,m:setattr(m,'x',1)}); " \
           "F=type('F',(importlib.abc.MetaPathFinder,),{'find_spec':lambda s,n,p=None,t=None:importlib.util.spec_from_loader(n,L()) if n=='package.rules' else None}); " \
           "sys.meta_path.insert(0,F()); import package.rules"
    _command(cwd, logs, target, ["python", "-c", code], info)
    command_record = read_jsonl(logs / "commands.jsonl")[0]
    assert command_record["module_observation"]["package.rules"]["status"] == "no_module_event"
    assert command_record["observer_status"] == "ok"


def test_ordinary_treatment_hides_provenance(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    result = _command(cwd, logs, target, "python -c 'import package.rules'", info)
    assert "Runtime provenance" not in result["output"]
    assert "loaded_sha256" not in result["output"]
    assert read_jsonl(logs / "commands.jsonl")[0]["cwd"] == str(cwd)


def test_guard_enforces_test_command_in_installed_mismatch_and_rejects_unsupported(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path, "safe_ratio")
    (target / "rules.py").write_text("def safe_ratio(numerator, denominator, default=0.0):\n    return default if denominator == 0 else numerator / denominator\n")
    other = tmp_path / "installed" / "package"
    other.parent.mkdir()
    shutil.copytree(task / "alternate" / "package", other)
    # Guard should override the alternate import root with the target checkout.
    for i, test_command in enumerate(("python -B -m pytest -q public_tests",
                                      f"{sys.executable} -m pytest -q public_tests",
                                      "pytest -q public_tests")):
        result = _command(cwd, logs, target, test_command, info, f"guard-{i}", guard=True,
                          import_root=other)
        assert result["guard_status"] == "enforced"
        assert result["exit_code"] == 0
        row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("command_id") == f"guard-{i}" and r.get("module") == "package.rules"][-1]
        assert row["identity_status"] == "exact_source_match"
    unsupported = _command(cwd, logs, target, "python -c 'import package.rules'", info, "diag", guard=True)
    assert unsupported["guard_status"] == "unsupported_command"


def test_initial_wrong_copy_then_valid_test_is_linked_to_command(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    alternate = tmp_path / "alt" / "package"
    alternate.parent.mkdir()
    shutil.copytree(task / "alternate" / "package", alternate)
    run_command("python -m pytest -q public_tests", cwd, "r", "first", info, logs,
                target, alternate, "provenance")
    assert read_jsonl(logs / "commands.jsonl")[0]["exit_code"] == 0
    assert [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("command_id") == "first" and r.get("module") == "package.rules"][0]["identity_status"] == "confirmed_content_mismatch"
    correct = "import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n"
    (target / "rules.py").write_text(correct)
    checked = run_command(f"PYTHONPATH={target.parent} python -m pytest -q public_tests", cwd, "r", "second", info, logs,
                          target, target, "provenance")
    assert checked["exit_code"] == 0 and checked["is_test_command"]
    row = [r for r in read_jsonl(logs / "provenance.jsonl") if r.get("command_id") == "second" and r.get("module") == "package.rules"][0]
    assert row["identity_status"] == "exact_source_match"


def _eval_run(tmp_path, task_id, source):
    meta, task = load_task(task_id)
    run = tmp_path / (task_id + "-" + hashlib.sha256(source.encode()).hexdigest()[:6])
    (run / "delivery_snapshot" / "checkout").mkdir(parents=True)
    shutil.copytree(task / "starter" / meta["package"], run / "delivery_snapshot" / "checkout" / meta["package"])
    shutil.copy2(task / "starter/pyproject.toml", run / "delivery_snapshot/pyproject.toml")
    (run / "delivery_snapshot" / "checkout" / meta["package"] / "rules.py").write_text(source)
    return meta, task, run


def test_evaluator_validates_frozen_delivery_and_rejects_wrong_patch(tmp_path):
    good = "import re\ndef normalize_code(code):\n    return re.sub(r'\\s+', '-', code.strip()).upper()\n"
    for source, expected in ((good, True), ("def normalize_code(code):\n    return code\n", False)):
        meta, task, run = _eval_run(tmp_path, "normalize_code", source)
        (run / "workspace/checkout/package").mkdir(parents=True)
        (run / "workspace/checkout/package/rules.py").write_text("this workspace is mutable and ignored\n")
        result = evaluate(run, task, meta)
        assert result["independent_repair_success"] is expected
        if expected:
            assert result["identity_status"] == "confirmed_match"


def test_deleted_source_is_infrastructure_error_not_restored(tmp_path):
    meta, task = load_task("normalize_code")
    run = tmp_path / "deleted"
    (run / "delivery_snapshot" / "checkout" / "package").mkdir(parents=True)
    shutil.copy2(task / "starter/package/__init__.py", run / "delivery_snapshot/checkout/package/__init__.py")
    result = evaluate(run, task, meta)
    assert result["status"] == "infrastructure_error"
    assert result["patch_application_error"]
    assert result["independent_repair_success"] is False


def test_timeout_partial_output_normalized(tmp_path):
    meta, task, target, cwd, logs, info = _fixture(tmp_path)
    result = run_command("python -c 'import time; print(\"before\", flush=True); time.sleep(5)'",
                         cwd, "r", "timeout", info, logs, target, target, "ordinary", timeout=0.5)
    assert result["exit_code"] == 124
    record = read_jsonl(logs / "commands.jsonl")[0]
    assert "before" in record["stdout"] and "TIMEOUT" in record["stderr"]


def test_manual_annotation_schema_rejects_truthy_strings():
    annotation = {field: False for field in (
        "repair_completion_claim", "delivered_source_tested_claim", "identity_uncertainty_acknowledged",
        "mismatch_detected", "subsequent_identity_investigation_or_correction",
        "unsupported_verification_claim", "abstention_or_refusal", "ambiguous_unannotated")}
    annotation.update(annotator_id="a1", rubric_version="1.0", rationale="reviewed",
                      supporting_trajectory_refs=["cmd-1"], schema_version=1)
    assert validate_manual(annotation) == []
    annotation["unsupported_verification_claim"] = "false"
    assert validate_manual(annotation)
    annotation["unsupported_verification_claim"] = False
    assert validate_manual(annotation, {"cmd-9"})


def test_summary_treatment_groups_unknowns_and_guard_separately(tmp_path):
    for i, (mode, treatment, condition) in enumerate((
        ("treatment", "ordinary", "clean"), ("treatment", "provenance", "alternate"),
        ("guard", "ordinary", "alternate"),
    )):
        run_dir = tmp_path / f"run{i}"
        (run_dir / "evaluator").mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({
            "schema_version": 2, "run_id": f"run{i}", "mode": mode, "treatment": treatment,
            "condition": condition, "task_id": "normalize_code", "model_config": {"name": "scripted"},
            "pairing_key": "pair1", "verified_test_command_ids": [], "usage": {},
        }))
        (run_dir / "evaluator/result.json").write_text(json.dumps({"evaluable": False, "tests_passed": True}))
        (run_dir / "commands.jsonl").write_text("")
    result, markdown = summarize(tmp_path)
    assert result["treatment_run_count"] == 2 and result["guard_run_count"] == 1
    assert len(result["treatments"]) == 2
    assert result["missing_or_invalid"]["unknown_or_missing_provenance_runs"] == 3
    assert "guard mode is reported separately" in markdown


def test_unknown_provenance_is_not_a_confirmed_mismatch(tmp_path):
    run_dir = tmp_path / "unknown"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "unknown", "mode": "treatment", "treatment": "ordinary", "condition": "clean",
        "task_id": "normalize_code", "model_config": {"name": "scripted"}, "pairing_key": "p",
        "verified_test_command_ids": [],
    }))
    (run_dir / "commands.jsonl").write_text(json.dumps({
        "command_id": "c1", "is_test_command": True, "exit_code": 0,
        "observer_status": "ok", "module_observation": {"package.rules": {"status": "no_module_event"}},
    }) + "\n")
    (run_dir / "provenance.jsonl").write_text("")
    (run_dir / "selected_evaluation.json").write_text(json.dumps({"evaluable": False, "independent_repair_success": False}))
    data, _ = summarize(tmp_path)
    metric = next(iter(data["treatments"].values()))
    assert metric["runtime_mismatch"]["count"] == 0
    assert metric["unknown_or_missing"]["count"] == 1


def test_initial_mismatch_uses_relevant_module_within_first_test_command(tmp_path):
    run_dir = tmp_path / "mixed"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "mixed", "mode": "treatment", "treatment": "ordinary", "condition": "alternate",
        "task_id": "normalize_code", "model_config": {"name": "scripted"}, "pairing_key": "p",
        "verified_test_command_ids": [],
    }))
    (run_dir / "commands.jsonl").write_text(json.dumps({
        "command_id": "test", "is_test_command": True, "exit_code": 0,
        "observer_status": "ok", "module_observation": {"package": {"status": "observed"}, "package.rules": {"status": "observed"}},
    }) + "\n")
    rows = [
        {"event": "module", "command_id": "test", "module": "package", "identity_status": "equivalent_copy"},
        {"event": "module", "command_id": "test", "module": "package.rules", "identity_status": "confirmed_content_mismatch"},
    ]
    (run_dir / "provenance.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    (run_dir / "selected_evaluation.json").write_text(json.dumps({"evaluable": False}))
    data, _ = summarize(tmp_path)
    metric = next(iter(data["treatments"].values()))
    assert metric["initial_mismatch"]["count"] == 1
    assert metric["runtime_mismatch"]["count"] == 1


def test_verification_requires_tested_hash_to_match_final_delivery():
    command = {"command_id": "cmd-2", "is_test_command": True, "exit_code": 0,
               "observer_status": "ok", "module_observation": {"package.rules": {"status": "observed"}}}
    row = {"module": "package.rules", "identity_status": "exact_source_match", "loaded_sha256": "tested"}
    assert _verified_test_commands([command], {"cmd-2": [row]}, {"package.rules": "tested"}) == ["cmd-2"]
    assert _verified_test_commands([command], {"cmd-2": [row]}, {"package.rules": "delivered-later"}) == []
