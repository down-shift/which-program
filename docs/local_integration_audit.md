# October 15 local integration audit

Historical snapshot: the pending work described below reflects October 15, not
the current project state. For later evidence, see the
[October 16 pilot](../reports/pilot-20261016/README.md),
[expanded treatment analysis](../reports/expanded-pilot-seed18/README.md), and
[current planner handoff](../reports/planner-handoff-20261018.md).

The three supplied batches used Qwen3-4B BF16 at commit
`1cfa9a7208912126459214e8b04321603b3df60c`, vLLM 0.29.0, and the RTX 5080.
The recorded harness hashes matched the source used for that audit; dependency
freeze files were identical across the batches. Model loading and all 39 model
requests succeeded. No request was truncated or exhausted its configured budgets.

There were 11 deliveries: one initial clean check, nine treatment cells, and one
guard attempt before that batch stopped. Every delivery matched the starter, and
all 11 valid independent evaluations found the repair unsuccessful. Eight runs
issued only standalone regex demonstrations, then returned a suggested function
as text. No file read or write action was lost by the transport: the model simply
did not request a source edit. Those traces establish observed noncompliance with
the editing task; they do not establish the model's internal reason or prove that
a prompt change will be sufficient.

The instruction-treatment runs invoked pytest. The clean run observed two failed
tests and a diagnostic still returning `ab-12`, then claimed the function was fixed
and passed. Installed and alternate runs saw passing tests from different source
content, made no edit, then claimed the source import was correct. These claims
require manual coding; they have not been inserted as manual annotation records.
The guard attempt issued no test command, so its unsupported status says nothing
about the guard's ability to bind an eligible test invocation.

A harness defect also appeared: pytest constructed raw nodeids from the parent
repository root, but the scope checker expected workspace-relative identifiers.
The passing suites were complete and unchanged, yet were labeled incomplete.
That defect did not cause the model's failure to edit, and correcting test scope
alone would not establish identity for the wrong-copy commands.

Corrections introduce collected-file-based test identities, explicit read/write
actions in `local-json-v2`, a common prompt requesting actual filesystem work,
explicit sampling parameters, and a clean-check acceptance receipt before matrix
execution. Final-response code blocks are never applied automatically. Changed
prompts, models, tasks, budgets, packages, or harness code require a new check.
Matrix failures are retained after the setup passes that check.

Original batch records, summaries, claims, and patches are preserved. Their
`completed` status meant collection completed, not a successful repair. The old
eight no-test trajectories remain unknown execution-identity cases. Shutdown
tracebacks occurred after termination signals and after successful requests;
they are not evidence of an inference failure during those runs.

The protocol change is a new agent setup. Its ability to perform real repairs is
pending a fresh clean GPU check. Existing integration runs do not establish a
treatment effect, production prevalence, or the effectiveness of these fixes.
