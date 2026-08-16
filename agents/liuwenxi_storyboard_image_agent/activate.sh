#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "This script must be sourced so the environment remains active:" >&2
  echo "  source /code/lwx/anime-agent/activate.sh" >&2
  exit 1
fi

source /root/miniconda3/etc/profile.d/conda.sh
conda activate /opt/conda/envs/lwx-anime-agent
cd /code/lwx/anime-agent

echo "Activated: ${CONDA_PREFIX}"
echo "Project:   ${PROJECT_ROOT}"
echo "Models:    ${MODEL_ROOT}"
echo "Outputs:   ${OUTPUT_ROOT}"
