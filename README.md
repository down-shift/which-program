# Which Program Did You Test?

A small controlled empirical-study scaffold for measuring whether a coding agent's test process executed the source it edited. It separates execution identity, repair correctness under independent regression tests, and support for the agent's final verification claim. A correct patch tested against a stale installed copy is not evidence that the delivered patch was verified; a faulty patch run from the target checkout is an ordinary repair failure. The study is a controlled stress test under specified conditions, not an estimate of production prevalence. This implementation does not establish the hypothesis or make novelty/effectiveness claims.

## Install

From the repository root, install dependencies and the local CLI:

```sh
uv sync
```

## Example

An agent edits `workspace/package/rules.py`, runs pytest, and sees a pass. Provenance may show that Python loaded `venv/.../site-packages/package/rules.py`. The harness records loaded source hash and path at module load, then independently applies the delivered source to a fresh starter reconstruction and runs trusted tests. The three outcomes remain separate in the run and evaluator records.

## Commands

```sh
uv run program-identity validate-tasks
uv run program-identity smoke --config configs/smoke.yaml
uv run program-identity run --config configs/pilot.yaml
uv run program-identity evaluate --run runs/pilot/<run-directory>
uv run program-identity summarize --runs runs/pilot
```

Smoke uses only the scripted adapter and locally built package artifacts; it needs no model credentials. It creates unique run directories and persists config-relevant settings, task file hashes, environment details, trajectories, raw command output, provenance, delivered patch, evaluator output, and provisional annotations. `uv run pytest` runs the harness tests. See [protocol](docs/protocol.md), [claim rubric](docs/claim_rubric.md), and [limitations](docs/limitations.md).

## Add a task or adapter

Add a task directory with `task.yaml`, instruction, immutable `starter/`, inspectable `alternate/`, public tests, independent trusted tests, and reference patch. Declare package/module, editable paths, and allowed patch scope. `uv run program-identity validate-tasks` checks required files and metadata and verifies that alternate public tests fail before repair.

For a real coding agent, implement `AgentAdapter.run` in `src/program_identity/agents/base.py`: accept instruction, workspace, execution callable, evidence treatment, model configuration, seed, and budgets; return final response, trajectory, an optional delivered patch (or edit the provided workspace), usage, and termination metadata. Set `model.adapter` to `your.module:AdapterClass` in the run config. Do not fabricate unavailable token/cost fields. Add human claim annotations separately from raw run files.
