#!/bin/bash
set -euo pipefail
project="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project"
action="${1:-start}"
[[ $# -le 1 ]] || { echo 'Usage: lovepinyin [start|status|stop|restart]' >&2; exit 1; }
case "$action" in
  status|stop|top) exec "$project/run.sh" "$action" ;;
  start|restart) ;;
  *) echo 'Usage: lovepinyin [start|status|stop|restart]' >&2; exit 1 ;;
esac
source "$project/scripts/service-config.sh"
load_service_config
url="http://127.0.0.1:$app_port"
if [[ "$action" == start ]]; then
  if "$project/run.sh" status; then
    :
  else
    result=$?
    [[ $result -eq 3 ]] || exit "$result"
  fi
fi
launcher_python="$project/.venv/bin/python"
if [[ ! -x "$launcher_python" ]]; then
  echo "正在准备启动所需的本地运行环境…"
  "$project/run.sh" --prepare-only
fi
[[ -x "$launcher_python" ]] || { echo 'Local Python is unavailable after preparation.' >&2; exit 1; }
log_dir="${LOVE_PINYIN_LOG_DIR:-$HOME/Library/Logs/LovePinyin}"
mkdir -p "$log_dir"
# Each launch gets a fresh log so restart cannot accept an earlier ready marker.
log_file="$(mktemp "$log_dir/start-$app_port.XXXXXX")"
# A separate session survives terminal closure and callers cleaning up their
# process group. nohup alone leaves the service in the launcher's session.
launcher_pid="$("$launcher_python" - "$project/run.sh" "$action" "$log_file" <<'PYLAUNCH'
import subprocess
import sys

with open(sys.argv[3], "ab", buffering=0) as log:
    process = subprocess.Popen(
        [sys.argv[1], sys.argv[2]],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
print(process.pid)
PYLAUNCH
)"
echo "正在启动爱拼音，全部入口就绪后自动打开浏览器。"
echo "启动日志：$log_file"
launch_is_ready() {
  grep -Fqx 'Love Pinyin is ready.' "$log_file" && "$project/run.sh" status >/dev/null 2>&1 && curl --noproxy '*' --fail --silent --max-time 2 "$url/api/v1/health" >/dev/null 2>&1
}
ready=0
for ((attempt=0; attempt<900; attempt++)); do
  # During restart, status can still describe the old processes. The launch's
  # ready marker confirms that preflight and replacement have both completed.
  if launch_is_ready; then
    ready=1
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    # The all-running fast path may finish between the ready check and kill.
    if launch_is_ready; then
      ready=1
      break
    fi
    echo "启动进程已退出，请检查日志：$log_file" >&2
    tail -n 30 "$log_file" >&2
    exit 1
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "仍在准备，请查看日志：$log_file；稍后再次运行 lovepinyin。" >&2
  exit 1
fi
open "$url"
"$project/run.sh" status
echo "爱拼音已启动（后台运行；lovepinyin stop 停止全部入口）。"
