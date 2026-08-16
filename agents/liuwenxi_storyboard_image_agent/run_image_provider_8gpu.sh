#!/usr/bin/env bash
set -Eeuo pipefail

source /code/lwx/anime-agent/activate.sh >/dev/null

export PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
unset CUDA_VISIBLE_DEVICES

exec python -m anime_image_agent run "$@"
