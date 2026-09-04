#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/.venv/bin/activate"
exec flux2-agent --workspace "${PROJECT_ROOT}" run "${PROJECT_ROOT}/configs/example.json" "$@"
