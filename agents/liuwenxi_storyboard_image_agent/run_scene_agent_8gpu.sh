#!/usr/bin/env bash
set -Eeuo pipefail

source /code/lwx/anime-agent/activate.sh >/dev/null
export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export ASSET_ROOT="${ASSET_ROOT:-${PROJECT_ROOT}/assets/presets}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
unset CUDA_VISIBLE_DEVICES

exec python -m anime_image_agent serve --host 127.0.0.1 --port 8000 --backend qwen "$@"
