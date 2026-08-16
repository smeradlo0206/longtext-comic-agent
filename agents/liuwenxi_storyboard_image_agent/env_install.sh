#!/usr/bin/env bash
set -Eeuo pipefail

ENV_PATH="/opt/conda/envs/lwx-anime-agent"
PROJECT_ROOT="/code/lwx/anime-agent"
PERSIST_ROOT="/output/lwx/anime-agent"
TEMP_ROOT="/tmp/lwx-anime-agent"
PIP_INDEX="https://pypi.mirrors.ustc.edu.cn/simple/"

cleanup() {
  rm -rf "${TEMP_ROOT}/conda-pkgs" "${TEMP_ROOT}/pip-cache"
}

trap 'echo "Environment installation failed at line ${LINENO}." >&2' ERR

test -w /code
test -w /output
test -w /opt/conda/envs
test "$(findmnt -n -o FSTYPE -T /output)" = "fuse.juicefs"

mkdir -p \
  "${PROJECT_ROOT}/src" \
  "${PERSIST_ROOT}/models/huggingface" \
  "${PERSIST_ROOT}/models/torch" \
  "${PERSIST_ROOT}/models/qwen-image-2512" \
  "${PERSIST_ROOT}/models/qwen-image-edit-2509" \
  "${PERSIST_ROOT}/models/qwen2.5-vl-7b" \
  "${PERSIST_ROOT}/datasets" \
  "${PERSIST_ROOT}/characters" \
  "${PERSIST_ROOT}/outputs" \
  "${PERSIST_ROOT}/runs" \
  "${PERSIST_ROOT}/runs/image-provider" \
  "${PERSIST_ROOT}/outputs/image-provider" \
  "${PERSIST_ROOT}/bootstrap" \
  "${TEMP_ROOT}/conda-pkgs" \
  "${TEMP_ROOT}/pip-cache" \
  "${TEMP_ROOT}/scratch" \
  "${TEMP_ROOT}/cache"

cat > "${TEMP_ROOT}/condarc" <<'EOF'
channels:
  - defaults
show_channel_urls: true
default_channels:
  - https://mirrors.ustc.edu.cn/anaconda/pkgs/main
  - https://mirrors.ustc.edu.cn/anaconda/pkgs/r
  - https://mirrors.ustc.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.ustc.edu.cn/anaconda/cloud
  pytorch: https://mirrors.ustc.edu.cn/anaconda/cloud
EOF

export CONDARC="${TEMP_ROOT}/condarc"
export CONDA_PKGS_DIRS="${TEMP_ROOT}/conda-pkgs"
export PIP_CACHE_DIR="${TEMP_ROOT}/pip-cache"
export TMPDIR="${TEMP_ROOT}"

source /root/miniconda3/etc/profile.d/conda.sh

if [[ ! -x "${ENV_PATH}/bin/python" ]]; then
  conda create -y -p "${ENV_PATH}" python=3.10 pip
fi

conda activate "${ENV_PATH}"

python -m pip install --no-cache-dir --upgrade pip -i "${PIP_INDEX}"
python -m pip install --no-cache-dir \
  torch==2.7.1 \
  torchvision==0.22.1 \
  -i "${PIP_INDEX}"
python -m pip install --no-cache-dir \
  -r "${PROJECT_ROOT}/requirements.txt" \
  -i "${PIP_INDEX}"

mkdir -p "${ENV_PATH}/etc/conda/activate.d" "${ENV_PATH}/etc/conda/deactivate.d"

cat > "${ENV_PATH}/etc/conda/activate.d/anime-agent.sh" <<EOF
export PROJECT_ROOT="${PROJECT_ROOT}"
export MODEL_ROOT="${PERSIST_ROOT}/models"
export DATASET_ROOT="${PERSIST_ROOT}/datasets"
export CHARACTER_ROOT="${PERSIST_ROOT}/characters"
export OUTPUT_ROOT="${PERSIST_ROOT}/outputs"
export RUN_ROOT="${PERSIST_ROOT}/runs"
export HF_HOME="${PERSIST_ROOT}/models/huggingface"
export HF_HUB_CACHE="${PERSIST_ROOT}/models/huggingface/hub"
export HF_ENDPOINT="https://hf-mirror.com"
export TORCH_HOME="${PERSIST_ROOT}/models/torch"
export SCRATCH_ROOT="${TEMP_ROOT}/scratch"
export XDG_CACHE_HOME="${TEMP_ROOT}/cache"
export TMPDIR="${TEMP_ROOT}"
EOF

cat > "${ENV_PATH}/etc/conda/deactivate.d/anime-agent.sh" <<'EOF'
unset PROJECT_ROOT MODEL_ROOT DATASET_ROOT CHARACTER_ROOT OUTPUT_ROOT RUN_ROOT
unset HF_HOME HF_HUB_CACHE HF_ENDPOINT TORCH_HOME SCRATCH_ROOT XDG_CACHE_HOME TMPDIR
EOF

cp "${PROJECT_ROOT}/env_install.sh" "${PERSIST_ROOT}/bootstrap/env_install.sh"
cp "${PROJECT_ROOT}/requirements.txt" "${PERSIST_ROOT}/bootstrap/requirements.txt"

cleanup
echo "Environment ready: ${ENV_PATH}"
