# Which Program Did You Test?

A small controlled study scaffold for whether a coding agent's tests executed the source it edited. It records three outcomes separately: runtime execution identity, independent repair correctness, and whether a final verification claim is supported by the command evidence. A correct patch tested against stale code does not verify the delivered patch; a wrong patch tested against the target is an ordinary repair failure. This is a susceptibility stress test under specified conditions, not an estimate of production prevalence. The scaffold makes no claim about research novelty or treatment effectiveness.

## Install

Install Python 3.11+, `uv`, and the project dependencies as a separate setup step:

```sh
uv sync
```

Use `uv` for project commands and environment creation. The offline harness builds local wheels and does not require model credentials.
The CLI expects to run from this repository checkout because task, config, and documentation fixtures are repository assets; they are not embedded in the built Python wheel.

## How a run works

For example, an agent edits `checkout/package/rules.py`, runs `python -m pytest -q public_tests`, and sees a pass. The import path may resolve to the local checkout, a locally installed wheel, or a second checkout. At module load, the observer records the source bytes actually compiled and the corresponding delivered target bytes. The runner retains raw output in its observer logs; ordinary treatment only shows stdout/stderr to the agent.

After the agent returns, the harness freezes the delivered tree and a patch against the initial workspace, including ordinary workspace edits. A separate evaluator reconstructs that frozen tree in a temporary workspace and runs trusted regression tests. The observer distinguishes source execution from meaningful regression verification: the latter requires a complete, passing configured public suite, unchanged public test files, and loaded source hashes matching the frozen delivery. An earlier mismatch followed by a cited qualifying command can therefore support a later claim. Unknown instrumentation remains unknown.

## Commands

```sh
uv run program-identity validate-tasks
uv run program-identity smoke --config configs/smoke.yaml
uv run program-identity run --config configs/pilot.yaml
uv run program-identity evaluate --run runs/pilot-template/<run-directory>
uv run program-identity summarize --runs runs/pilot-template
uv run program-identity annotate --run runs/pilot-template/<run-directory> --file annotation.json
```

The smoke matrix includes clean imports, separately installed passing copies, other passing checkouts, and separate failing-copy controls. It crosses these with ordinary output, provenance display, and provenance plus an instruction to check source identity. Guard runs execute as a separate mode. The scripted agents exercise an unjustified claim, explicit identity inspection, and an incorrect repair; their outputs are harness checks, not empirical evidence about coding models.

Runs are unique directories. Each retains the config, pre-run task snapshot and hashes, workspace trajectory, raw command output, provenance events, frozen delivery and patch, evaluation history and selected evaluation, plus provisional claim cues. Manual annotations are separate. The summary reports treatment, condition, task, model, and pairing keys; guard rows are separate.

## Add a task or agent

Add a task directory with a precise instruction, `starter/`, passing-but-different `alternate/`, public tests, trusted tests, a valid reference patch, and task metadata. `uv run program-identity validate-tasks` checks reference-patch application, starter public assertion failures, alternate public success, and the reference patch against trusted tests. Declare monitored modules and the dependency scope; identity claims cover only those modules.

Implement `AgentAdapter.run` in `src/program_identity/agents/base.py`. It receives instruction, workspace, command execution callable, evidence treatment, model config, seed, and budgets. It returns a final response, trajectory, delivered source changes (or edits the workspace), usage where available, and termination metadata. Keep token and cost values null when unavailable. Use the annotation JSON schema described in [the rubric](docs/claim_rubric.md); keyword cues are provisional only.

Read [the experiment protocol](docs/protocol.md) and [limitations](docs/limitations.md) before configuring a real-agent pilot.

## Run a local GPU model

On Ubuntu with an NVIDIA GPU, the launcher installs a separate pinned vLLM server,
loads Qwen3-4B in BF16 by default, runs one clean repair, saves the full trajectory
and independent evaluation, and shuts down its server:

```sh
uv sync --python 3.11
uv run program-identity-local --dry-run
uv run program-identity-local
```

After reviewing the clean run, `uv run program-identity-local --stage matrix` runs
the nine cells in `configs/local-qwen.yaml`. Use `--guard` for a separate guard batch.
Model selection, 8B quantized checkpoints, dependencies, artifacts, and limitations
are documented in [the Ubuntu GPU instructions](docs/local_gpu.md).
