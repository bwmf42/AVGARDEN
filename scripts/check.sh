#!/bin/bash
# Local verification and optional read-only NAS checks; compatible with Bash 3.2.
set -u

usage() {
  cat <<'EOF'
Usage: scripts/check.sh [--layer 1|2|all] [--quick]
  --layer 1  第 1 层：本地 Python 语法/单测、Go vet/test、前端构建（默认）
  --layer 2  第 2 层：NAS 版本、JSON 接口、容器状态（只读）
  --layer all 运行第 1、2 层
  --quick    只运行第 1 层的 Python 语法检查和 unittest，覆盖 --layer
  第 3 层需人工或浏览器验收，脚本不覆盖页面验收。
Exit: 0 = 全部 PASS 或 SKIP；1 = 有 FAIL 或参数错误；2 = 第 2 层整体连不上 NAS
子命令完整输出保留在临时日志；FAIL 额外显示最后 20 行。
EOF
}

layer=1
quick=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --quick) quick=1; shift ;;
    --layer)
      case "${2:-}" in
        1|2|all) layer="$2"; shift 2 ;;
        *) usage >&2; exit 1 ;;
      esac ;;
    *) usage >&2; exit 1 ;;
  esac
done
[ "$quick" -eq 0 ] || layer=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/avgarden-check.XXXXXX")" || exit 1
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/private/tmp/av-garden-pycache}"
export GOCACHE="${GOCACHE:-/private/tmp/av-garden-gocache}"
# Verification must not fetch modules or toolchains implicitly.
export GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local
passed=0 failed=0 skipped=0 sequence=0
attempted=0 reachable=0
LAST_STATUS=0

record() {
  local status="$1" label="$2" reason="$3" log="$4"
  case "$status" in
    PASS) passed=$((passed + 1)) ;;
    FAIL) failed=$((failed + 1)) ;;
    SKIP) skipped=$((skipped + 1)); printf '%s\n' "$reason" > "$log" ;;
  esac
  printf '%s %s: %s [log: %s]\n' "$status" "$label" "$reason" "$log"
  [ "$status" != FAIL ] || tail -n 20 "$log"
}

skip_check() {
  sequence=$((sequence + 1))
  record SKIP "$1" "$2" "$LOG_DIR/$sequence.log"
}

run_check() {
  local label="$1" reason="$2" log
  shift 2
  sequence=$((sequence + 1))
  log="$LOG_DIR/$sequence.log"
  ( "$@" ) > "$log" 2>&1
  LAST_STATUS=$?
  if [ "$LAST_STATUS" -eq 0 ]; then
    record PASS "$label" "$reason" "$log"
  else
    record FAIL "$label" "$reason (exit=$LAST_STATUS)" "$log"
  fi
}

python_syntax() {
  python3 - <<'PY'
import os, subprocess, sys
excluded = {"frontend", "node_modules", "vendor", "third_party", "third-party",
            "thirdparty", "external", "deps", ".venv", "venv", "site-packages"}
tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "*.py"])
paths = [os.fsdecode(p) for p in tracked.split(b"\0") if p]
paths = [p for p in paths if not excluded.intersection(p.split("/")[:-1])]
print("Tracked Python files:", len(paths), flush=True)
if paths:
    sys.exit(subprocess.call([sys.executable, "-m", "py_compile", *paths]))
PY
}

go_checks() { cd backend && go vet ./... && go test ./...; }
frontend_build() { cd frontend && npm run build; }

if [ "$layer" = 1 ] || [ "$layer" = all ]; then
  printf '\n=== 第 1 层：本地静态与单测 ===\n'
  if ! command -v python3 >/dev/null 2>&1; then
    skip_check 'Python syntax' '缺少 python3'
    skip_check 'Python unittest' '缺少 python3'
  else
    if command -v git >/dev/null 2>&1; then
      run_check 'Python syntax' 'git 跟踪的 Python 语法检查' python_syntax
    else
      skip_check 'Python syntax' '缺少 git，无法列出跟踪文件'
    fi
    run_check 'Python unittest' '根目录 test_*.py 自动发现' python3 -m unittest discover -s . -p 'test_*.py'
  fi
  if [ "$quick" -eq 0 ]; then
    if command -v go >/dev/null 2>&1; then
      run_check 'Go vet/test' 'go vet ./... && go test ./...' go_checks
    else
      skip_check 'Go vet/test' '缺少 go'
    fi
    if ! command -v npm >/dev/null 2>&1 || ! command -v node >/dev/null 2>&1; then
      skip_check 'Frontend build' '缺少 node 或 npm'
    elif [ ! -d frontend/node_modules ]; then
      skip_check 'Frontend build' '缺少 frontend/node_modules；不自动安装依赖'
    else
      run_check 'Frontend build' 'npm run build' frontend_build
    fi
  fi
fi

# Read defaults from check_version.sh without sourcing/executing its checks.
nas_config() {
  python3 - "$ROOT/check_version.sh" "$LOG_DIR/config" <<'PY'
import os, pathlib, re, sys, urllib.parse
source = pathlib.Path(sys.argv[1]).read_text()
url = re.search(r'^URL="\$\{AVGARDEN_URL:-([^}]+)\}"$', source, re.M)
host = re.search(r'\bssh\s+(?:-o\s+\S+\s+)+([\w.@-]+)\s', source.replace('\\\n', ' '))
if not url or not host:
    sys.exit("无法读取 check_version.sh 的 URL/SSH 配置；请同步解析规则")
base = os.environ.get("AVGARDEN_URL") or url[1]
parts = urllib.parse.urlsplit(base)
if (parts.scheme not in ("http", "https") or not parts.hostname or
        parts.username is not None or parts.password is not None or
        parts.query or parts.fragment or "\n" in base or "\r" in base):
    sys.exit("AVGARDEN_URL 必须是无凭证、查询参数或片段的 HTTP(S) 地址")
pathlib.Path(sys.argv[2]).write_text(base.rstrip('/') + '\n' + host[1] + '\n')
PY
}

api_check() {
  local endpoint="$1" code rc
  code="$(curl -sS --connect-timeout 4 --max-time 8 -o "$LOG_DIR/$endpoint.json" \
    -w '%{http_code}' "$NAS_URL/api/$endpoint")"
  rc=$?
  [ "$rc" -eq 0 ] || return 2
  # Keep response bodies out of terminal failure tails (they may contain data).
  printf 'HTTP %s\n' "$code"
  [ "$code" = 200 ] || return 1
  python3 - "$LOG_DIR/$endpoint.json" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        json.load(f, parse_constant=lambda value: sys.exit("Invalid JSON constant"))
except (ValueError, OSError):
    sys.exit("Invalid JSON response (body retained in temporary file)")
print("Valid JSON")
PY
}

container_check() {
  local state rc
  state="$(ssh -o ConnectTimeout=6 -o BatchMode=yes -o StrictHostKeyChecking=yes "$NAS_HOST" \
    "sudo -n docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.Status}}' $1")"
  rc=$?
  [ "$rc" -eq 0 ] || return "$rc"
  printf '%s\n' "$state"
  [ "$state" = 'healthy|running' ] || [ "$state" = '|running' ]
}

if [ "$layer" = 2 ] || [ "$layer" = all ]; then
  printf '\n=== 第 2 层：NAS 运行时（只读） ===\n'
  if ! command -v python3 >/dev/null 2>&1; then
    skip_check 'NAS checks' '缺少 python3，无法读取共享配置和验证 JSON'
  elif ! nas_config > "$LOG_DIR/config.log" 2>&1; then
    record FAIL 'NAS configuration' '无法安全读取共享配置' "$LOG_DIR/config.log"
  else
    { IFS= read -r NAS_URL; IFS= read -r NAS_HOST; } < "$LOG_DIR/config"
    export AVGARDEN_URL="$NAS_URL"
    if ! command -v curl >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
      skip_check 'NAS version' '缺少 curl 或 git'
    else
      run_check 'NAS version' '版本一致=0；不一致=1；API 不可达=2' ./check_version.sh
      attempted=$((attempted + 1))
      case "$LAST_STATUS" in 0|1) reachable=$((reachable + 1)) ;; esac
    fi
    for endpoint in version queue-status; do
      if command -v curl >/dev/null 2>&1; then
        run_check "API /api/$endpoint" '要求 HTTP 200 且合法 JSON' api_check "$endpoint"
        attempted=$((attempted + 1))
        [ "$LAST_STATUS" -eq 2 ] || reachable=$((reachable + 1))
      else
        skip_check "API /api/$endpoint" '缺少 curl'
      fi
    done
    for container in avgarden-server avgarden-worker; do
      if command -v ssh >/dev/null 2>&1; then
        run_check "Container $container" '要求 running；有 healthcheck 时要求 healthy' container_check "$container"
        attempted=$((attempted + 1))
        [ "$LAST_STATUS" -eq 255 ] || reachable=$((reachable + 1))
      else
        skip_check "Container $container" '缺少 ssh'
      fi
    done
  fi
fi

printf '\n第 3 层需人工或浏览器验收\n'
result=0
[ "$failed" -eq 0 ] || result=1
if [ "$attempted" -gt 0 ] && [ "$reachable" -eq 0 ]; then result=2; fi
printf 'SUMMARY PASS=%s FAIL=%s SKIP=%s exit=%s\n' "$passed" "$failed" "$skipped" "$result"
exit "$result"
