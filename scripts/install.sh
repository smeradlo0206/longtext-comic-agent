#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"
python3 -m venv "${PROJECT_ROOT}/.venv"
source "${PROJECT_ROOT}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Installed. Activate with: source ${PROJECT_ROOT}/.venv/bin/activate"
