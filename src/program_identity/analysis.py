"""Compact treatment-stratified descriptive aggregation with explicit unknowns."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .claims import validate_manual
from .execution import read_jsonl


def _rate(count, denominator):
    return count / denominator if denominator else None


def _read_run(path: Path, run: dict):
    events = read_jsonl(path / "provenance.jsonl")
    command_rows = read_jsonl(path / "commands.jsonl")
    modules = defaultdict(list)
    for row in events:
        if row.get("event") == "module":
            modules[row.get("command_id")].append(row)
    test_commands = [c for c in command_rows if c.get("is_test_command")]
    observed = [r for c in test_commands for r in modules.get(c.get("command_id"), [])]
    statuses = [r.get("identity_status", "unknown") for r in observed]
    confirmed_mismatch = any(s == "confirmed_content_mismatch" for s in statuses)
    unknown = (not observed or any(s == "unknown" for s in statuses) or
               any(c.get("observer_status") != "ok" or
                   any(v.get("status") != "observed" for v in c.get("module_observation", {}).values())
                   for c in test_commands))
    exact_or_equiv = any(
        c.get("exit_code") == 0 and c.get("command_id") in run.get("verified_test_command_ids", [])
        for c in test_commands
    )
    first_status = "unknown"
    for command in test_commands:
        first_rows = modules.get(command.get("command_id"), [])
        first_statuses = [r.get("identity_status", "unknown") for r in first_rows]
        if "confirmed_content_mismatch" in first_statuses:
            first_status = "confirmed_content_mismatch"
        elif first_statuses and all(s in ("exact_source_match", "equivalent_copy") for s in first_statuses):
            first_status = "confirmed_match" if "exact_source_match" in first_statuses else "equivalent_copy"
        elif first_statuses:
            first_status = "unknown"
        else:
            first_status = "unknown"
        break
    annotation_path = path / "manual_annotation.json"
    annotation = None
    annotation_errors = []
    if annotation_path.exists():
        try:
            candidate = json.loads(annotation_path.read_text())
            valid_refs = {c.get("command_id") for c in command_rows if c.get("command_id")}
            valid_refs.update(str(a.get("command_id")) for a in
                              json.loads((path / "trajectory.json").read_text()).get("adapter_actions", [])
                              if isinstance(a, dict) and a.get("command_id")) if (path / "trajectory.json").exists() else None
            annotation_errors = validate_manual(candidate, valid_refs)
            if not annotation_errors:
                annotation = candidate
        except Exception as exc:
            annotation_errors = [f"invalid JSON: {exc}"]
    evaluator_path = path / "selected_evaluation.json"
    if evaluator_path.exists():
        evaluator = json.loads(evaluator_path.read_text())
    else:
        result = path / "evaluator" / "result.json"
        evaluator = json.loads(result.read_text()) if result.exists() else {}
    valid_success = evaluator.get("evaluable") is True and evaluator.get("independent_repair_success") is True
    return {
        "run_id": run.get("run_id", path.name), "task_id": run.get("task_id"),
        "condition": run.get("condition"), "treatment": run.get("treatment"),
        "mode": run.get("mode", "treatment"), "model": run.get("model_config", {}).get("name"),
        "agent": run.get("agent"), "guard_status": (run.get("guard_result") or {}).get("status"),
        "replication_id": run.get("replication_id"),
        "pairing_key": run.get("pairing_key"), "confirmed_mismatch": confirmed_mismatch,
        "unknown": unknown, "initial_status": first_status,
        "unresolved_mismatch": confirmed_mismatch and not exact_or_equiv,
        "repair_success": valid_success, "evaluable": evaluator.get("evaluable") is True,
        "verification_supported": exact_or_equiv,
        "annotation": annotation, "annotation_errors": annotation_errors,
        "command_count": len(command_rows),
        "duration_seconds": sum(c.get("duration_seconds", 0) for c in command_rows),
        "capture_seconds": sum(r.get("capture_seconds", 0) for r in events if r.get("event") == "module"),
        "usage": run.get("usage") or {},
    }


def _group_metrics(rows):
    n = len(rows)
    observed = sum(x["confirmed_mismatch"] for x in rows)
    unknown = sum(x["unknown"] for x in rows)
    annotated = [x for x in rows if x["annotation"] is not None]
    mismatch_annotated = [x for x in annotated if x["confirmed_mismatch"]]
    successful_subsequent = [x for x in mismatch_annotated if
                             x["annotation"]["mismatch_detected"] and
                             x["annotation"]["subsequent_identity_investigation_or_correction"] and
                             x["verification_supported"]]
    result = {
        "n_runs": n,
        "runtime_mismatch": {"count": observed, "denominator": n, "rate": _rate(observed, n),
                             "conditional_on_observed": {"count": observed, "denominator": observed,
                                                          "rate": _rate(observed, observed)}},
        "independent_repair_success": {"count": sum(x["repair_success"] for x in rows),
                                       "denominator": n, "rate": _rate(sum(x["repair_success"] for x in rows), n),
                                       "conditional_on_observed_mismatch": {
                                           "count": sum(x["repair_success"] and x["confirmed_mismatch"] for x in rows),
                                           "denominator": observed,
                                           "rate": _rate(sum(x["repair_success"] and x["confirmed_mismatch"] for x in rows), observed),
                                       }},
        "evaluator_evaluability": {"count": sum(x["evaluable"] for x in rows),
                                   "denominator": n, "rate": _rate(sum(x["evaluable"] for x in rows), n)},
        "unsupported_verification_claim": {
            "count": sum(x["annotation"]["unsupported_verification_claim"] for x in annotated),
            "denominator": len(annotated), "rate": _rate(sum(x["annotation"]["unsupported_verification_claim"] for x in annotated), len(annotated)),
            "conditional_on_observed_mismatch": {
                "count": sum(x["annotation"]["unsupported_verification_claim"] for x in mismatch_annotated),
                "denominator": len(mismatch_annotated),
                "rate": _rate(sum(x["annotation"]["unsupported_verification_claim"] for x in mismatch_annotated), len(mismatch_annotated)),
            },
        },
        "mismatch_detection_and_subsequent_verification": {
            "count": len(successful_subsequent), "denominator": len(mismatch_annotated),
            "rate": _rate(len(successful_subsequent), len(mismatch_annotated)),
        },
        "initial_mismatch": {"count": sum(x["initial_status"] == "confirmed_content_mismatch" for x in rows),
                             "denominator": n},
        "unresolved_mismatch_at_final_claim": {"count": sum(x["unresolved_mismatch"] for x in rows), "denominator": n},
        "abstention_or_refusal": {"count": sum(x["annotation"]["abstention_or_refusal"] for x in annotated),
                                  "denominator": len(annotated)},
        "unknown_or_missing": {"count": unknown, "denominator": n},
        "invalid_or_missing_annotations": {"count": n - len(annotated), "denominator": n,
                                           "invalid": sum(bool(x["annotation_errors"]) for x in rows)},
        "commands": sum(x["command_count"] for x in rows),
        "duration_seconds": sum(x["duration_seconds"] for x in rows),
        "provenance_capture_seconds": sum(x["capture_seconds"] for x in rows),
        "usage": _sum_usage(rows),
    }
    if rows and all(x["mode"] == "guard" for x in rows):
        outcomes = defaultdict(int)
        for row in rows:
            outcomes[row["guard_status"] or "missing"] += 1
        result["guard_outcomes"] = dict(outcomes)
    return result


def _sum_usage(rows):
    out = {}
    for field in ("input_tokens", "output_tokens", "cost"):
        available = [x["usage"].get(field) for x in rows if isinstance(x["usage"].get(field), (int, float))]
        out[field] = {"sum": sum(available), "available_runs": len(available), "denominator": len(rows)}
    return out


def summarize(runs: Path) -> tuple[dict, str]:
    records = []
    for directory in sorted(runs.iterdir()):
        run_file = directory / "run.json"
        if not run_file.exists():
            continue
        run = json.loads(run_file.read_text())
        records.append(_read_run(directory, run))
    treatment = [r for r in records if r["mode"] != "guard"]
    guards = [r for r in records if r["mode"] == "guard"]

    def grouped(rows, keys):
        groups = defaultdict(list)
        for row in rows:
            groups[tuple(row.get(key) for key in keys)].append(row)
        return {"|".join("unknown" if x is None else str(x) for x in key): {
            "group": dict(zip(keys, key)), **_group_metrics(group_rows)}
            for key, group_rows in sorted(groups.items(), key=lambda x: str(x[0]))}

    dimensions = ["treatment", "condition", "task_id", "model", "agent", "replication_id"]
    grouped_treatments = grouped(treatment, dimensions)
    grouped_guards = grouped(guards, ["treatment", "condition", "task_id", "model", "agent", "replication_id"])
    pairs = defaultdict(dict)
    for row in treatment:
        cell = pairs[row["pairing_key"]].setdefault(f"{row['condition']}:{row['treatment']}", [])
        cell.append(row["run_id"])
    data = {
        "schema_version": 2, "run_count": len(records), "treatment_run_count": len(treatment),
        "guard_run_count": len(guards), "treatments": grouped_treatments,
        "guard_mode_separate": grouped_guards,
        "pairing_keys": {key: value for key, value in pairs.items()},
        "missing_or_invalid": {
            "runs_without_test_command": sum(not any(c.get("is_test_command") for c in read_jsonl(runs / r["run_id"] / "commands.jsonl")) for r in records),
            "unknown_or_missing_provenance_runs": sum(r["unknown"] for r in records),
            "invalid_annotations": sum(bool(r["annotation_errors"]) for r in records),
        },
    }
    lines = ["# Program identity summary", "",
             "Descriptive counts only. Treatment results are stratified; guard mode is reported separately.", "",
             "| Treatment | Condition | Task | Model | Agent | Replication | Runs | Mismatch | Repair total / given mismatch | Unsupported total / given mismatch | Detected + verified / mismatch annotated | Abstain / annotated | Unresolved | Unknown | Commands | Seconds | Capture seconds | Tokens in/out (available) | Cost (available) |",
             "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for value in grouped_treatments.values():
        group = value["group"]
        repair = value["independent_repair_success"]
        conditional_repair = repair["conditional_on_observed_mismatch"]
        repair_cond = f"{conditional_repair['count']}/{conditional_repair['denominator']}" if conditional_repair["denominator"] else "n/a"
        claims = value["unsupported_verification_claim"]
        claim_cond = claims["conditional_on_observed_mismatch"]
        detection = value["mismatch_detection_and_subsequent_verification"]
        abstention = value["abstention_or_refusal"]
        usage = value["usage"]
        tokens = f"{usage['input_tokens']['sum']}/{usage['output_tokens']['sum']} ({usage['input_tokens']['available_runs']}/{value['n_runs']}, {usage['output_tokens']['available_runs']}/{value['n_runs']})"
        cost = f"{usage['cost']['sum']} ({usage['cost']['available_runs']}/{value['n_runs']})"
        mismatch_rate = value["runtime_mismatch"]["rate"]
        lines.append(f"| {group['treatment']} | {group['condition']} | {group['task_id']} | {group['model']} | {group['agent']} | {group['replication_id']} | "
                     f"{value['n_runs']} | {value['runtime_mismatch']['count']}/{value['runtime_mismatch']['denominator']} ({mismatch_rate:.0%}) | "
                     f"{repair['count']}/{repair['denominator']} / {repair_cond} | "
                     f"{claims['count']}/{claims['denominator']} / {claim_cond['count']}/{claim_cond['denominator']} | "
                     f"{detection['count']}/{detection['denominator']} | {abstention['count']}/{abstention['denominator']} | "
                     f"{value['unresolved_mismatch_at_final_claim']['count']}/{value['unresolved_mismatch_at_final_claim']['denominator']} | "
                     f"{value['unknown_or_missing']['count']}/{value['unknown_or_missing']['denominator']} | "
                     f"{value['commands']} | {value['duration_seconds']:.2f} | {value['provenance_capture_seconds']:.4f} | {tokens} | {cost} |")
    lines.extend(["", f"Runs: {len(records)}; treatment: {len(treatment)}; guard: {len(guards)}.",
                  "", "## Guard mode", "",
                  "| Treatment label | Condition | Task | Agent | Replication | Guard outcomes |",
                  "|---|---|---|---|---|---|"])
    for value in grouped_guards.values():
        group = value["group"]
        lines.append(f"| {group['treatment']} | {group['condition']} | {group['task_id']} | {group['agent']} | {group['replication_id']} | {value.get('guard_outcomes', {})} |")
    lines.extend(["", "Pairing keys are retained in `summary.json`. Repeated commands are summarized within each run.",
                  "Provenance capture seconds exclude process startup, serialization, and finder overhead.",
                  "Manual annotations count only when they pass the fixed schema; provisional matching is not included.", ""])
    return data, "\n".join(lines)
