# Local Qwen experiments on Ubuntu

The launcher starts a local vLLM server, waits for its model endpoint, runs coding
agents sequentially through the existing command runner, evaluates each frozen
delivery, writes a summary, and stops the server and its worker process group.
It also stops its server on Ctrl+C, SIGTERM, readiness failure, or experiment error.
It never adopts or shuts down another process already listening on the port.

The default is **Qwen/Qwen3-4B in BF16**, one sequence, 8,192 tokens of total context,
and 85% GPU memory utilization. This is the full 16-bit 4B option discussed for the
RTX 5080 with 16 GB. The supplied October 15 logs confirm this model loaded on that
GPU. They also show the original agent returned code suggestions without changing
files. The corrected `local-json-v2` agent must pass a new clean integration check
before a matrix can start; its real-model repair behavior remains to be tested.

## Commands

From the repository checkout on Ubuntu, with `uv` installed and a working NVIDIA
driver (`nvidia-smi` must succeed):

```sh
uv sync --python 3.11

# Preview: no installation, model download, GPU use, or experiment writes.
uv run program-identity-local --dry-run

# Start the model and check each configured task in clean/ordinary conditions.
uv run program-identity-local

# Only a batch reporting check_passed can authorize the following matrix.
# Replace <new-check-batch> with its printed batch directory.
uv run program-identity-local --stage matrix --check runs/local-qwen/<new-check-batch>

# Separate guard batch using the same model, agent, sampling, and budgets.
uv run program-identity-local --stage matrix --guard --check runs/local-qwen/<new-check-batch>
```

The first real launch automatically creates `.venv-model` with Python 3.12 using
`uv venv` and installs the version pinned in `configs/local-qwen.yaml` using
`uv pip install`. Later launches reuse this environment and the Hugging Face
download cache. Server dependencies are isolated from the harness/test runtime.
Initial package installation and model downloads require network access and disk
space. Floating Hub revisions are resolved online. Matrix launches reuse the
immutable revision from the successful check. Explicit commit hashes and local
checkpoint directories avoid Hub revision lookup.

## Resume a batch or sequence

The expanded sequence automatically discovers compatible saved batches. Rerun
the same command after a failure or interruption:

```sh
# Preview which batches will be kept, resumed, or created; no writes or GPU use.
bash scripts/run_expanded_pilot.sh --dry-run

# Continue seeds 18–20; completed matrices and collected cells are retained.
bash scripts/run_expanded_pilot.sh
```

The sequence obtains a fresh clean check when the harness has changed, skips
completed matrices, and resumes incomplete ones. An unsuccessful repair or
budget-exhausted agent outcome is a collected observation and is not rerun.
A run that stopped collection because evaluation or observation failed is
archived and retried. A cell interrupted before saving a complete outcome is
also retried. There is no continuation of an individual model conversation.

To resume a specific matrix directly, supply a current successful integration
check if the original receipt is stale:

```sh
uv run program-identity-local \
  --resume runs/local-qwen-expanded/<failed-batch> \
  --check runs/local-qwen-expanded/<current-clean-check>
```

The launcher restores stage, mode, seed, and settings from the saved batch. It
rejects changed experiment settings, agent prompts, task snapshots, model identity,
or server dependencies; these require a new batch. Harness fixes may be resumed
after a current check. The updated launch retains `resume_history` and archives
the previous launch, effective config, logs, summary, and superseded run directories
under `attempts/`. Collected run files remain unchanged, with their original agent
and setup metadata. New runs record the current harness's agent ID, so summaries
can retain separate setup strata when a harness fix changed the fingerprint.
Only the selected current attempt for each cell appears in the active summary.
Do not combine superseded attempts as independent replications.

Launch-state writes are atomic, and a batch lock rejects simultaneous launchers.
A failed resume preflight writes a diagnostic under `attempts/` without replacing
the historical launch or summary.

vLLM's [GPU installation documentation](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/index.html?device=cuda)
describes driver and CUDA compatibility. The script records `nvidia-smi` output
and installed server packages. It does not install or modify NVIDIA drivers.
If startup fails, inspect `server.log`; if GPU memory is insufficient, adjust
`context_length` or `gpu_memory_utilization` explicitly before starting a new batch.

## Selecting the 8B model

An existing **vLLM-compatible quantized checkpoint directory or Hub ID** can be
selected explicitly:

```sh
uv run program-identity-local --model /absolute/path/to/qwen3-8b-int8
```

This does not quantize ordinary BF16 weights into INT8. The checkpoint must already
contain a supported quantization format and its configuration. For loaders needing
an explicit method, set `model.quantization` in the YAML. GGUF files need a separate
llama.cpp integration; passing a GGUF file to this launcher is unsupported.

The official [Qwen/Qwen3-8B-FP8](https://huggingface.co/Qwen/Qwen3-8B-FP8)
is another explicit option supported by Qwen's vLLM instructions:

```sh
uv run program-identity-local --model Qwen/Qwen3-8B-FP8
```

**FP8 and INT8 are different formats.** The launcher does not substitute one model,
precision, context setting, or sampling configuration for another after a failure.
Record a deliberate config change as a new batch.

## Agent and budget behavior

The versioned `local-json-v2` adapter uses a small JSON action protocol over local
HTTP. The model can select `read_file`, `write_file`, `run` with an argv array, or
`final` with its final statement. File actions are translated to Python argv
commands and pass through the same recorded runner as imports and pytest commands.
The common prompt explicitly requests filesystem edits and explains that a code
listing in the final response is not applied to the workspace. Final responses
remain verbatim; the adapter never extracts and applies a suggested Markdown patch.
The same prompt and actions apply across all evidence treatments.
There is no hidden scripted repair or task-specific solution in the adapter.
Commands use direct argv; shell pipelines and shell operators are unsupported.
This restriction is the same in every environment and evidence treatment.

Thinking is disabled with `chat_template_kwargs.enable_thinking=false`, as supported
by the [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B). Sampling, seed, protocol,
budgets, and model identity are held fixed within a batch. Thinking mode, different
quantizations, and different adapters would each define a different agent setup.
Temperature, top-p, top-k, min-p, and repetition penalty are explicit in requests.
`--generation-config vllm` disables inherited model generation defaults. Protocol,
prompt hash, checkpoint, task, budget, and runtime fingerprints identify the new
agent setup in reports so it is not pooled with the original integration runs.

The default permits 16 model actions, 768 output tokens per response, 24,000 total
input-plus-output tokens across model requests, and 900 seconds per repair run.
The vLLM `/tokenize` endpoint checks each full conversation before generation so
the adapter can enforce context and token budgets; it checks returned usage against
that count. Reasoning tokens, protocol corrections, and repeated prompt tokens are
not free. No prompt truncation or retry silently changes the experiment. A truncated
response is logged and may be followed by an explicit correction request within
the same action/token budgets. Missing usage remains null; cost remains null.

Runs ending without a valid final response retain an empty final response and an
explicit termination reason. Infrastructure/API errors stop
the batch after saving the partial run. An invalid independent evaluation also
stops the batch. An ordinary incorrect repair with a valid evaluation remains a
recorded failure and does not stop later matrix runs. Action, context/token, and
run deadline exhaustion are retained as incomplete outcomes and collection continues,
without automatic retries or fabricated final claims. Their delivered source is
still independently evaluated. Guard runs with no supported test invocation are
retained as `no_test_command` or `unsupported_command`, not guard successes.
Actual guard identity failures still stop collection. A clean integration check
with an incomplete response remains `check_failed`; it cannot authorize a matrix.

The **check stage** reports `check_passed` only when every configured task has an
actual source modification, a complete passing public suite, valid final-source
identity, a successful independent evaluation, and a returned final response. It
writes all checks to `readiness.json`, prints their outcomes, and exits nonzero
with `check_failed` for an unchanged or incorrect repair. `completed` is reserved
for collection of matrix outcomes and does not mean every repair succeeded.

The matrix requires `--check` pointing to a successful current-version check and
compares model identity, tasks, prompt/protocol, sampling, budgets, server packages,
and harness sources before starting the model. Changed settings require a new
check. This is a setup integration gate; once a matrix starts, unsuccessful repairs
are retained and never selectively excluded or retried to obtain successful data.

## Saved artifacts and interpretation

Every invocation creates a new directory under `runs/local-qwen/` and prints its
path. It includes:

- `requested-config.yaml`, effective `config.yaml`, and `launch.json` with GPU
  information, model commit or local file hashes, startup status, and server argv;
- `server.log` and `server-packages.txt`;
- `readiness.json` for a completed check stage, with individual acceptance checks;
- `runs/<run-id>/` with normal task snapshots, command logs, provenance, delivery,
  evaluator results, and full adapter request/response trajectories;
- `runs/summary.json` and `runs/summary.md`, including partial batches. Launch
  metadata distinguishes planned run count from completed run count.

A guard run with no supported test invocation records `guard_status: no_test_command`
in its launch outcome (or `unsupported_command` for unsupported invocations).
Collection continues and summaries preserve these counts. This is distinct from a guarded invocation with an unknown or
incorrect execution identity; no guard effectiveness outcome can be inferred from
an agent that never invoked the guard.

Hub revision names are resolved to a commit before serving; the same commit is
passed for the model and tokenizer. Local checkpoint directories are hashed before
launch and must remain unchanged while the server loads them. Package versions
are recorded per batch; the vLLM version is pinned, while its dependency resolution
is not a complete portable lock. Pin the resolved environment before research runs.

Pytest records both raw nodeids and identities relative to the agent workspace,
using the collected test file's actual path. Parent-repository pytest configuration
therefore does not change suite identity; same-named tests outside the workspace
cannot establish that the public suite ran. Complete failing public suites have a
separate `complete_public_suite_failed` status. Original raw runs are not rewritten.

This script has offline mocked-server coverage. Real Qwen tool-use behavior with
the new protocol requires the Ubuntu GPU integration check. One successful
clean repair is an integration check, not evidence about treatment effectiveness.
Manual claim coding remains required. The nine-run matrix does not determine a
sample size or produce confirmatory results.
