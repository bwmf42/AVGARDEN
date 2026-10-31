#!/usr/bin/env bash
# Compute AVGARDEN source identity for local/NAS version checks.
# Usage:
#   tools/build_identity.sh              # print JSON to stdout
#   tools/build_identity.sh --write      # also write BUILD_INFO.json in repo root
#   tools/build_identity.sh --write PATH # write to PATH
#
# Fields:
#   tree_hash_server  — Go/Vue/server image inputs
#   tree_hash_worker  — Python/worker image inputs
#   tree_hash         — combined (server|worker) for backward compatibility
#   git_dirty         — true only if dirty paths intersect fingerprint set
set -euo pipefail
# Fixed collation: sort order (and so tree_hash) must not depend on who runs this.
export LC_ALL=C

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WRITE=0
OUT="$ROOT/BUILD_INFO.json"
if [ "${1:-}" = "--write" ]; then
  WRITE=1
  if [ -n "${2:-}" ]; then
    OUT="$2"
  fi
fi

VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || echo dev)"

# --- list deploy-relevant files for a role (server|worker|all) ---
list_identity_files() {
  local role="$1"
  local roots=()
  case "$role" in
    server)
      roots=(
        VERSION
        Dockerfile.server
        backend
        frontend/src
      )
      ;;
    worker)
      roots=(
        Dockerfile.worker
        requirements.txt
        worker.py
        queue_api.py
        queue_store.py
        launcher.py
        process_control.py
        metadata.py
        video_id.py
        weekly_updater.py
        run_scrape_followups.py
        unwatched_chinese_refill.py
        download_source.py
        heal_runner.py
        translate_settings.py
        title_translate_job.py
        src
        tools/maintenance
      )
      ;;
    all)
      roots=(
        VERSION
        Dockerfile.server
        Dockerfile.worker
        docker-compose.example.yml
        requirements.txt
        worker.py
        queue_api.py
        queue_store.py
        launcher.py
        process_control.py
        metadata.py
        video_id.py
        weekly_updater.py
        run_scrape_followups.py
        unwatched_chinese_refill.py
        download_source.py
        heal_runner.py
        translate_settings.py
        title_translate_job.py
        backend
        frontend/src
        src
        tools/maintenance
      )
      ;;
    *)
      echo "unknown role: $role" >&2
      return 1
      ;;
  esac

  # Only existing roots (missing paths are skipped by find)
  local existing=()
  local r
  for r in "${roots[@]}"; do
    if [ -e "$r" ]; then
      existing+=("$r")
    fi
  done
  if [ "${#existing[@]}" -eq 0 ]; then
    return 0
  fi

  # Unreadable paths must fail loudly: a silently partial hash is worse than none.
  local find_out find_err find_rc=0
  find_out="$(mktemp "${TMPDIR:-/tmp}/avgarden-find.XXXXXX")"
  find_err="$(mktemp "${TMPDIR:-/tmp}/avgarden-finderr.XXXXXX")"
  find "${existing[@]}" -type f \( \
      -name 'VERSION' -o \
      -name 'Dockerfile*' -o \
      -name 'docker-compose*.yml' -o \
      -name 'requirements.txt' -o \
      -name '*.go' -o \
      -name '*.vue' -o \
      -name '*.js' -o \
      -name '*.css' -o \
      -name '*.html' -o \
      -name '*.py' -o \
      -name '*.json' \
    \) >"$find_out" 2>"$find_err" || find_rc=$?
  if [ "$find_rc" -ne 0 ] || [ -s "$find_err" ]; then
    echo "build_identity: cannot read some identity paths under $ROOT (find exit $find_rc):" >&2
    sed 's/^/  /' "$find_err" >&2
    echo "build_identity: run as a user that can read the source tree, or compute inside the container (see docs/operations.md)." >&2
    rm -f "$find_out" "$find_err"
    exit 1
  fi
  sed 's|^\./||' "$find_out" | sort -u
  rm -f "$find_out" "$find_err"
}

hash_file_list() {
  # stdin: paths one per line -> 16-char hex of content+path fingerprint
  local h
  {
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      [ -f "$f" ] || continue
      if [ ! -r "$f" ]; then
        echo "build_identity: unreadable file: $ROOT/$f" >&2
        exit 1
      fi
      if command -v shasum >/dev/null 2>&1; then
        h="$(shasum -a 256 "$f" | awk '{print $1}')"
      else
        h="$(sha256sum "$f" | awk '{print $1}')"
      fi
      printf '%s  %s\n' "$h" "$f"
    done
  } | {
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 | awk '{print substr($1,1,16)}'
    else
      sha256sum | awk '{print substr($1,1,16)}'
    fi
  }
}

TREE_HASH_SERVER="$(list_identity_files server | hash_file_list)"
TREE_HASH_WORKER="$(list_identity_files worker | hash_file_list)"
# Combined: stable function of both sides (changes if either side changes)
TREE_HASH="$(
  printf 'server:%s\nworker:%s\n' "$TREE_HASH_SERVER" "$TREE_HASH_WORKER" | {
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 | awk '{print substr($1,1,16)}'
    else
      sha256sum | awk '{print substr($1,1,16)}'
    fi
  }
)"

GIT_SHA="unknown"
GIT_DIRTY=false
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  # Only dirty if changed/untracked paths intersect fingerprint set (all roles)
  IDENTITY_SET="$(mktemp "${TMPDIR:-/tmp}/avgarden-idset.XXXXXX")"
  list_identity_files all > "$IDENTITY_SET"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    # porcelain: XY PATH or XY ORIG -> PATH / renames
    path="${line:3}"
    path="${path#\"}"
    path="${path%\"}"
    case "$path" in
      *" -> "*) path="${path##* -> }" ;;
    esac
    path="${path#./}"
    if [ -n "$path" ] && grep -Fxq "$path" "$IDENTITY_SET" 2>/dev/null; then
      GIT_DIRTY=true
      break
    fi
    # directory dirty: any identity file under that prefix
    if [ -n "$path" ] && grep -E "^${path%/}/" "$IDENTITY_SET" >/dev/null 2>&1; then
      GIT_DIRTY=true
      break
    fi
  done < <(git -C "$ROOT" status --porcelain 2>/dev/null || true)
  rm -f "$IDENTITY_SET"
fi

BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
HOST="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"

# JSON (booleans unquoted)
JSON="$(printf '%s\n' \
  "{" \
  "  \"version\": \"${VERSION}\"," \
  "  \"git_sha\": \"${GIT_SHA}\"," \
  "  \"git_dirty\": ${GIT_DIRTY}," \
  "  \"tree_hash\": \"${TREE_HASH}\"," \
  "  \"tree_hash_server\": \"${TREE_HASH_SERVER}\"," \
  "  \"tree_hash_worker\": \"${TREE_HASH_WORKER}\"," \
  "  \"built_at\": \"${BUILT_AT}\"," \
  "  \"built_on\": \"${HOST}\"" \
  "}"
)"

echo "$JSON"
if [ "$WRITE" = "1" ]; then
  printf '%s\n' "$JSON" > "$OUT"
  echo "wrote $OUT" >&2
fi
