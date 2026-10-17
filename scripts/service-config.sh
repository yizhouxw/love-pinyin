#!/bin/bash
# Sourced from the project root by run.sh and the desktop command wrapper.
load_service_config() {
  local key value
  if [[ -f private/server.env ]]; then
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
      [[ -z "$key" || "$key" == \#* ]] && continue
      case "$key" in
        LOVE_PINYIN_PORT|LOVE_PINYIN_HTTPS_PORT|LOVE_PINYIN_BIND_IP|LOVE_PINYIN_TLS_CERT|LOVE_PINYIN_TLS_KEY) ;;
        *) echo "Unknown setting in private/server.env: $key" >&2; return 1 ;;
      esac
      # No eval/source: spaces and shell metacharacters remain literal values.
      if ! declare -p "$key" >/dev/null 2>&1; then
        export "$key=${value%$'\r'}"
      fi
    done < private/server.env
  fi
  app_port="${LOVE_PINYIN_PORT:-8000}"
  https_port="${LOVE_PINYIN_HTTPS_PORT:-8443}"
  for key in app_port https_port; do
    value="${!key}"
    if [[ ! "$value" =~ ^[1-9][0-9]{0,4}$ ]] || ((value < 1024 || value > 65535)); then
      if [[ "$key" == app_port ]]; then key=LOVE_PINYIN_PORT; else key=LOVE_PINYIN_HTTPS_PORT; fi
      echo "Invalid $key: expected a port from 1024 to 65535." >&2
      return 1
    fi
  done
  lan_enabled=0
  if [[ -n "${LOVE_PINYIN_BIND_IP:-}${LOVE_PINYIN_TLS_CERT:-}${LOVE_PINYIN_TLS_KEY:-}" ]]; then
    lan_enabled=1
    if [[ "$app_port" == "$https_port" ]]; then
      echo "HTTP and HTTPS ports must be different." >&2
      return 1
    fi
  fi
}

check_service_tls() {
  [[ "$lan_enabled" == 1 ]] || return 0
  if [[ -z "${LOVE_PINYIN_BIND_IP:-}" || -z "${LOVE_PINYIN_TLS_CERT:-}" || -z "${LOVE_PINYIN_TLS_KEY:-}" ]]; then
    echo "HTTPS requires LOVE_PINYIN_BIND_IP, LOVE_PINYIN_TLS_CERT and LOVE_PINYIN_TLS_KEY in private/server.env or the environment." >&2
    return 1
  fi
  LOVE_PINYIN_PORT="$https_port" node scripts/serve-lan.mjs --check
}
