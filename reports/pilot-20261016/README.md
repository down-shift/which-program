# Pilot audit and expansion

Scope: the nine directories in `batches.txt`, originally supplied in
`files_list.md`. Three integration checks are excluded from experimental counts.
The six matrices contain 54 runs across seeds 18, 19, and 20. Earlier seed-17
batches and aborted batches are excluded. All matrices have the same model,
sampling, budgets, task list, conditions, treatments, and harness source hashes;
seed, mode, and batch-specific identifiers differ.

Reproduce the audit from the repository root with:

```sh
uv run python scripts/review_pilot.py
```

The script recomputes final-source verification from command scope, provenance
records, and frozen delivery hashes, checks every guard result, and checks
collection completeness and evaluator validity. It reads existing artifacts;
it does not rerun historical model requests or historical evaluator tests.
`audit.json` retains batch paths and launch-file hashes; `run-outcomes.csv`
contains one row per experimental run.

## Verified results

| Outcome | Unguarded | Guard |
|---|---:|---:|
| Experimental runs | 27 | 27 |
| Independent repair success | 24/27 | 27/27 |
| Complete public suite verified final source | 9/27 | 27/27 |
| Installed/alternate final source verified | 0/18 | 18/18 |
| Any observed runtime content mismatch in tests | 18/27 | 0/27 |
| Budget exhaustion | 3/27 | 0/27 |

Every clean run repaired and verified its source. All unguarded installed and
alternate runs tested different content; 15/18 nonetheless delivered correct
repairs. Neither displayed provenance nor the added identity instruction yielded
verification of the final source in those cells. This supports a distinction
between repair correctness and the evidence for testing that repair.

All three incomplete runs were unguarded provenance runs. Each read the source,
read public tests, reread the source, then ran the same passing test command five
times without editing. Before call nine, accumulated input/output usage plus the
next prompt exceeded the 24,000-token budget. The next prompt still fit within
8,192 tokens. Thus the direct stop cause was the cumulative token budget, not
an observed context-window rejection. Repeated large provenance outputs increased
prompt sizes. This is a possible interaction between presentation and agent
behavior, not evidence that provenance generally harms performance.

## Claim review

`claim-review-candidates.json` contains 54 explicitly labeled assistant-reviewed
candidates with final-response text, per-field rubric judgments, command
references, and rationales. The responses and supporting commands were inspected
before encoding the explicit run-ID list in the review script; these are not
keyword-generated annotations. There are 51 final responses and three missing
responses. No human `manual_annotation.json` files have been created or changed.
The primary summary's human-annotation denominators remain unknown.

The assistant review identifies 33 test claims in repair context. Eleven lack
matching-source evidence; two of those explicitly say the tests confirm
correctness. For the remaining nine, the unsupported judgment depends on reading
the passing-tests statement as applying to the described repair. A narrow reading
that only claims a test process passed would differ. Repair-completion statements
alone are not classified as verification claims. Missing responses are marked
unannotated, not refusals. No response acknowledges the identity mismatch.

Human review should resolve this attribution consistently, review the independent
fields, and then save approved annotations through `program-identity annotate`.
Assistant candidate counts are not human-coded claim rates. Do not infer an
absence of unsupported claims from the original `0/0` fields.

## Interpretation and limits

The guard successfully forced the intended source to be tested in all observed
cases. This is an engineering validation under controlled source confusion; it
does not show that the model learned to diagnose import identity. Three seeds
are repeated observations of the same small task and model, not 54 independent
tasks. Treatment order was fixed, and provenance conditions consume more prompt
tokens. Do not infer production prevalence, general model capability, or
statistically established treatment effectiveness from these counts.

The adapter sends the configured seed on every model request. Matrix agent IDs
change because seed participates in the setup fingerprint, not because the
adapter or prompt changed. Preserve the run-level artifacts and seed strata.

## Expanded pilot prepared

`configs/local-qwen-expanded.yaml` keeps the original prompt, sampling, context,
output limit, and budgets, and pins the same Qwen checkpoint commit. It includes:

- `normalize_code`: whitespace and case normalization (baseline).
- `safe_ratio`: fractional arithmetic and caller-selected zero fallback (existing task).
- `clamp_value`: both bounds, fractional values, and invalid interval rejection (new).
- `unique_items`: stable deduplication of iterables without sorting or input mutation (new).

Each new task has a failing starter, a plausible different copy that passes public
tests but fails trusted regression tests, public/trusted suites, package metadata,
and an applicable reference patch. The expansion varies repair behavior while
retaining the same clean/installed/alternate import mechanisms. It does not add
new loader types or broaden the instrumentation boundary.

After syncing these files to the Linux NVIDIA host, run:

```sh
bash scripts/run_expanded_pilot.sh
```

This runs fresh four-task integration checks for each seed, followed by separate
36-cell unguarded and guard matrices: 216 experimental runs plus 12 check runs.
The sequence now discovers saved progress automatically: rerunning the command
keeps completed matrices and resumes failed ones. A fresh check is required only
when no compatible current check exists. Use `--dry-run` to inspect the plan.
Historical checks cannot authorize the changed task set. The GPU experiments
have not been run from this Mac workspace. Provenance compression or larger
budgets should be configured as separately labeled follow-up experiments.

## Local verification

- Full existing test suite: 64 passed.
- `program-identity validate-tasks`: all four task fixtures valid, including
  starter assertion failures, alternate public success and trusted failures,
  import origins, reference-patch application, and reference trusted success.
- Twelve additional reference-fixture runs exercised both new tasks across
  clean/installed/alternate and unguarded/guard modes using real runner commands,
  wheel construction, and independent evaluation. All reference repairs passed;
  verification appeared only in clean unguarded runs and all guarded runs, as
  expected. These fixture runs used supplied repairs, not a model, and are not
  included in empirical counts.
- Expanded launcher dry-run: 36 cells per mode, same pinned model and budgets.
- Remote-run script: `bash -n` passed. Whitespace check: `git diff --check` passed.

Local checks used Python 3.13.5; historical experiments used the recorded remote
Python 3.11 harness. Fresh integration checks on the remote host are still part
of the prepared script.
