#!/usr/bin/env bash
# Re-running this command continues the sequence from saved batch artifacts.
set -euo pipefail
cd "$(dirname "$0")/.."

exec uv run python -m program_identity.sequence "$@"
