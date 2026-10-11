# Protocol

The matrix crosses two task snapshots with clean target imports, a locally built non-editable wheel in an isolated virtual environment, and a second checkout, then crosses those conditions with ordinary output, provenance display, and provenance plus an identity-check instruction. Pairing uses task and seed. Guard runs are a distinct execution mode and are summarized separately. Public inputs, budgets, and model configuration are identical within each task's matrix.

The alternate snapshots are plausible prior revisions with a documented behavioral difference; their public tests fail before repair. The agent can inspect all paths, interpreter details, and installed package metadata with ordinary shell/Python commands. Trusted tests and observer records live outside the agent workspace. Only `package/rules.py` may be delivered as a patch. This is a controlled susceptibility stress test, not an estimate of production prevalence.

Each command record includes its original command, execution cwd and environment, exit status, output, and elapsed time. Python commands are routed through `uv run`; the installed-copy condition selects its isolated venv interpreter. The package wheel is built locally and installed with `uv pip`; if uv exits with its known macOS proxy-discovery panic (101), the harness places the simple local wheel into the venv using the standard wheel archive layout. Raw command records and provenance are retained outside the workspace. Ordinary treatment does not display provenance. Display and instruction treatments append provenance records to command output. Configured budgets are persisted; usage is nullable.

## Provenance boundary

Instrumentation is injected cooperatively with `PYTHONPATH` and wraps ordinary filesystem `SourceFileLoader` modules at `exec_module`, recording source bytes and target bytes before module execution. The source hash therefore describes the file at module load, not a later read. It records path equality separately from content equality. A different path with identical bytes is an equivalent copy. Unknown loader types, absent source, mapping errors, and visible bytecode caches produce unknown instrumentation. The runner sets `-B` for its test command and `PYTHONDONTWRITEBYTECODE`; this does not make Python instrumentation tamper-proof. Obvious loss is represented by missing records. The threat model is a cooperative agent, not adversarial process tampering. Container/OS enforcement is future work.

The identity-binding guard forces the supported pytest command's `PYTHONPATH` to the target checkout and checks provenance identity. It does not force arbitrary custom commands, instrument non-Python code, or convert unknown/mismatched identity into a passing result. Guard effects are not pooled with evidence-display effects.

Evaluator reconstructs starter files in a fresh temporary directory, copies only permitted delivered source paths, and runs trusted tests in a fresh target-root import environment with a timeout. Scope violations, test outcomes, and evaluator identity are separate fields. Evaluator failures/unknown identity are not automatically repair failures. Agent workspace edits to tests or packaging remain in its trajectory and are never copied to trusted tests.

## Pilot stop rules

- Stop if mismatches require arbitrary or inaccessible traps.
- Stop if the agent cannot inspect the relevant environment.
- Stop if provenance is unreliable.
- Stop if the clean condition is not genuinely clean.

No paid model runs or confirmatory analyses are part of this scaffold. Choose pilot sample size and inferential analysis only after validating the harness.
