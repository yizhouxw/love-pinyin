#!/bin/bash
# No installation, network access, or PID-file trust in discovery and stop.
find_endpoint() {
  local port="$1" protocol="$2" pid command_line process_cwd
  endpoint_pid=""
  endpoint_host=""
  for pid in $(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u); do
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    process_cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    if [[ "$process_cwd" != "$PWD" || ! "$command_line" =~ (^|[[:space:]/])uvicorn[[:space:]]server.main:app[[:space:]] || " $command_line " != *" --port $port "* ]]; then
      echo "Port $port is occupied by another service; refusing to manage it." >&2
      return 1
    fi
    if [[ "$protocol" == http ]]; then
      if [[ " $command_line " != *" --host 127.0.0.1 "* || " $command_line " == *" --ssl-"* ]]; then
        echo "Port $port is not the expected local HTTP service; refusing to manage it." >&2
        return 1
      fi
      endpoint_host=127.0.0.1
    else
      if [[ " $command_line " != *" --ssl-certfile "* || " $command_line " != *" --ssl-keyfile "* || ! "$command_line" =~ --host[[:space:]]([^[:space:]]+) ]]; then
        echo "Port $port is not the expected HTTPS service; refusing to manage it." >&2
        return 1
      fi
      endpoint_host="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$endpoint_pid" ]]; then
      echo "Multiple listeners use port $port; refusing to manage them." >&2
      return 1
    fi
    endpoint_pid="$pid"
  done
}

discover_services() {
  find_endpoint "$app_port" http || return 1
  http_pid="$endpoint_pid"
  https_pid=""
  https_host="${LOVE_PINYIN_BIND_IP:-unconfigured}"
  if [[ "$lan_enabled" == 1 ]]; then
    find_endpoint "$https_port" https || return 1
    https_pid="$endpoint_pid"
    [[ -z "$endpoint_host" ]] || https_host="$endpoint_host"
  fi
}

all_services_running() {
  [[ -n "$http_pid" ]] && { [[ "$lan_enabled" == 0 ]] || [[ -n "$https_pid" ]]; }
}

show_service_status() {
  discover_services || return 1
  if [[ -n "$http_pid" ]]; then
    echo "HTTP is running (PID $http_pid): http://127.0.0.1:$app_port"
  else
    echo "HTTP is not running: http://127.0.0.1:$app_port"
  fi
  if [[ "$lan_enabled" == 1 ]]; then
    if [[ -n "$https_pid" ]]; then
      echo "HTTPS is running (PID $https_pid): https://$https_host:$https_port"
    else
      echo "HTTPS is not running: https://$https_host:$https_port"
    fi
  else
    echo "HTTPS is not configured. Set LOVE_PINYIN_BIND_IP, LOVE_PINYIN_TLS_CERT and LOVE_PINYIN_TLS_KEY in private/server.env."
  fi
  if [[ -n "$https_pid" && "$https_host" != "${LOVE_PINYIN_BIND_IP:-}" ]]; then
    echo "HTTPS is running on a different address than configured; use restart to apply the configuration."
    return 3
  fi
  all_services_running && return 0
  return 3
}

process_alive() {
  kill -0 "$1" 2>/dev/null && [[ "$(ps -p "$1" -o stat= 2>/dev/null || true)" != *Z* ]]
}

stop_services() {
  # Check BOTH endpoints before sending any signals.
  discover_services || return 1
  local pid attempt pending
  if [[ -z "$http_pid$https_pid" ]]; then
    echo "Love Pinyin is not running."
    return 0
  fi
  for pid in $http_pid $https_pid; do
    kill -TERM "$pid" 2>/dev/null || { process_alive "$pid" && return 1; }
  done
  for ((attempt=0; attempt<100; attempt++)); do
    pending=0
    for pid in $http_pid $https_pid; do
      if process_alive "$pid"; then pending=1; fi
    done
    if [[ "$pending" == 0 ]]; then
      echo "Love Pinyin stopped (HTTP $app_port, HTTPS $https_port)."
      return 0
    fi
    sleep 0.1
  done
  echo "Service has not exited after 10 seconds; restart cancelled." >&2
  return 1
}

cleanup_started_services() {
  local pid attempt pending
  for pid in ${started_pids[@]+"${started_pids[@]}"}; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for ((attempt=0; attempt<100; attempt++)); do
    pending=0
    for pid in ${started_pids[@]+"${started_pids[@]}"}; do
      if process_alive "$pid"; then pending=1; fi
    done
    [[ "$pending" == 1 ]] || return 0
    sleep 0.1
  done
  echo "A started service did not exit after 10 seconds; no forced kill was sent." >&2
}

start_services() {
  discover_services || return 1
  # Another invocation may have filled the missing endpoint during preflight.
  if all_services_running; then
    show_service_status
    echo "Love Pinyin is ready."
    return 0
  fi
  local attempt pid
  started_pids=()
  trap 'cleanup_started_services' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [[ -z "$http_pid" ]]; then
    .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port "$app_port" --no-access-log --no-proxy-headers &
    started_pids+=("$!")
  fi
  if [[ "$lan_enabled" == 1 && -z "$https_pid" ]]; then
    .venv/bin/uvicorn server.main:app --host "$LOVE_PINYIN_BIND_IP" --port "$https_port" \
      --ssl-certfile "$LOVE_PINYIN_TLS_CERT" --ssl-keyfile "$LOVE_PINYIN_TLS_KEY" \
      --no-access-log --no-proxy-headers &
    started_pids+=("$!")
  fi
  for ((attempt=0; attempt<150; attempt++)); do
    for pid in ${started_pids[@]+"${started_pids[@]}"}; do
      if ! process_alive "$pid"; then
        echo "A Love Pinyin service exited before startup completed." >&2
        return 1
      fi
    done
    discover_services || return 1
    if all_services_running; then break; fi
    sleep 0.1
  done
  if ! all_services_running; then
    echo "Love Pinyin did not become ready within the startup timeout." >&2
    return 1
  fi
  show_service_status
  echo "Love Pinyin is ready."
  echo "Ctrl+C stops the services started by this command."
  while true; do
    for pid in ${started_pids[@]+"${started_pids[@]}"}; do
      if ! process_alive "$pid"; then
        echo "A Love Pinyin service exited; stopping the other services started by this command." >&2
        return 1
      fi
    done
    sleep 0.5
  done
}
