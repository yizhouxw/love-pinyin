#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "run.sh currently supports macOS only." >&2; exit 1
fi
case "${1:-}" in
  ""|--prepare-only) ;;
  *) echo "Usage: ./run.sh [--prepare-only]" >&2; exit 1 ;;
esac
git_binary="${LOVE_PINYIN_GIT_BIN:-$(command -v git || true)}"
if [[ -z "$git_binary" ]] || ! "$git_binary" --version >/dev/null 2>&1; then
  git_binary=""
  for candidate in /opt/homebrew/bin/git /usr/local/bin/git; do
    if [[ -x "$candidate" ]] && "$candidate" --version >/dev/null 2>&1; then
      git_binary="$candidate"; break
    fi
  done
fi
[[ -n "$git_binary" ]] || { echo "A working Git is required. Complete Command Line Tools setup or provide LOVE_PINYIN_GIT_BIN." >&2; exit 1; }
export LOVE_PINYIN_GIT_BIN="$git_binary"
mkdir -p private/runtime
setup_lock="$PWD/private/setup.lock"
if ! mkdir "$setup_lock" 2>/dev/null; then
  echo "Another setup is running. If a prior setup was killed, remove the empty private/setup.lock directory and retry." >&2
  exit 1
fi
trap 'rmdir "$setup_lock" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
case "$(uname -m)" in
  arm64) node_arch=arm64; uv_arch=aarch64 ;;
  x86_64) node_arch=x64; uv_arch=x86_64 ;;
  *) echo "Unsupported Mac architecture" >&2; exit 1 ;;
esac
runtime_root="$PWD/private/runtime"
export PATH="$runtime_root/npm/node_modules/.bin:$runtime_root/node/bin:$runtime_root/uv:$PATH"
fetch() { curl --fail --location --show-error --retry 2 --connect-timeout 20 --max-time 300 "$1" -o "$2"; }
if ! command -v node >/dev/null || [[ "$(node --version)" != v24.18.1 ]]; then
  echo "Installing project-local Node 24.18.1…"
  node_file="node-v24.18.1-darwin-$node_arch.tar.gz"
  fetch "https://nodejs.org/dist/v24.18.1/SHASUMS256.txt" "$runtime_root/node-shasums.txt"
  fetch "https://nodejs.org/dist/v24.18.1/$node_file" "$runtime_root/$node_file"
  (cd "$runtime_root"; awk -v f="$node_file" '$2 == f' node-shasums.txt > node-check.txt; test -s node-check.txt; shasum -a 256 -c node-check.txt)
  mkdir -p "$runtime_root/node"
  tar -xzf "$runtime_root/$node_file" -C "$runtime_root/node" --strip-components=1
fi
if ! command -v npm >/dev/null || [[ "$(npm --version)" != 11.16.0 ]]; then
  echo "Installing project-local npm 11.16.0…"
  npm install --prefix "$runtime_root/npm" --no-save --package-lock=false npm@11.16.0
fi
if ! command -v uv >/dev/null || [[ "$(uv --version)" != 'uv 0.12.5'* ]]; then
  echo "Installing project-local uv 0.12.5…"
  uv_file="uv-$uv_arch-apple-darwin.tar.gz"
  fetch "https://github.com/astral-sh/uv/releases/download/0.12.5/$uv_file" "$runtime_root/$uv_file"
  fetch "https://github.com/astral-sh/uv/releases/download/0.12.5/$uv_file.sha256" "$runtime_root/uv-check.txt"
  (cd "$runtime_root"; shasum -a 256 -c uv-check.txt)
  mkdir -p "$runtime_root/uv"
  tar -xzf "$runtime_root/$uv_file" -C "$runtime_root/uv" --strip-components=1
fi
printf '\nInstalling locked dependencies…\n'
npm ci --prefer-offline --no-audit --no-fund
uv sync --locked
printf '\nSynchronizing standard pinyin recordings…\n'
uv run --locked python -m scripts.sync_standard_audio
printf '\nChecking bundled narration and lessons…\n'
uv run --locked python -m scripts.check_bundled_resources
printf '\nPreparing the pinned local recognition model…\n'
uv run --locked python -m scripts.fetch_asr_model
npm run build
npm run validate:release
if [[ "${1:-}" == --prepare-only ]]; then
  echo "All resources are ready."; exit 0
fi
app_port="${LOVE_PINYIN_PORT:-8000}"
[[ "$app_port" =~ ^[1-9][0-9]{0,4}$ ]] && ((app_port > 0 && app_port < 65536)) || { echo "Invalid LOVE_PINYIN_PORT" >&2; exit 1; }
printf '\nOpen http://127.0.0.1:%s (Ctrl+C stops the service)\n' "$app_port"
rmdir "$setup_lock"
trap - EXIT INT TERM
exec uv run --locked uvicorn server.main:app --host 127.0.0.1 --port "$app_port" --no-access-log
