#!/usr/bin/env bash
# NAS-local AVGARDEN deploy (Hermes / Feishu / ssh on the NAS).
#
# Unlike deploy.sh this does NOT rsync from a Mac and does NOT need sshpass.
# Run it from the AVGARDEN tree that is already on the NAS (or the bind-mount
# visible inside hermes-agent at /opt/data/projects/AVGARDEN).
#
# Usage:
#   bash deploy_local.sh                 # rebuild+restart server+worker
#   bash deploy_local.sh server          # server only
#   bash deploy_local.sh worker          # worker only
#   bash deploy_local.sh all             # both (default)
#   bash deploy_local.sh --identity-only # only refresh BUILD_INFO into running server
#   AVGARDEN_HOT=1 bash deploy_local.sh worker   # docker-cp Python into worker, no image build
#   bash deploy_local.sh --paths backend/handlers.go worker.py
#
# Exit: 0 ok, 1 build/verify fail, 2 bad args / missing compose
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
STARTED=$SECONDS

COMPOSE_FILE="${AVGARDEN_COMPOSE:-$ROOT/docker-compose.yml}"
API_URL="${AVGARDEN_LOCAL_URL:-http://127.0.0.1:31471}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "error: missing $COMPOSE_FILE (is this the NAS AVGARDEN tree?)" >&2
  exit 2
fi

# Prefer plain docker (hermes with sock mount / docker group); fall back to sudo -n.
resolve_docker() {
  if docker info >/dev/null 2>&1; then
    echo "docker"
    return
  fi
  if sudo -n docker info >/dev/null 2>&1; then
    echo "sudo -n docker"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    echo "sudo docker"
    return
  fi
  echo "docker"
}

DOCKER_CMD="$(resolve_docker)"
dc() {
  # shellcheck disable=SC2086
  $DOCKER_CMD compose -f "$COMPOSE_FILE" "$@"
}
d() {
  # shellcheck disable=SC2086
  $DOCKER_CMD "$@"
}

reset_deploy_plan() {
  BUILD_SERVER=0
  BUILD_WORKER=0
  RECREATE_SERVER=0
  RECREATE_WORKER=0
}

mark_server_build() { BUILD_SERVER=1; RECREATE_SERVER=1; }
mark_worker_build() { BUILD_WORKER=1; RECREATE_WORKER=1; }
mark_all_build() { mark_server_build; mark_worker_build; }

classify_changed_path() {
  local path="${1#./}"
  path="${path%/}"
  case "$path" in
    ""|.) ;;
    docker-compose.yml|.dockerignore) mark_all_build ;;
    Dockerfile.server|Dockerfile.server.dockerignore|VERSION|backend|backend/*|frontend|frontend/*)
      mark_server_build ;;
    Dockerfile.worker|Dockerfile.worker.dockerignore|requirements.txt|src|src/*)
      mark_worker_build ;;
    tools/maintenance/*.py) mark_worker_build ;;
    cfg|cfg/*) RECREATE_SERVER=1; RECREATE_WORKER=1 ;;
    deploy.sh|deploy_local.sh|check_version.sh|BUILD_INFO.json|tools|tools/*|docs|docs/*|*.md|.gitignore)
      ;;
    *.py)
      if [[ "$path" == */* ]]; then mark_all_build; else mark_worker_build; fi
      ;;
    *) mark_all_build ;;
  esac
}

IDENTITY_ONLY=0
MODE_PATHS=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --identity-only) IDENTITY_ONLY=1; shift ;;
    --paths) MODE_PATHS=1; shift; break ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [ "$MODE_PATHS" = "1" ]; then
  reset_deploy_plan
  for path in "$@"; do
    classify_changed_path "$path"
  done
elif [ "${#ARGS[@]}" -eq 0 ]; then
  mark_all_build
else
  reset_deploy_plan
  case "${ARGS[0]}" in
    server) mark_server_build ;;
    worker) mark_worker_build ;;
    all) mark_all_build ;;
    *)
      echo "error: service must be server|worker|all (got: ${ARGS[0]})" >&2
      exit 2
      ;;
  esac
fi

echo "=== AVGARDEN deploy_local ==="
echo "root:    $ROOT"
echo "compose: $COMPOSE_FILE"
echo "docker:  $DOCKER_CMD"
echo "api:     $API_URL"

echo ""
echo "=== 0. BUILD_INFO identity ==="
if [ -f "$ROOT/tools/build_identity.sh" ]; then
  bash "$ROOT/tools/build_identity.sh" --write || true
else
  printf '%s\n' \
    '{' \
    '  "version": "'"$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || echo dev)"'",' \
    '  "git_sha": "unknown",' \
    '  "git_dirty": false,' \
    '  "tree_hash": "",' \
    '  "built_at": "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'",' \
    '  "built_on": "'"$(hostname -s 2>/dev/null || echo nas)"'"' \
    '}' > "$ROOT/BUILD_INFO.json"
  echo "wrote stub BUILD_INFO.json"
fi

inject_build_info() {
  if [ ! -f "$ROOT/BUILD_INFO.json" ]; then
    echo "skip BUILD_INFO inject: file missing"
    return 0
  fi
  local cid
  # Prefer compose project service id; fall back to fixed container_name
  # (Hermes may resolve a different compose project name than the host deploy).
  cid="$(dc ps -q server 2>/dev/null || true)"
  if [ -z "$cid" ]; then
    cid="$(d ps -q --filter name=^avgarden-server$ 2>/dev/null || true)"
  fi
  if [ -z "$cid" ]; then
    cid="$(d ps -q --filter name=avgarden-server 2>/dev/null | head -1 || true)"
  fi
  if [ -z "$cid" ]; then
    echo "skip BUILD_INFO inject: server not running"
    return 0
  fi
  d cp "$ROOT/BUILD_INFO.json" "$cid:/app/BUILD_INFO.json"
  echo "BUILD_INFO.json -> server:/app/BUILD_INFO.json"
}

if [ "$IDENTITY_ONLY" = "1" ]; then
  inject_build_info
  curl -fsS --max-time 5 "$API_URL/api/version" || true
  echo ""
  echo "done identity-only in $((SECONDS - STARTED))s"
  exit 0
fi

DEPLOY_HOT=0
case "${AVGARDEN_DEPLOY_MODE:-}${AVGARDEN_HOT:-}" in
  hot*|1|true|yes|on) DEPLOY_HOT=1 ;;
esac

BUILD_SERVICES=()
RECREATE_SERVICES=()
HOT_WORKER=0

if [ "$DEPLOY_HOT" = "1" ]; then
  if [ "$BUILD_SERVER" = "1" ]; then
    echo "HOT note: server changes still full-build"
    BUILD_SERVICES+=(server)
    RECREATE_SERVICES+=(server)
  fi
  if [ "$BUILD_WORKER" = "1" ] || [ "$RECREATE_WORKER" = "1" ]; then
    HOT_WORKER=1
  fi
else
  [ "$BUILD_SERVER" = "1" ] && BUILD_SERVICES+=(server)
  [ "$BUILD_WORKER" = "1" ] && BUILD_SERVICES+=(worker)
  [ "$RECREATE_SERVER" = "1" ] && RECREATE_SERVICES+=(server)
  [ "$RECREATE_WORKER" = "1" ] && RECREATE_SERVICES+=(worker)
fi

echo "plan: build=${BUILD_SERVICES[*]:-none} recreate=${RECREATE_SERVICES[*]:-none} hot_worker=$HOT_WORKER"

echo ""
echo "=== 1. docker compose build ==="
if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
  BUILD_LOG="/tmp/avgarden-local-build-$$.log"
  if dc build "${BUILD_SERVICES[@]}" >"$BUILD_LOG" 2>&1; then
    echo "build ok: ${BUILD_SERVICES[*]} ($((SECONDS - STARTED))s so far)"
    tail -n 8 "$BUILD_LOG" || true
    rm -f "$BUILD_LOG"
  else
    echo "build FAILED; log: $BUILD_LOG" >&2
    tail -n 80 "$BUILD_LOG" >&2 || true
    exit 1
  fi
else
  echo "skip build"
fi

echo ""
echo "=== 2. HOT worker python inject ==="
if [ "$DEPLOY_HOT" = "1" ] && [ "$HOT_WORKER" = "1" ]; then
  cid="$(dc ps -q worker 2>/dev/null || true)"
  if [ -z "$cid" ]; then
    echo "worker not running; full recreate worker"
    dc up -d --no-deps --build worker
  else
    for rel in \
      worker.py queue_api.py queue_store.py launcher.py heal_runner.py \
      download_source.py requirements.txt \
      src/p115_offline.py src/log_writer.py
    do
      if [ -f "$ROOT/$rel" ]; then
        dir="$(dirname "$rel")"
        if [ "$dir" != "." ]; then
          d exec "$cid" mkdir -p "/app/$dir" >/dev/null 2>&1 || true
        fi
        d cp "$ROOT/$rel" "$cid:/app/$rel"
        echo "  cp $rel"
      fi
    done
    if [ -d "$ROOT/src" ]; then
      d cp "$ROOT/src/." "$cid:/app/src/"
      echo "  cp src/."
    fi
    if [ -d "$ROOT/tools/maintenance" ]; then
      d exec "$cid" mkdir -p /app/tools/maintenance >/dev/null 2>&1 || true
      d cp "$ROOT/tools/maintenance/." "$cid:/app/tools/maintenance/"
      echo "  cp tools/maintenance/."
    fi
    d restart "$cid"
    echo "worker restarted (hot)"
  fi
else
  echo "skip HOT worker"
fi

echo ""
echo "=== 3. recreate services ==="
if [ "${#RECREATE_SERVICES[@]}" -gt 0 ]; then
  dc up -d --no-deps "${RECREATE_SERVICES[@]}"
else
  echo "skip recreate"
fi

echo ""
echo "=== 4. inject BUILD_INFO ==="
inject_build_info

echo ""
echo "=== 5. health ==="
READY=0
for _i in $(seq 1 40); do
  if curl -fsS --max-time 3 "$API_URL/api/version" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
if [ "$READY" != "1" ]; then
  echo "warn: API not ready at $API_URL" >&2
  exit 1
fi

VER_JSON="$(curl -fsS --max-time 5 "$API_URL/api/version" || true)"
printf '%s\n' "$VER_JSON" | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin)
except Exception as e:
  print("version parse fail", e); raise SystemExit(0)
print("version:", d.get("version"))
print("tree_hash:", d.get("tree_hash") or "(none)")
print("git_sha:", d.get("git_sha") or "(none)")
print("frontend:", d.get("frontend_js"))
' 2>/dev/null || printf '%s\n' "$VER_JSON"

for name in avgarden-server avgarden-worker; do
  st="$(d inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo missing)"
  echo "container $name running=$st"
done

echo ""
echo "deploy_local done in $((SECONDS - STARTED))s"
exit 0
