# Planner handoff: Which Program Did You Test?

As of 2026-10-18; reflects saved local artifacts, not an independently refreshed
remote-machine state. GPU availability was last reported busy. This handoff
proposes next work; it does not claim that new variants or remote runs have begun.

## Objective and current assessment

Study whether coding agents mistake passing tests against another source copy
for evidence about the code they delivered. Measure independent repair correctness,
runtime identity/final-source verification, and claim support separately.

The mechanism is relevant and reproducible in the pilot. Novelty is not
established: wrong-copy imports, misleading test success, and artifact-bound
verification all have prior work. The candidate contribution is the controlled
behavioral/claim study at the edited-source versus imported-source boundary.
See [research positioning](../docs/research_positioning.md) for primary sources,
overlap, and limits. Do not market this as discovery of deliberate cheating or
as proof that provenance or the guard improves agent reasoning.

## Evidence inventory

| Dataset | Included observations | Repairs | Final source verified | Important boundary |
|---|---:|---:|---:|---|
| Original unguarded pilot | 27 | 24/27 | 9/27 | normalize_code, seeds 18–20 |
| Original guard pilot | 27 | 27/27 | 27/27 | Same single task; enforcement result |
| Expanded unguarded pilot | 36 | 26/36 | 9/36 | Four tasks, seed 18 only |
| Expanded guard attempt | Incomplete | No full-matrix estimate | No full-matrix estimate | Ten collected cells precede collection failure at cell 11 |

Integration checks and superseded attempts are excluded. The 90 annotation
candidates combine the first three rows for review convenience; they do not form
a homogeneous 90-task experiment. Expanded normalize_code at seed 18 is a repeat
observation within a later phase, not another independent seed.

Expanded results by task:

| Task | Repair success | Final-source verification |
|---|---:|---:|
| normalize_code | 8/9 | 3/9 |
| safe_ratio | 3/9 | 1/9 |
| clamp_value | 6/9 | 2/9 |
| unique_items | 9/9 | 3/9 |

All 24 installed/alternate expanded runs passed public tests against different
content; none verified the final source. Seventeen nevertheless delivered correct
repairs. Six delivered invalid Python and returned success/pass claims. Nine total
deliveries copied `[Runtime provenance]` and `[]` into source. Four runs exhausted
the cumulative token budget; three also had syntax-invalid source, so these failure
categories must not be added as disjoint counts. Three of the syntax failures
were clean runs where tests exposed the broken source.

Assistant review flags 11 contextual unsupported claims in the original 54 runs
and 16 in the expanded 36. These are not human-coded claim rates. The expanded
review also leaves two test-case correctness assertions ambiguous and four absent
final responses unannotated. No human labels were created by the assistant.

## Artifacts and reproducibility

- [Original audit](pilot-20261016/README.md), with batch manifest, audit JSON,
  per-run CSV, and 54 annotation candidates in the same directory.
- [Expanded audit](expanded-pilot-seed18/README.md), with audit JSON, per-run CSV,
  36 annotation candidates, and the combined 90-row human review queue.
- `scripts/review_pilot.py` and `scripts/review_expanded_pilot.py` reproduce the
  artifact audits without a GPU. The latter independently recompiles the frozen
  source bytes and verifies the masking evidence in the six invalid-code cases.
- `configs/local-qwen-expanded.yaml`: four tasks, seeds supplied by the sequence,
  Qwen/Qwen3-4B BF16 without quantization, commit
  `1cfa9a7208912126459214e8b04321603b3df60c`; 8,192-token context,
  24,000 cumulative input/output tokens, 768 output tokens per request,
  16 model actions, thinking disabled.
- `scripts/run_expanded_pilot.sh` invokes `program_identity.sequence`, which
  discovers completed/incomplete batches and obtains current clean-check receipts.
- `program-identity-local --resume <batch> --check <current-check>` resumes a
  matrix. It retains collected model failures, retries collection failures, and
  archives superseded attempts outside the active summary. Original run files and
  setup IDs remain intact; new runs may have a different harness fingerprint.

Completed expanded treatment batch:
`runs/local-qwen-expanded/20261017T162544Z-4b4fe12a`.

Interrupted expanded guard batch:
`runs/local-qwen-expanded/20261017T162735Z-cda64d03`.

The local dry-run retains the former, retains ten guard cells and retries cell 11
in the latter, then schedules the remaining seed-18 cells and seeds 19–20. Recheck
the plan on the remote host because its artifacts may have advanced.

## Implementation status and constraints

Implemented: frozen delivery evaluation, source-identity observation, full-public-
suite qualification, independent repair assessment, explicit compilation-failure
outcomes, guard handling of known syntax failures, and resumable collection.
The last implementation verification reported 71 passing tests. The latest
expanded artifact audit checked 36 cells, frozen/evaluator hashes, syntax errors,
pre-final command references, and a 90-row worksheet with blank human fields.
The documentation update itself does not change runtime code or experiment settings.

Instrumentation is cooperative, limited to declared ordinary Python source
modules, and not a whole-program or tamper-proof guarantee. The installed-copy
condition shares the host interpreter/test dependencies; do not describe it as a
fully hermetic alternate runtime. Runtime provenance on a failed compilation is
not execution evidence. Evaluator knowledge obtained after the final response
cannot retrospectively support the agent's claim.

## Next work, in dependency order

### P0 — Human annotation and literature review; no GPU

Deliverables:

- Review the six priority-0 invalid-code success claims, then other unsupported
  candidates and ambiguous assertions in `expanded-pilot-seed18/human-review-queue.csv`.
- Document whether each response merely reports a process pass or attributes the
  evidence to the delivered repair. Code the rubric fields independently.
- Have a second human independently code a declared overlap subset, reconcile
  disagreements, and report agreement and exclusions. Hide model/treatment labels
  where feasible; preserve evidence required for judgment.
- Save approved annotations through the CLI and regenerate affected summaries.
  Do not promote assistant suggestions to human labels automatically.
- Read the full closest papers, particularly EA-Graph and ECK, and maintain a
  comparison of research question, identity mechanism, task setting, claim metrics,
  interventions, and evaluation scale. The current abstract-level check does not
  establish scientific priority.

Gate: a stable, documented interpretation of claim support and a specific gap
relative to prior work. If the same empirical question is already adequately
answered, redirect toward replication, stronger realism, or an engineering artifact
rather than claiming first discovery.

### P1 — Specify and implement a separate presentation variant; CPU first

Deliverables:

- Separate file contents from observer metadata in the agent-facing interface,
  especially for file reads with no monitored imports. Keep the underlying
  identity evidence available; preserve the original mixed-output baseline.
- Add an explicit variant setting to configuration validation, setup fingerprints,
  readiness checks, resume compatibility, and sequence selection. Changed prompts
  or action protocols need corresponding identity changes as well. The current
  sequence does not yet know about an unimplemented presentation setting.
- Exercise exact file-content return, metadata access, write-file round trips,
  malformed source, and wrong-copy detection with offline fixtures. Do not silently
  sanitize model-written source; that would mask the behavior under study.
- Predefine a matched baseline/variant comparison, order counterbalancing, and
  token accounting. Call the treatment a presentation/interface change if more
  than serialization format changes. Metadata copying and budget use are outcomes.

Gate: offline checks show correct separation and unchanged observer capabilities,
and the comparison can attribute differences without conflating changed model,
tasks, budgets, or source identity. Whether it improves model behavior is untested.

### P2 — Complete the descriptive baseline when GPU time returns

Preview and resume on the remote Linux/NVIDIA checkout after syncing code:

```sh
bash scripts/run_expanded_pilot.sh --dry-run
bash scripts/run_expanded_pilot.sh
```

Keep the existing baseline presentation unchanged while finishing it. Preserve
model failures and missing finals; do not repeat them until they pass. Archive
and retry actual collection failures only. Identify original and resumed harness
versions in the report. A resumed mixed-version batch is descriptive evidence,
not an automatically homogeneous confirmatory comparison.

Gate: expanded guard outcomes exist for the relevant tasks/conditions and actual
identity uncertainty is resolved or explicitly excluded. A passing guard measures
enforcement; it does not demonstrate autonomous recognition. If the guard merely
exposes metadata-induced syntax failures, report that outcome directly.

### P3 — Targeted replication and realistic environments

After P0/P1, evaluate the baseline and separate presentation variant on a stronger
model and realistic, inspectable package layouts/repositories. Define model and
precision choices deliberately; a quantized larger model introduces configuration
differences that must be reported. Retain sufficient clean controls to distinguish
ordinary repair inability from mismatch-specific susceptibility.

Predeclare sample size, task/seed units, primary comparisons, ordering, missing-
data rules, and uncertainty estimates before a confirmatory collection. Repeated
commands are never the sample unit; report task/seed dependence. Constructed stale
imports estimate susceptibility conditional on that setup, not natural prevalence.

Gate: the edited-vs-executed evidence gap persists beyond the current small model
and presentation, or a bounded failure of replication is documented. Only then
choose a larger confirmatory study or publication claim.

## Decisions requested from the planner

1. Choose the human annotation/reconciliation workflow and assign actual reviewers.
2. Bound the full-text prior-work review and decide the proposed contribution.
3. Specify the presentation variant and its immutable experiment identity before
   implementation; no variant or larger-budget run has been launched.
4. Reserve GPU work for completing the baseline and targeted matched replications;
   choose a stronger model only after checking memory/runtime constraints.

Do not infer intent, general treatment superiority, production failure rates, or
novelty from the present counts. Do not hide missing cells, pool setup versions,
erase superseded attempts, or treat assistant annotations as human observations.
