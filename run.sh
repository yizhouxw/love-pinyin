#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "run.sh currently supports macOS only." >&2; exit 1
fi
action="${1:-start}"
case "$action" in
  start|stop|top|restart|status|--prepare-only) ;;
  *) echo "Usage: ./run.sh [start|stop|restart|status|--prepare-only]" >&2; exit 1 ;;
esac
[[ $# -le 1 ]] || { echo "Expected at most one command." >&2; exit 1; }
export PATH="$PWD/private/runtime/npm/node_modules/.bin:$PWD/private/runtime/node/bin:$PWD/private/runtime/uv:$PATH"
source scripts/service-config.sh
source scripts/service-lifecycle.sh
load_service_config
case "$action" in
  status) show_service_status; exit $? ;;
  stop|top) stop_services; exit $? ;;
  restart)
    # A bad certificate must not take the working local service down.
    check_service_tls
    stop_services ;;
esac
if [[ "$action" != --prepare-only ]]; then
  discover_services
  if [[ "$lan_enabled" == 1 ]] && command -v node >/dev/null; then check_service_tls; fi
  if [[ -n "$https_pid" && "$https_host" != "$LOVE_PINYIN_BIND_IP" ]]; then
    echo "HTTPS is running on a different address; use restart to apply the new configuration." >&2
    exit 1
  fi
  if all_services_running; then
    echo "Love Pinyin is already running."
    show_service_status
    echo "Love Pinyin is ready."
    exit 0
  fi
  if [[ -n "$http_pid$https_pid" ]]; then
    check_service_tls
    [[ -x .venv/bin/uvicorn && -f dist/index.html ]] || { echo "Existing service has no prepared runtime/build; stop it and run ./run.sh again." >&2; exit 1; }
    echo "Starting the missing Love Pinyin endpoint."
    start_services
    exit $?
  fi
fi
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
if [[ "$action" != --prepare-only ]]; then check_service_tls; fi
printf '\nInstalling locked dependencies…\n'
npm ci --prefer-offline --no-audit --no-fund
uv sync --locked
printf '\nChecking local standard pinyin recordings (download only if missing)…\n'
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
rmdir "$setup_lock"
trap - EXIT INT TERM
start_services
