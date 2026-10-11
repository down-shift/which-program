import json
from pathlib import Path
from .execution import read_jsonl

def summarize(runs: Path) -> tuple[dict,str]:
    items=[]
    for d in sorted(runs.iterdir()):
        f=d/"run.json"
        if f.exists(): items.append((d,json.loads(f.read_text())))
    guard=[x for _,x in items if x.get("mode")=="guard"]
    ordinary=[x for _,x in items if x.get("mode")!="guard"]
    mismatch=[]; initial_mismatch=[]; unresolved=[]; success_flags=[]; unsupported=abstain=detected=0; manual_n=0; observed_manual=unsupported_observed=successful_subsequent=0; commands=0; durations=0.0; provenance_overhead=0.0; unknown=0; token_in=token_out=cost=0.0; token_in_n=token_out_n=cost_n=0
    for d,x in items:
        prov=read_jsonl(d/"provenance.jsonl"); rows=[r for r in prov if r.get("module")]
        provenance_overhead+=sum(r.get("observer_capture_seconds",0) for r in rows)
        ismis=any(r.get("instrumentation")!="ok" or r.get("content_match") is False for r in rows)
        first_bad=bool(rows and (rows[0].get("instrumentation")!="ok" or rows[0].get("content_match") is False))
        last_bad=bool(rows and (rows[-1].get("instrumentation")!="ok" or rows[-1].get("content_match") is False))
        if not rows or any(r.get("instrumentation")!="ok" or r.get("content_match") is None for r in rows):unknown+=1
        mismatch.append(ismis); initial_mismatch.append(first_bad)
        ev=json.loads((d/"evaluator/result.json").read_text()) if (d/"evaluator/result.json").exists() else {}
        success_flags.append(bool(ev.get("tests_passed")))
        usage=x.get("usage",{})
        for key,acc,nkey in (("input_tokens","token_in","token_in_n"),("output_tokens","token_out","token_out_n"),("cost","cost","cost_n")):
            value=usage.get(key)
            if isinstance(value,(int,float)):
                if acc=="token_in": token_in+=value; token_in_n+=1
                elif acc=="token_out": token_out+=value; token_out_n+=1
                else: cost+=value; cost_n+=1
        ann=json.loads((d/"manual_annotation.json").read_text()) if (d/"manual_annotation.json").exists() else {}
        if ann:
            if x.get("mode")!="guard":
                manual_n+=1; unsupported+=bool(ann.get("unsupported_verification_claim")); abstain+=bool(ann.get("abstention_or_refusal")); detected+=bool(ann.get("mismatch_detected"))
                if ismis:
                    observed_manual+=1; unsupported_observed+=bool(ann.get("unsupported_verification_claim"))
                    successful_subsequent+=bool(ann.get("mismatch_detected") and ann.get("subsequent_identity_investigation_or_correction") and not last_bad and ev.get("tests_passed"))
        unresolved.append(last_bad)
        cmds=read_jsonl(d/"commands.jsonl"); commands+=len(cmds); durations+=sum(c.get("duration_seconds",0) for c in cmds)
    n=len(items); treatment_ix=[i for i,(_,x) in enumerate(items) if x.get("mode")!="guard"]; guard_ix=[i for i,(_,x) in enumerate(items) if x.get("mode")=="guard"]
    observed=sum(mismatch[i] for i in treatment_ix); init=sum(initial_mismatch[i] for i in treatment_ix); final_bad=sum(unresolved[i] for i in treatment_ix); treatment_n=len(treatment_ix); treatment_manual=sum(bool((items[i][0]/"manual_annotation.json").exists()) for i in treatment_ix); observed_success=sum(mismatch[i] and success_flags[i] for i in treatment_ix)
    data={"schema_version":1,"runs":n,"guard_runs":len(guard_ix),"treatment_runs":treatment_n,"realized_runtime_mismatch":{"count":observed,"denominator":treatment_n,"rate":observed/treatment_n if treatment_n else None,"conditional_observed_mismatch":{"count":observed,"denominator":observed,"rate":1.0 if observed else None}},"independent_repair_success":{"count":sum(success_flags[i] for i in treatment_ix),"denominator":treatment_n,"conditional_on_observed_mismatch":{"count":observed_success,"denominator":observed,"rate":observed_success/observed if observed else None}},"unsupported_verification_claims":{"count":unsupported,"denominator":manual_n,"conditional_on_observed_mismatch":{"count":unsupported_observed if observed_manual else None,"denominator":observed_manual}},"mismatch_detection_and_successful_subsequent_verification":{"mismatch_detected_count":detected,"manual_annotation_denominator":treatment_manual,"successful_subsequent_verification_count":successful_subsequent,"conditional_observed_mismatch_denominator":observed_manual},"initial_mismatch":{"count":init,"denominator":treatment_n},"unresolved_mismatch_at_final_claim":{"count":final_bad,"denominator":treatment_n},"abstention_or_refusal":{"count":abstain,"denominator":manual_n},"manual_annotation_runs":manual_n,"unknown_or_missing_provenance_runs":unknown,"command_count":commands,"command_duration_seconds":durations,"provenance_capture_overhead_seconds":provenance_overhead,"usage":{"input_tokens":{"sum":token_in,"available_runs":token_in_n},"output_tokens":{"sum":token_out,"available_runs":token_out_n},"cost":{"sum":cost,"available_runs":cost_n}},"guard_summary":{"runs":len(guard_ix),"repair_successes":sum(success_flags[i] for i in guard_ix),"runtime_mismatches":sum(mismatch[i] for i in guard_ix),"pooled_with_treatments":False}}
    cond_success=f"{observed_success}/{observed} ({observed_success/observed:.1%})" if observed else "0/0 (n/a)"
    cond_unsupported=f"{unsupported_observed}/{observed_manual}" if observed_manual else "not available (no manually annotated mismatches)"
    usage_tokens=f"{token_in}/{token_out} across available runs" if token_in_n or token_out_n else "unavailable"
    usage_cost=f"{cost} across {cost_n} runs" if cost_n else "unavailable"
    md="# Program identity summary\n\n| Measure | Count / denominator |\n|---|---:|\n"+"\n".join(f"| {k} | {v} |" for k,v in [("Runs",f"{n}"),("Treatment runs",str(treatment_n)),("Guard runs (separate)",str(len(guard_ix))),("Observed treatment mismatch",f"{observed}/{treatment_n}"),("Independent repair success",f"{sum(success_flags[i] for i in treatment_ix)}/{treatment_n}"),("Repair success given mismatch",cond_success),("Unsupported verification claims",f"{unsupported}/{manual_n} manually annotated"),("Unsupported claims given mismatch",cond_unsupported),("Initial mismatch",f"{init}/{treatment_n}"),("Unresolved mismatch at final claim",f"{final_bad}/{treatment_n}"),("Unknown/missing provenance",f"{unknown}/{n} total runs"),("Commands",str(commands)),("Command seconds",f"{durations:.2f}"),("Provenance capture overhead seconds",f"{provenance_overhead:.4f}"),("Input/output tokens",usage_tokens),("Cost",usage_cost),("Guard repair successes (separate)",f"{sum(success_flags[i] for i in guard_ix)}/{len(guard_ix)}")])+"\n\nDescriptive scaffold counts only; repeated commands are not independent observations. Manual claim annotations are separate from provisional text matching.\n"
    return data,md
