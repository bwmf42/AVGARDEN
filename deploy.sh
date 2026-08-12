#!/bin/bash
set -eo pipefail

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_STARTED=$SECONDS

reset_deploy_plan() {
    BUILD_SERVER=0
    BUILD_WORKER=0
    RECREATE_SERVER=0
    RECREATE_WORKER=0
    UNKNOWN_PATHS=()
}

mark_server_build() {
    BUILD_SERVER=1
    RECREATE_SERVER=1
}

mark_worker_build() {
    BUILD_WORKER=1
    RECREATE_WORKER=1
}

mark_all_build() {
    mark_server_build
    mark_worker_build
}

classify_changed_path() {
    local path="${1#./}"
    path="${path%/}"
    case "$path" in
        ""|.)
            ;;
        docker-compose.yml|.dockerignore)
            mark_all_build
            ;;
        Dockerfile.server|Dockerfile.server.dockerignore|VERSION|backend|backend/*|frontend|frontend/*)
            mark_server_build
            ;;
        Dockerfile.worker|Dockerfile.worker.dockerignore|requirements.txt|src|src/*)
            mark_worker_build
            ;;
        tools/maintenance/storage_cleanup.py|tools/maintenance/weekly_cache_maintenance.py|tools/maintenance/weekly_retention_maintenance.py)
            mark_worker_build
            ;;
        cfg/configs.json.example)
            ;;
        cfg|cfg/*)
            RECREATE_SERVER=1
            RECREATE_WORKER=1
            ;;
        deploy.sh|docker-compose.example.yml|.env.example|.gitignore|AGENTS.md|CLAUDE.md|CHANGELOG.md|README.md|INSTALL.md|LICENSE|NOTICE|docs|docs/*|.github|.github/*|tools|tools/*|check_version.sh|BUILD_INFO.json)
            # BUILD_INFO is regenerated every deploy; identity is docker-cp'd into
            # the running server without forcing an image rebuild.
            ;;
        *.py)
            if [[ "$path" == */* ]]; then
                UNKNOWN_PATHS+=("$path")
                mark_all_build
            else
                mark_worker_build
            fi
            ;;
        *)
            UNKNOWN_PATHS+=("$path")
            mark_all_build
            ;;
    esac
}

print_deploy_plan() {
    local builds=()
    local recreates=()
    [ "$BUILD_SERVER" = "1" ] && builds+=(server)
    [ "$BUILD_WORKER" = "1" ] && builds+=(worker)
    [ "$RECREATE_SERVER" = "1" ] && recreates+=(server)
    [ "$RECREATE_WORKER" = "1" ] && recreates+=(worker)
    echo "build=${builds[*]:-none}"
    echo "recreate=${recreates[*]:-none}"
    if [ "${#UNKNOWN_PATHS[@]}" -gt 0 ]; then
        echo "unknown=${UNKNOWN_PATHS[*]}"
    fi
}

reset_deploy_plan
if [ "${1:-}" = "--plan-paths" ]; then
    shift
    for path in "$@"; do
        classify_changed_path "$path"
    done
    print_deploy_plan
    exit 0
fi

NAS_USER="${AVGARDEN_USER:-13049108160}"
NAS_IP="${AVGARDEN_IP:-192.168.5.14}"
NAS_PORT="${AVGARDEN_PORT:-10000}"
NAS_PASS="${AVGARDEN_PASS:?错误: 需要设置 AVGARDEN_PASS 环境变量}"
NAS_SSH_HOST="${AVGARDEN_SSH_HOST:-}"
NAS_DIR="/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN"
NAS_STAGE="/tmp/avgarden-deploy-${NAS_USER}"
DEPLOY_ID="$(date +%Y%m%d-%H%M%S)-$$"

# Export password for sshpass -e (environment variable is safer than command line)
export SSHPASS="$NAS_PASS"

if [ -n "$NAS_SSH_HOST" ]; then
    SSH_TARGET="$NAS_SSH_HOST"
    RSYNC_RSH="ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=120"
    USE_SSHPASS=0
else
    SSH_TARGET="$NAS_USER@$NAS_IP"
    RSYNC_RSH="ssh -p $NAS_PORT -o ServerAliveInterval=15 -o ServerAliveCountMax=120 -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no"
    USE_SSHPASS=1
fi

remote_ssh() {
    if [ "$USE_SSHPASS" = "1" ]; then
        sshpass -e ssh -p "$NAS_PORT" -o ServerAliveInterval=15 -o ServerAliveCountMax=120 -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no "$SSH_TARGET" "$@"
    else
        ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=120 "$SSH_TARGET" "$@"
    fi
}

echo "=== 0. 写入构建身份 BUILD_INFO.json ==="
IDENTITY_SCRIPT="$LOCAL_DIR/tools/build_identity.sh"
if [ ! -x "$IDENTITY_SCRIPT" ]; then
    chmod +x "$IDENTITY_SCRIPT" 2>/dev/null || true
fi
if [ -x "$IDENTITY_SCRIPT" ] || [ -f "$IDENTITY_SCRIPT" ]; then
    bash "$IDENTITY_SCRIPT" --write
else
    # Fallback stub so Dockerfile.server COPY never fails
    printf '%s\n' \
      '{' \
      '  "version": "'"$(tr -d '[:space:]' < "$LOCAL_DIR/VERSION" 2>/dev/null || echo dev)"'",' \
      '  "git_sha": "unknown",' \
      '  "git_dirty": false,' \
      '  "tree_hash": "",' \
      '  "built_at": "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'",' \
      '  "built_on": "'"$(hostname -s 2>/dev/null || echo unknown)"'"' \
      '}' > "$LOCAL_DIR/BUILD_INFO.json"
    echo "wrote stub $LOCAL_DIR/BUILD_INFO.json (identity script missing)"
fi

echo "=== 1. 同步源码 -> NAS 临时目录 ==="
remote_ssh "rm -rf '$NAS_STAGE' && mkdir -p '$NAS_STAGE'"
RSYNC_ARGS=( -a --stats -e "$RSYNC_RSH" \
    --exclude 'venv' \
    --exclude 'node_modules' \
    --exclude 'dist' \
    --exclude 'outputs' \
    --exclude 'work' \
    --exclude '__pycache__' \
    --exclude '.DS_Store' \
    --exclude 'frontend/node_modules' \
    --exclude 'frontend/dist' \
    --exclude '.env' \
    --exclude '.env.local' \
    --exclude 'cfg/configs.json' \
    --exclude 'db' \
    --exclude 'logs' \
    --exclude 'logs/*.log' \
    --exclude '*.wav' \
    --exclude 'repair_*' \
    --exclude 'ZOOM*' \
    --exclude 'test_*.py' \
    --exclude '.git' \
    --exclude '.claude' \
    --exclude 'codex-agent' \
    --exclude 'design-demos' \
    --exclude 'pic' \
    --exclude 'CLAUDE.md' \
    --exclude 'handoff.md' \
    --exclude 'docs/handoff-*.md' \
    --exclude 'docs/deploy-zspace.md' \
    --exclude 'dockerfile' \
    --exclude '/main.go' \
    --exclude '/main.py' \
    "$LOCAL_DIR/" \
    "$SSH_TARGET:$NAS_STAGE/" )
if [ "$USE_SSHPASS" = "1" ]; then
    sshpass -e rsync "${RSYNC_ARGS[@]}"
else
    rsync "${RSYNC_ARGS[@]}"
fi

echo ""
echo "=== 2. 计算部署影响范围 ==="
REMOTE_DIFF="$(remote_ssh \
    "echo '$NAS_PASS' | sudo -S -p '' rsync -a --delete --delete-delay --dry-run --out-format='%i|%n' \
        --exclude '.env' --exclude '.env.local' --exclude 'cfg/configs.json' \
        --exclude 'db/' --exclude 'logs/' \
        '$NAS_STAGE/' '$NAS_DIR/'")"

CHANGED_COUNT=0
while IFS='|' read -r _item path; do
    [ -n "${path:-}" ] || continue
    path="${path%/}"
    [ "$path" = "." ] && continue
    CHANGED_COUNT=$((CHANGED_COUNT + 1))
    classify_changed_path "$path"
done <<EOF
$REMOTE_DIFF
EOF

case "${AVGARDEN_DEPLOY_SERVICES:-auto}" in
    auto)
        ;;
    server)
        # 强制只动 server，忽略其它路径分类
        reset_deploy_plan
        mark_server_build
        ;;
    worker)
        # 强制只动 worker
        reset_deploy_plan
        mark_worker_build
        ;;
    all)
        reset_deploy_plan
        mark_all_build
        ;;
    *)
        echo "错误: AVGARDEN_DEPLOY_SERVICES 只支持 auto、server、worker、all" >&2
        exit 2
        ;;
esac

# HOT 模式：Python 热补丁（docker cp + restart），跳过镜像构建。
# 适用：只改 worker.py / queue_api.py / src/*.py 等，且 requirements 未变。
# 用法：AVGARDEN_HOT=1 bash deploy.sh
# 或：  AVGARDEN_DEPLOY_MODE=hot bash deploy.sh
DEPLOY_HOT=0
case "${AVGARDEN_DEPLOY_MODE:-}${AVGARDEN_HOT:-}" in
    hot*|1|true|yes|on) DEPLOY_HOT=1 ;;
esac
# 依赖变化或 Dockerfile 变化时禁止 hot（必须完整构建）
if [ "$DEPLOY_HOT" = "1" ]; then
    if echo "$REMOTE_DIFF" | grep -E '\|requirements\.txt$|\|Dockerfile\.worker|\|Dockerfile\.server|\|docker-compose\.yml' >/dev/null 2>&1; then
        echo "HOT 禁用：检测到 requirements/Dockerfile/compose 变更，回退完整构建"
        DEPLOY_HOT=0
    fi
fi

echo "检测到 ${CHANGED_COUNT} 个同步变化"
print_deploy_plan
if [ "$DEPLOY_HOT" = "1" ]; then
    echo "mode=hot (skip docker build; docker cp python into running containers)"
fi
if [ "${#UNKNOWN_PATHS[@]}" -gt 0 ]; then
    echo "未识别路径按最安全策略重建两个服务"
fi

BUILD_SERVICES=()
RECREATE_SERVICES=()
if [ "$DEPLOY_HOT" = "1" ]; then
    # hot: 不 build；worker 有 py 变更则标记 hot-restart；server 前端/go 变更仍需完整 build
    if [ "$BUILD_SERVER" = "1" ]; then
        echo "HOT 注意：含 server/frontend/go 变更，server 仍完整构建"
        BUILD_SERVICES+=(server)
        RECREATE_SERVICES+=(server)
    fi
    # worker 不进 BUILD_SERVICES
    HOT_WORKER=0
    if [ "$BUILD_WORKER" = "1" ] || [ "$RECREATE_WORKER" = "1" ]; then
        HOT_WORKER=1
    fi
    # 若 auto 路径下只有 py 变更，classify 已 mark_worker
    if [ "$HOT_WORKER" != "1" ] && echo "$REMOTE_DIFF" | grep -E '\|\.py$|\|src/' >/dev/null 2>&1; then
        HOT_WORKER=1
    fi
else
    [ "$BUILD_SERVER" = "1" ] && BUILD_SERVICES+=(server)
    [ "$BUILD_WORKER" = "1" ] && BUILD_SERVICES+=(worker)
    [ "$RECREATE_SERVER" = "1" ] && RECREATE_SERVICES+=(server)
    [ "$RECREATE_WORKER" = "1" ] && RECREATE_SERVICES+=(worker)
    HOT_WORKER=0
fi

OLD_IMAGE_IDS=""
if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
    IMAGE_SERVICES="${BUILD_SERVICES[*]}"
    OLD_IMAGE_IDS="$(remote_ssh "for service in $IMAGE_SERVICES; do \
        cid=\$(echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' ps -q \$service 2>/dev/null || true); \
        if [ -n \"\$cid\" ]; then echo '$NAS_PASS' | sudo -S -p '' docker inspect -f '{{.Image}}' \"\$cid\" 2>/dev/null || true; fi; \
    done" | grep '^sha256:' | sort -u || true)"
fi

echo ""
echo "=== 3. 同步源码 -> 现役目录（保护运行数据） ==="
remote_ssh \
    "echo '$NAS_PASS' | sudo -S -p '' mkdir -p '$NAS_DIR' && echo '$NAS_PASS' | sudo -S -p '' rsync -a --delete --delete-delay \
        --exclude '.env' --exclude '.env.local' --exclude 'cfg/configs.json' \
        --exclude 'db/' --exclude 'logs/' \
        '$NAS_STAGE/' '$NAS_DIR/' && rm -rf '$NAS_STAGE'"

echo ""
echo "=== 4. 定向构建 Docker 镜像 ==="
if [ "${#BUILD_SERVICES[@]}" -gt 0 ]; then
    SERVICE_ARGS="${BUILD_SERVICES[*]}"
    BUILD_LOG="/tmp/avgarden-build-${DEPLOY_ID}.log"
    remote_ssh "build_log='$BUILD_LOG'; started=\$(date +%s); \
        if echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' build $SERVICE_ARGS >\"\$build_log\" 2>&1; then \
            elapsed=\$((\$(date +%s) - started)); \
            echo \"Build complete: $SERVICE_ARGS (\${elapsed}s)\"; \
            tail -n 12 \"\$build_log\"; \
            rm -f \"\$build_log\"; \
        else \
            status=\$?; \
            echo \"构建失败，日志: \$build_log\" >&2; \
            tail -n 160 \"\$build_log\" >&2; \
            exit \$status; \
        fi"
else
    echo "镜像输入未变化，跳过构建"
fi

echo ""
echo "=== 4b. HOT worker 热补丁（docker cp） ==="
if [ "$DEPLOY_HOT" = "1" ] && [ "${HOT_WORKER:-0}" = "1" ]; then
    remote_ssh "
        set -e
        cid=\$(echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' ps -q worker)
        if [ -z \"\$cid\" ]; then
            echo 'worker 容器不存在，回退完整 recreate' >&2
            echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' up -d --no-deps --build worker
            exit 0
        fi
        # 把 NAS 现役目录里的 Python 源码拷进容器 /app（跳过镜像重建）
        for rel in \
            worker.py queue_api.py queue_store.py launcher.py heal_runner.py \
            download_source.py weekly_updater.py plwt_translate_missing.py \
            requirements.txt \
            src/p115_offline.py src/log_writer.py src/failure_recovery.py \
            tools/maintenance/link_115_aiwei_into_data_root.py \
            ; do
            # note: queue_store.py is required when queue_api imports download_targets helpers
            if [ -f '$NAS_DIR/'\"\$rel\" ]; then
                # ensure parent dir inside container for nested paths
                dir=\$(dirname \"\$rel\")
                if [ \"\$dir\" != . ]; then
                    echo '$NAS_PASS' | sudo -S -p '' docker exec \"\$cid\" mkdir -p \"/app/\$dir\"
                fi
                echo '$NAS_PASS' | sudo -S -p '' docker cp '$NAS_DIR/'\"\$rel\" \"\$cid:/app/\$rel\"
                echo \"  cp \$rel\"
            fi
        done
        # 整棵 src/ 保险同步（仅 .py）
        if [ -d '$NAS_DIR/src' ]; then
            echo '$NAS_PASS' | sudo -S -p '' docker cp '$NAS_DIR/src/.' \"\$cid:/app/src/\"
            echo '  cp src/.'
        fi
        if [ -d '$NAS_DIR/tools/maintenance' ]; then
            echo '$NAS_PASS' | sudo -S -p '' docker exec \"\$cid\" mkdir -p /app/tools/maintenance
            echo '$NAS_PASS' | sudo -S -p '' docker cp '$NAS_DIR/tools/maintenance/.' \"\$cid:/app/tools/maintenance/\"
            echo '  cp tools/maintenance/.'
        fi
        echo '$NAS_PASS' | sudo -S -p '' docker restart \"\$cid\"
        echo 'worker restarted (hot)'
    "
else
    echo "跳过 HOT worker"
fi

echo ""
echo "=== 5. 定向重启服务 ==="
if [ "${#RECREATE_SERVICES[@]}" -gt 0 ]; then
    SERVICE_ARGS="${RECREATE_SERVICES[*]}"
    remote_ssh \
        "echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' up -d --no-deps $SERVICE_ARGS 2>&1"
else
    echo "运行配置未变化，跳过容器重启"
fi

echo ""
echo "=== 5b. 热更新 BUILD_INFO 到运行中 server（无需重建镜像） ==="
remote_ssh "
    set -e
    if [ ! -f '$NAS_DIR/BUILD_INFO.json' ]; then
        echo 'skip: BUILD_INFO.json missing on NAS'
        exit 0
    fi
    cid=\$(echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' ps -q server 2>/dev/null || true)
    if [ -z \"\$cid\" ]; then
        echo 'skip: server container not running yet'
        exit 0
    fi
    echo '$NAS_PASS' | sudo -S -p '' docker cp '$NAS_DIR/BUILD_INFO.json' \"\$cid:/app/BUILD_INFO.json\"
    echo 'BUILD_INFO.json -> server:/app/BUILD_INFO.json'
"

echo ""
echo "=== 6. 等待 API 就绪 ==="
READY=0
READY_STARTED=$SECONDS
for _i in $(seq 1 40); do
    if curl -fsS --max-time 3 "http://${NAS_IP}:31471/api/version" >/dev/null 2>&1; then
        READY=1
        echo "API ready after $((SECONDS - READY_STARTED))s"
        break
    fi
    sleep 2
done
if [ "$READY" != "1" ]; then
    echo "警告: 部署后 API 仍未就绪，前端加入队列可能短暂失败（会自动重试）"
else
    # Show identity so operators can confirm Mac vs NAS without a separate tool.
    if VER_JSON="$(curl -fsS --max-time 5 "http://${NAS_IP}:31471/api/version" 2>/dev/null)"; then
        printf '%s' "$VER_JSON" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("version:", d.get("version")); print("tree_hash:", d.get("tree_hash") or "(none)"); print("tree_hash_server:", d.get("tree_hash_server") or "(none)"); print("tree_hash_worker:", d.get("tree_hash_worker") or "(none)"); print("git_sha:", d.get("git_sha") or "(none)")' 2>/dev/null || true
    fi
fi

SERVICES_UP=0
if remote_ssh "for service in server worker; do \
    cid=\$(echo '$NAS_PASS' | sudo -S -p '' docker compose -f '$NAS_DIR/docker-compose.yml' ps -q \$service); \
    [ -n \"\$cid\" ] && [ \"\$(echo '$NAS_PASS' | sudo -S -p '' docker inspect -f '{{.State.Running}}' \"\$cid\")\" = true ] || exit 1; \
done"; then
    SERVICES_UP=1
fi

echo ""
echo "=== 7. 精确清理本次替换的旧镜像 ==="
if [ "$READY" = "1" ] && [ "$SERVICES_UP" = "1" ] && [ -n "$OLD_IMAGE_IDS" ]; then
    remote_ssh "old_ids='$OLD_IMAGE_IDS'; \
        refs=\$(ids=\$(echo '$NAS_PASS' | sudo -S -p '' docker ps -aq); if [ -n \"\$ids\" ]; then echo '$NAS_PASS' | sudo -S -p '' docker inspect -f '{{.Image}}' \$ids; fi); \
        for id in \$old_ids; do \
            if printf '%s\\n' \"\$refs\" | grep -Fxq \"\$id\"; then \
                echo \"保留仍被容器引用的镜像 \$id\"; \
            else \
                echo '$NAS_PASS' | sudo -S -p '' docker image rm \"\$id\"; \
            fi; \
        done"
else
    echo "跳过旧镜像清理：没有被替换的旧镜像，或容器/API 尚未通过健康检查"
fi

echo ""
echo "=== 部署完成，总耗时 $((SECONDS - DEPLOY_STARTED))s ==="
