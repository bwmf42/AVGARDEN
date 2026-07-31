#!/usr/bin/env bash
# Compute AVGARDEN source identity for local/NAS version checks.
# Usage:
#   tools/build_identity.sh              # print JSON to stdout
#   tools/build_identity.sh --write      # also write BUILD_INFO.json in repo root
#   tools/build_identity.sh --write PATH # write to PATH
set -euo pipefail

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

GIT_SHA="unknown"
GIT_DIRTY=false
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    GIT_DIRTY=true
  fi
fi

# Content fingerprint of deploy-relevant sources (stable order).
# Excludes node_modules, dist, db, logs, secrets.
TREE_HASH="$(
  {
    find \
      VERSION \
      Dockerfile.server \
      Dockerfile.worker \
      docker-compose.example.yml \
      requirements.txt \
      worker.py \
      queue_api.py \
      queue_store.py \
      launcher.py \
      process_control.py \
      metadata.py \
      video_id.py \
      weekly_updater.py \
      backend \
      frontend/src \
      src \
      tools/maintenance \
      -type f \( \
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
      \) 2>/dev/null \
      | sed 's|^\./||' \
      | sort -u
  } | while IFS= read -r f; do
    [ -f "$f" ] || continue
    # path + content hash so renames also change identity
    if command -v shasum >/dev/null 2>&1; then
      h="$(shasum -a 256 "$f" | awk '{print $1}')"
    else
      h="$(sha256sum "$f" | awk '{print $1}')"
    fi
    printf '%s  %s\n' "$h" "$f"
  done | {
    if command -v shasum >/dev/null 2>&1; then
      shasum -a 256 | awk '{print substr($1,1,16)}'
    else
      sha256sum | awk '{print substr($1,1,16)}'
    fi
  }
)"

BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
HOST="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"

JSON="$(printf '%s\n' \
  "{" \
  "  \"version\": \"${VERSION}\"," \
  "  \"git_sha\": \"${GIT_SHA}\"," \
  "  \"git_dirty\": ${GIT_DIRTY}," \
  "  \"tree_hash\": \"${TREE_HASH}\"," \
  "  \"built_at\": \"${BUILT_AT}\"," \
  "  \"built_on\": \"${HOST}\"" \
  "}"
)"

echo "$JSON"
if [ "$WRITE" = "1" ]; then
  printf '%s\n' "$JSON" > "$OUT"
  echo "wrote $OUT" >&2
fi
