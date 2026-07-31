#!/usr/bin/env bash
# Compare local AVGARDEN source identity vs running NAS API (and optional NAS tree).
#
# Usage:
#   ./check_version.sh
#   AVGARDEN_URL=http://192.168.5.14:31471 ./check_version.sh
#   ./check_version.sh --nas-tree   # also fingerprint NAS source via ssh zspace
#
# Exit: 0 match, 1 mismatch, 2 cannot reach NAS API
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
LOCAL_VERSION="$(printf '%s' "$LOCAL_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["version"])')"
LOCAL_TREE="$(printf '%s' "$LOCAL_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["tree_hash"])')"
LOCAL_GIT="$(printf '%s' "$LOCAL_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["git_sha"])')"
LOCAL_DIRTY="$(printf '%s' "$LOCAL_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["git_dirty"])')"

echo "=== Local (Mac) ==="
echo "version:   $LOCAL_VERSION"
echo "tree_hash: $LOCAL_TREE"
echo "git_sha:   $LOCAL_GIT"
echo "git_dirty: $LOCAL_DIRTY"

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

print(f"version:   {api.get('version')}")
print(f"tree_hash: {api.get('tree_hash') or '(missing — redeploy to bake BUILD_INFO)'}")
print(f"git_sha:   {api.get('git_sha') or '(missing)'}")
print(f"git_dirty: {api.get('git_dirty')}")
print(f"build_time:{api.get('build_time')}")
print(f"frontend:  {api.get('frontend_js')}")

api_tree = str(api.get("tree_hash") or "").strip()
local_tree = str(local.get("tree_hash") or "").strip()
api_ver = str(api.get("version") or "").strip()
local_ver = str(local.get("version") or "").strip()

print("")
if not api_tree:
    print("RESULT: UNKNOWN — running server has no tree_hash yet")
    print("  -> deploy once so BUILD_INFO is written + docker-cp'd into server")
    sys.exit(1)

if api_tree == local_tree and api_ver == local_ver:
    if local.get("git_dirty"):
        print("RESULT: MATCH tree/version, but LOCAL git is dirty (uncommitted edits)")
        sys.exit(1)
    print("RESULT: MATCH — local source matches running NAS build")
    sys.exit(0)

print("RESULT: MISMATCH — do not assume NAS has your local edits")
if api_ver != local_ver:
    print(f"  version  local={local_ver}  nas={api_ver}")
if api_tree != local_tree:
    print(f"  tree_hash local={local_tree}  nas={api_tree}")
print("  next:")
print("    outside/Hermes edited NAS  -> pull NAS source then continue locally")
print("    local is newer             -> bash deploy.sh")
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
    echo "$NAS_TREE" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("version:", d.get("version")); print("tree_hash:", d.get("tree_hash")); print("git_sha:", d.get("git_sha")); print("git_dirty:", d.get("git_dirty"))'
    NAS_TH="$(echo "$NAS_TREE" | python3 -c 'import sys,json; print(json.load(sys.stdin)["tree_hash"])')"
    if [ "$NAS_TH" = "$LOCAL_TREE" ]; then
      echo "NAS source tree_hash matches local"
    else
      echo "NAS source tree_hash DIFFERS from local (source on disk out of sync)"
      status=1
    fi
  else
    echo "skip: cannot ssh zspace or NAS lacks tools/build_identity.sh"
  fi
fi

exit "$status"
