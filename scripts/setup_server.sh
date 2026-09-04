#!/usr/bin/env bash
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-v24.13.0}"
CODEX_VERSION="${CODEX_VERSION:-0.147.0}"
NODE_DIST="node-${NODE_VERSION}-linux-x64"
NODE_ARCHIVE="${NODE_DIST}.tar.xz"
NODE_URL="https://nodejs.org/dist/${NODE_VERSION}"
INSTALL_ROOT="/opt/${NODE_DIST}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This installer expects an x86_64 Linux host." >&2
  exit 1
fi

if [[ ! -d "${INSTALL_ROOT}" ]]; then
  TEMP_ROOT="$(mktemp -d)"
  trap 'rm -rf "${TEMP_ROOT}"' EXIT
  curl --fail --location --retry 3 --output "${TEMP_ROOT}/${NODE_ARCHIVE}" \
    "${NODE_URL}/${NODE_ARCHIVE}"
  curl --fail --location --retry 3 --output "${TEMP_ROOT}/SHASUMS256.txt" \
    "${NODE_URL}/SHASUMS256.txt"
  (
    cd "${TEMP_ROOT}"
    grep " ${NODE_ARCHIVE}$" SHASUMS256.txt | sha256sum --check --strict -
  )
  tar -xJf "${TEMP_ROOT}/${NODE_ARCHIVE}" -C /opt
fi

for command in node npm npx corepack; do
  ln -sfn "${INSTALL_ROOT}/bin/${command}" "/usr/local/bin/${command}"
done

npm install --global "@openai/codex@${CODEX_VERSION}"
ln -sfn "${INSTALL_ROOT}/bin/codex" /usr/local/bin/codex
mkdir -p /root/.codex
chmod 700 /root/.codex

node --version
npm --version
codex --version
