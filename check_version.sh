#!/usr/bin/env bash
# Compare local AVGARDEN source identity vs running NAS API (and optional NAS tree).
#
# Usage:
#   ./check_version.sh
#   AVGARDEN_URL=http://192.168.5.14:31471 ./check_version.sh
#   ./check_version.sh --nas-tree   # also fingerprint NAS source via ssh zspace
#
# Exit: 0 full match (or server+worker match with dirty warning only if not dirty),
#       1 mismatch / partial / dirty-on-identity-paths,
#       2 cannot reach NAS API
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

URL="${AVGARDEN_URL:-http://192.168.5.14:31471}"
CHECK_NAS_TREE=0
[ "${1:-}" = "--nas-tree" ] && CHECK_NAS_TREE=1

IDENTITY_SCRIPT="$ROOT/tools/build_identity.sh"
if [ ! -x "$IDENTITY_SCRIPT" ]; then
  chmod +x "$IDENTITY_SCRIPT" 2>/dev/null || true
fi

LOCAL_JSON="$("$IDENTITY_SCRIPT")"

py_field() {
  local key="$1"
  printf '%s' "$LOCAL_JSON" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get(sys.argv[1],""))' "$key"
}

LOCAL_VERSION="$(py_field version)"
LOCAL_TREE="$(py_field tree_hash)"
LOCAL_SERVER="$(py_field tree_hash_server)"
LOCAL_WORKER="$(py_field tree_hash_worker)"
LOCAL_GIT="$(py_field git_sha)"
LOCAL_DIRTY="$(py_field git_dirty)"

echo "=== Local (Mac) ==="
echo "version:          $LOCAL_VERSION"
echo "tree_hash:        $LOCAL_TREE"
echo "tree_hash_server: $LOCAL_SERVER"
echo "tree_hash_worker: $LOCAL_WORKER"
echo "git_sha:          $LOCAL_GIT"
echo "git_dirty:        $LOCAL_DIRTY  (identity paths only)"

echo ""
echo "=== NAS running API ($URL/api/version) ==="
API_JSON=""
if ! API_JSON="$(curl -fsS --connect-timeout 4 --max-time 8 "$URL/api/version" 2>/dev/null)"; then
  echo "UNREACHABLE: cannot fetch $URL/api/version"
  echo ""
  echo "RESULT: cannot verify (NAS API down or not on LAN)"
  exit 2
fi

TMPDIR_CV="${TMPDIR:-/tmp}"
LOCAL_FILE="$(mktemp "$TMPDIR_CV/avgarden-local.XXXXXX")"
API_FILE="$(mktemp "$TMPDIR_CV/avgarden-api.XXXXXX")"
cleanup() { rm -f "$LOCAL_FILE" "$API_FILE"; }
trap cleanup EXIT
printf '%s\n' "$LOCAL_JSON" > "$LOCAL_FILE"
printf '%s\n' "$API_JSON" > "$API_FILE"

set +e
python3 - "$LOCAL_FILE" "$API_FILE" <<'PY'
import json, sys

with open(sys.argv[1], encoding="utf-8") as f:
    local = json.load(f)
with open(sys.argv[2], encoding="utf-8") as f:
    api = json.load(f)

def g(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""

api_ver = g(api, "version")
local_ver = g(local, "version")
api_tree = g(api, "tree_hash")
local_tree = g(local, "tree_hash")
api_server = g(api, "tree_hash_server")
local_server = g(local, "tree_hash_server")
api_worker = g(api, "tree_hash_worker")
local_worker = g(local, "tree_hash_worker")

print(f"version:          {api_ver or '(none)'}")
print(f"tree_hash:        {api_tree or '(missing)'}")
print(f"tree_hash_server: {api_server or '(missing — redeploy identity)'}")
print(f"tree_hash_worker: {api_worker or '(missing — redeploy identity)'}")
print(f"git_sha:          {g(api, 'git_sha') or '(missing)'}")
print(f"git_dirty:        {api.get('git_dirty')}")
print(f"build_time:       {api.get('build_time')}")
print(f"frontend:         {api.get('frontend_js')}")
print(f"built_at:         {api.get('built_at')}")
print(f"built_on:         {api.get('built_on')}")

print("")

# Prefer per-side when API has split hashes; else fall back to combined tree_hash.
has_split = bool(api_server or api_worker)
if not api_tree and not has_split:
    print("RESULT: UNKNOWN — running server has no tree_hash yet")
    print("  -> deploy once so BUILD_INFO is written + docker-cp'd into server")
    sys.exit(1)

server_ok = None
worker_ok = None
if has_split:
    if api_server and local_server:
        server_ok = api_server == local_server
    if api_worker and local_worker:
        worker_ok = api_worker == local_worker
    # If API missing one side but has other, treat missing as unknown
    if not api_server:
        server_ok = None
    if not api_worker:
        worker_ok = None
else:
    # Legacy API: only combined hash
    combined = api_tree == local_tree
    server_ok = combined
    worker_ok = combined

ver_ok = (not local_ver and not api_ver) or (api_ver == local_ver)

def side(name, ok):
    if ok is True:
        return f"{name}=MATCH"
    if ok is False:
        return f"{name}=MISMATCH"
    return f"{name}=UNKNOWN"

print(f"sides: {side('server', server_ok)}  {side('worker', worker_ok)}  version={'MATCH' if ver_ok else 'MISMATCH'}")

if server_ok is False and local_server and api_server:
    print(f"  server  local={local_server}  nas={api_server}")
if worker_ok is False and local_worker and api_worker:
    print(f"  worker  local={local_worker}  nas={api_worker}")
if not has_split and api_tree != local_tree:
    print(f"  tree_hash local={local_tree}  nas={api_tree}")
if not ver_ok:
    print(f"  version  local={local_ver}  nas={api_ver}")

dirty = bool(local.get("git_dirty"))

if server_ok is True and worker_ok is True and ver_ok:
    if dirty:
        print("RESULT: MATCH server+worker, but LOCAL identity-path git is dirty")
        print("  (uncommitted changes under fingerprint paths — deploy before relying on NAS)")
        sys.exit(1)
    print("RESULT: MATCH — local source matches running NAS build (server+worker)")
    sys.exit(0)

if server_ok is True and worker_ok is False:
    print("RESULT: SERVER_MATCH / WORKER_MISMATCH")
    print("  next: AVGARDEN_HOT=1 bash deploy_local.sh worker   # or Mac HOT deploy")
    sys.exit(1)

if server_ok is False and worker_ok is True:
    print("RESULT: SERVER_MISMATCH / WORKER_MATCH")
    print("  next: bash deploy.sh / deploy_local.sh server")
    sys.exit(1)

if server_ok is False and worker_ok is False:
    print("RESULT: BOTH_MISMATCH — do not assume NAS has your local edits")
    print("  next:")
    print("    outside/Hermes edited NAS  -> pull NAS source then continue locally")
    print("    local is newer             -> bash deploy.sh  (or deploy_local on NAS)")
    sys.exit(1)

# Partial unknown (e.g. old API with only combined that matched one interpretation)
if server_ok is True and worker_ok is None:
    print("RESULT: SERVER_MATCH / WORKER_UNKNOWN (API lacks tree_hash_worker — redeploy identity)")
    sys.exit(1)
if worker_ok is True and server_ok is None:
    print("RESULT: WORKER_MATCH / SERVER_UNKNOWN (API lacks tree_hash_server — redeploy identity)")
    sys.exit(1)

print("RESULT: PARTIAL/UNKNOWN — redeploy once to refresh BUILD_INFO with split hashes")
sys.exit(1)
PY
status=$?
set -e

if [ "$CHECK_NAS_TREE" = "1" ]; then
  echo ""
  echo "=== NAS source tree (via ssh zspace) ==="
  NAS_DIR="${AVGARDEN_NAS_DIR:-/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN}"
  if NAS_TREE="$(ssh -o ConnectTimeout=6 -o BatchMode=yes zspace \
      "cd '$NAS_DIR' && bash tools/build_identity.sh 2>/dev/null" 2>/dev/null)"; then
    echo "$NAS_TREE" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("version:", d.get("version")); print("tree_hash:", d.get("tree_hash")); print("tree_hash_server:", d.get("tree_hash_server")); print("tree_hash_worker:", d.get("tree_hash_worker")); print("git_sha:", d.get("git_sha")); print("git_dirty:", d.get("git_dirty"))'
    NAS_S="$(echo "$NAS_TREE" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tree_hash_server") or "")')"
    NAS_W="$(echo "$NAS_TREE" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("tree_hash_worker") or "")')"
    if [ -n "$NAS_S" ] && [ "$NAS_S" = "$LOCAL_SERVER" ]; then
      echo "NAS disk server hash matches local"
    else
      echo "NAS disk server hash DIFFERS from local (or missing)"
      status=1
    fi
    if [ -n "$NAS_W" ] && [ "$NAS_W" = "$LOCAL_WORKER" ]; then
      echo "NAS disk worker hash matches local"
    else
      echo "NAS disk worker hash DIFFERS from local (or missing)"
      status=1
    fi
  else
    echo "skip: cannot ssh zspace or NAS lacks tools/build_identity.sh"
  fi
fi

exit "$status"
