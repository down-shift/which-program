#!/usr/bin/env bash
# Run on the Linux NVIDIA host after syncing the expanded tasks and config.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p runs/local-qwen-expanded/configs
for run_seed in 18 19 20; do
  task_config="runs/local-qwen-expanded/configs/seed-${run_seed}.yaml"
  uv run python - "$run_seed" "$task_config" <<'PY'
import sys
from pathlib import Path
import yaml
config = yaml.safe_load(Path("configs/local-qwen-expanded.yaml").read_text())
config["seed"] = int(sys.argv[1])
Path(sys.argv[2]).write_text(yaml.safe_dump(config, sort_keys=False))
PY

  run_cmd=(uv run program-identity-local --config "$task_config")
  check_log=$(mktemp)
  trap 'rm -f "$check_log"' EXIT
  "${run_cmd[@]}" --stage check | tee "$check_log"
  check_batch=$(awk '/^Batch: / {print $2; exit}' "$check_log")
  test -n "$check_batch"
  "${run_cmd[@]}" --stage matrix --check "$check_batch"
  "${run_cmd[@]}" --stage matrix --guard --check "$check_batch"
  rm -f "$check_log"
  trap - EXIT
done
