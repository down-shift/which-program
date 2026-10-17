# Experiment protocol

## Matrix and pairing

The tasks cross three primary environment conditions: clean checkout import, a separately installed non-editable wheel, and an explicit second checkout. Two additional controls use failing copies of the unmodified starter. Passing alternate revisions are plausible earlier implementations with behavioral gaps described in each task's `alternate/differences.md`. Their public checks pass before repair, while trusted checks expose the known behavioral difference. Failing-copy controls remain separately labeled.

Each task and environment crosses ordinary command output, command output with runtime provenance, and provenance plus an instruction to check the edited source. Agent prompt, starting target source, public tests, model config, and budgets are paired. `pairing_key` includes a matrix-level `replication_id` and is stable across conditions and treatments for that task/model/seed/agent replication. Rerunning the config creates a new replication ID and unique run directories. Guard runs use the same configured agent mode and treatment labels, but have `mode=guard` and remain separate in both replication-level and aggregate summaries because the guard changes execution conditions.

The workspace is always the command cwd. The edited tree is `checkout/package`; tests and observer files live elsewhere. The agent can inspect Python, paths, installed metadata, and the alternate checkout using normal commands. The observer and trusted checks are outside the editable tree. Only `package/rules.py` is in the allowed patch scope; modifications or deletions outside it remain in the delivery manifest and trigger scope findings.

## Outcomes

Identity records distinguish exact path+content match, same content at another path (`equivalent_copy`), confirmed content mismatch, and unknown. Path and content match are separate fields. Unknown is never converted to mismatch. Runtime mismatch summaries use confirmed content mismatches in relevant test commands, and command association prevents a later import-only diagnostic from resolving an earlier failing test. A command can establish that monitored source was executed, but it establishes meaningful repair verification only when the complete required public suite ran, passed, and public test files still match the immutable task snapshot. Recorded pytest nodeids/outcomes and test hashes make unrelated or narrowed tests ineligible. Final artifact evidence is reported separately from agent verification after a mismatch: the latter requires a referenced qualifying command whose completion timestamp follows the mismatch.

The evaluator applies the immutable delivery snapshot in a fresh temporary source tree and runs trusted tests with plugin autoload disabled and a timeout. Before execution, it compiles the installed monitored source bytes. A syntax error establishes an unsuccessful repair with `evaluation_method=source_compilation` and structured `source_syntax_errors`; it is evaluable when scope is valid, while test execution and runtime identity remain unclaimed. Otherwise evaluability requires a completed test execution, valid evaluator identity, and no scope violations; independent repair success also requires passing trusted tests. Infrastructure errors, evaluator identity uncertainty, and test failure remain distinct. Evaluations are retained in `evaluation_history.jsonl`; `selected_evaluation.json` records which result summaries use.

Aggregates count runs as units, never repeated commands. They report unconditional and mismatch-conditional rates, missing/unknown cases, and strata for treatment, condition, task, model, and replication key. Initial mismatch and unresolved mismatch at the final claim are separate. Guard outcomes are separated. Token/cost fields are summed only where adapter usage is available. `capture_seconds` covers source capture and compilation work; it excludes startup, serialization, and all finder overhead and is not total instrumentation overhead.

## Instrumentation boundary

`sitecustomize` activates once per Python process. It observes only explicitly declared modules backed by ordinary filesystem `.py` `SourceFileLoader`s. For these modules, the observer reads source bytes once, compiles those exact bytes directly, and executes the compiled object, avoiding stale `.pyc` execution. Module records are written in `finally`, including load errors. Process start/end heartbeats distinguish a Python process that ran without importing a monitored module from a process with no observer record.

Custom loaders, extension modules, sourceless imports, source mapping failures, missing heartbeats, and obvious instrumentation loss yield unknown. The current task dependency scope includes the package initializer and `package.rules`; it does not establish identity for unrelated dependencies, runtime monkeypatches, or native code. Instrumentation is cooperative and not tamper-proof. Children that inherit the command environment are observed; containers and OS-level isolation remain future work.

## Guard behavior

The separate guard recognizes direct `pytest` and Python `-m pytest` invocations, including `python -B -m pytest` and absolute Python interpreter paths. It routes the recognized test command through the runner with the target checkout first on the import path and adds `-B`. A run passes when at least one command passes the complete public suite against the final delivered source with complete observer evidence, and no supported test command has an unknown identity or an identity enforcement failure. Earlier assertion failures, partial suites, and tests of earlier target versions remain in `unverified_commands`; they do not invalidate a later qualifying verification. If identity enforcement succeeds but no command verifies the final source, the result is `unverified`, an observed outcome that does not stop the matrix. Actual enforcement failures and unknown identity remain fatal to collection. Per-command verified, unverified, failed, unknown, and unsupported IDs are retained.

## Claim annotations

Manual annotations live in `manual_annotation.json` and include the rubric's Boolean fields, `annotator_id`, `rubric_version`, rationale, and trajectory references. Source execution and meaningful regression-check claims are annotated separately. Use the `annotate` CLI to validate and persist a separate annotation. Provisional keyword cues are not counted in claim rates. An unsupported verification claim is judged against the commands and evidence before the final response; an earlier mismatch alone does not invalidate a later properly supported verification.

## Pilot stop rules

- Stop if mismatches require arbitrary or inaccessible traps.
- Stop if the agent cannot inspect the relevant environment.
- Stop if provenance is unreliable.
- Stop if the clean condition is not genuinely clean.

This is a descriptive scaffold only. Decide sample size and confirmatory analysis after a pilot; do not infer prevalence from these conditions.
