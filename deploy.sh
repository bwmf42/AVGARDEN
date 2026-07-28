#!/bin/bash
set -e

NAS_USER="${AVGARDEN_USER:-13049108160}"
NAS_IP="${AVGARDEN_IP:-192.168.5.14}"
NAS_PORT="${AVGARDEN_PORT:-10000}"
NAS_PASS="${AVGARDEN_PASS:?错误: 需要设置 AVGARDEN_PASS 环境变量}"
NAS_SSH_HOST="${AVGARDEN_SSH_HOST:-}"
NAS_DIR="/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN"
NAS_STAGE="/tmp/avgarden-deploy-${NAS_USER}"
export SSHPASS="$NAS_PASS"

if [ -n "$NAS_SSH_HOST" ]; then
    SSH_TARGET="$NAS_SSH_HOST"
    RSYNC_RSH="ssh"
    USE_SSHPASS=0
else
    SSH_TARGET="$NAS_USER@$NAS_IP"
    RSYNC_RSH="ssh -p $NAS_PORT -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no"
    USE_SSHPASS=1
fi

remote_ssh() {
    if [ "$USE_SSHPASS" = "1" ]; then
        sshpass -e ssh -p "$NAS_PORT" -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no "$SSH_TARGET" "$@"
    else
        ssh "$SSH_TARGET" "$@"
    fi
}

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

OLD_IMAGE_IDS="$(remote_ssh "for service in server worker; do \
    cid=\$(echo '$NAS_PASS' | sudo -S docker compose -f '$NAS_DIR/docker-compose.yml' ps -q \$service 2>/dev/null || true); \
    if [ -n \"\$cid\" ]; then echo '$NAS_PASS' | sudo -S docker inspect -f '{{.Image}}' \"\$cid\" 2>/dev/null || true; fi; \
done" | grep '^sha256:' | sort -u || true)"

echo "=== 1. 同步源码 → NAS 临时目录 ==="
remote_ssh "rm -rf '$NAS_STAGE' && mkdir -p '$NAS_STAGE'"
RSYNC_ARGS=( -av -e "$RSYNC_RSH" \
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

echo "=== 2. 同步源码 → 现役目录（删除仓库已移除文件，保护运行数据） ==="
remote_ssh \
    "echo '$NAS_PASS' | sudo -S mkdir -p '$NAS_DIR' && echo '$NAS_PASS' | sudo -S rsync -a --delete --delete-delay --itemize-changes \
        --exclude '.env' --exclude '.env.local' --exclude 'cfg/configs.json' \
        --exclude 'db/' --exclude 'logs/' \
        '$NAS_STAGE/' '$NAS_DIR/' && rm -rf '$NAS_STAGE'"

echo ""
echo "=== 3. 构建 Docker 镜像 ==="
remote_ssh \
    "echo '$NAS_PASS' | sudo -S docker compose -f $NAS_DIR/docker-compose.yml build 2>&1"

echo ""
echo "=== 4. 重启服务 ==="
remote_ssh \
    "echo '$NAS_PASS' | sudo -S docker compose -f $NAS_DIR/docker-compose.yml up -d 2>&1"

echo ""
echo "=== 5. 等待 API 就绪 ==="
READY=0
for i in $(seq 1 40); do
    if curl -fsS --max-time 3 "http://${NAS_IP}:31471/api/version" >/dev/null 2>&1; then
        READY=1
        echo "API ready after ${i}s"
        break
    fi
    sleep 2
done
if [ "$READY" != "1" ]; then
    echo "警告: 部署后 API 仍未就绪，前端加入队列可能短暂失败（会自动重试）"
fi
SERVICES_UP=0
if remote_ssh "for service in server worker; do \
    cid=\$(echo '$NAS_PASS' | sudo -S docker compose -f '$NAS_DIR/docker-compose.yml' ps -q \$service); \
    [ -n \"\$cid\" ] && [ \"\$(echo '$NAS_PASS' | sudo -S docker inspect -f '{{.State.Running}}' \"\$cid\")\" = true ] || exit 1; \
done"; then
    SERVICES_UP=1
fi

echo ""
echo "=== 6. 精确清理本次替换的旧镜像 ==="
if [ "$READY" = "1" ] && [ "$SERVICES_UP" = "1" ] && [ -n "$OLD_IMAGE_IDS" ]; then
    remote_ssh "old_ids='$OLD_IMAGE_IDS'; \
        refs=\$(ids=\$(echo '$NAS_PASS' | sudo -S docker ps -aq); if [ -n \"\$ids\" ]; then echo '$NAS_PASS' | sudo -S docker inspect -f '{{.Image}}' \$ids; fi); \
        for id in \$old_ids; do \
            if printf '%s\\n' \"\$refs\" | grep -Fxq \"\$id\"; then \
                echo \"保留仍被容器引用的镜像 \$id\"; \
            else \
                echo '$NAS_PASS' | sudo -S docker image rm \"\$id\"; \
            fi; \
        done"
else
    echo "跳过旧镜像清理：没有旧镜像，或容器/API 尚未通过健康检查"
fi

echo ""
echo "=== 部署完成 ==="
