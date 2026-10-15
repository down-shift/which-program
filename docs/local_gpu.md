# Local Qwen experiments on Ubuntu

The launcher starts a local vLLM server, waits for its model endpoint, runs coding
agents sequentially through the existing command runner, evaluates each frozen
delivery, writes a summary, and stops the server and its worker process group.
It also stops its server on Ctrl+C, SIGTERM, readiness failure, or experiment error.
It never adopts or shuts down another process already listening on the port.

The default is **Qwen/Qwen3-4B in BF16**, one sequence, 8,192 tokens of total context,
and 85% GPU memory utilization. This is the full 16-bit 4B option discussed for the
RTX 5080 with 16 GB. Successful loading and the available context capacity still
need verification on that GPU. These are starting settings for integration checks.

## Commands

From the repository checkout on Ubuntu, with `uv` installed and a working NVIDIA
driver (`nvidia-smi` must succeed):

```sh
uv sync --python 3.11

# Preview: no installation, model download, GPU use, or experiment writes.
uv run program-identity-local --dry-run

# Start the model and run ONE clean-condition repair first.
uv run program-identity-local

# After reviewing that run, launch nine runs: one task × three environments
# × three evidence treatments. This is a fresh batch and fresh server.
uv run program-identity-local --stage matrix

# Separate guard batch using the same model, agent, sampling, and budgets.
uv run program-identity-local --stage matrix --guard
```

The first real launch automatically creates `.venv-model` with Python 3.12 using
`uv venv` and installs the version pinned in `configs/local-qwen.yaml` using
`uv pip install`. Later launches reuse this environment and the Hugging Face
download cache. Server dependencies are isolated from the harness/test runtime.
Initial package installation and model downloads require network access and disk
space. Subsequent Hub-based launches still resolve the selected revision online;
a local checkpoint directory avoids Hub resolution.

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

The adapter uses a small JSON action protocol over local HTTP. The model selects
either `run` with an argv array or `final` with its final statement. Source reads,
edits, imports, and pytest commands all pass through the recorded execution runner.
There is no hidden scripted repair or task-specific solution in the adapter.
Commands use direct argv; shell pipelines and shell operators are unsupported.
This restriction is the same in every environment and evidence treatment.

Thinking is disabled with `chat_template_kwargs.enable_thinking=false`, as supported
by the [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B). Sampling, seed, protocol,
budgets, and model identity are held fixed within a batch. Thinking mode, different
quantizations, and different adapters would each define a different agent setup.

The default permits 16 model actions, 768 output tokens per response, 24,000 total
input-plus-output tokens across model requests, and 900 seconds per repair run.
The vLLM `/tokenize` endpoint checks each full conversation before generation so
the adapter can enforce context and token budgets; it checks returned usage against
that count. Reasoning tokens, protocol corrections, and repeated prompt tokens are
not free. No prompt truncation or retry silently changes the experiment. A truncated
response is logged and may be followed by an explicit correction request within
the same action/token budgets. Missing usage remains null; cost remains null.

Runs ending without a valid final response retain an empty final response and an
explicit termination reason. Infrastructure/API errors and budget exhaustion stop
the batch after saving the partial run. An invalid independent evaluation also
stops the batch. An ordinary incorrect repair with a valid evaluation remains a
recorded failure and does not stop later runs. Always inspect the first clean run
before proceeding; the launcher does not judge readiness from model claims.

## Saved artifacts and interpretation

Every invocation creates a new directory under `runs/local-qwen/` and prints its
path. It includes:

- `requested-config.yaml`, effective `config.yaml`, and `launch.json` with GPU
  information, model commit or local file hashes, startup status, and server argv;
- `server.log` and `server-packages.txt`;
- `runs/<run-id>/` with normal task snapshots, command logs, provenance, delivery,
  evaluator results, and full adapter request/response trajectories;
- `runs/summary.json` and `runs/summary.md`, including partial batches.

Hub revision names are resolved to a commit before serving; the same commit is
passed for the model and tokenizer. Local checkpoint directories are hashed before
launch and must remain unchanged while the server loads them. Package versions
are recorded per batch; the vLLM version is pinned, while its dependency resolution
is not a complete portable lock. Pin the resolved environment before research runs.

This script has offline mocked-server coverage. Actual vLLM/CUDA loading and real
Qwen tool-use behavior require the Ubuntu GPU integration check. One successful
clean repair is an integration check, not evidence about treatment effectiveness.
Manual claim coding remains required. The nine-run matrix does not determine a
sample size or produce confirmatory results.
