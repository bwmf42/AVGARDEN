#!/bin/bash
# AV/GARDEN 健康检查 — cron 定时跑，异常推飞书通知

FEISHU_WEBHOOK="${FEISHU_WEBHOOK:?错误: 需要设置 FEISHU_WEBHOOK 环境变量}"
QB_URL="${QBITTORRENT_URL:-http://127.0.0.1:8080}"
QB_USER="${QBITTORRENT_USERNAME:-admin}"
QB_PASS="${QBITTORRENT_PASSWORD:?错误: 需要设置 QBITTORRENT_PASSWORD 环境变量}"
API_URL="${AV_GARDEN_API_URL:-http://127.0.0.1:31471/api/videos}"
SAVE_PATH="${SAVE_PATH:?错误: 需要设置 SAVE_PATH 环境变量}"
PROJECT_DIR="${AV_GARDEN_DIR:-$(cd "$(dirname "$0")" && pwd)}"
WEEKLY_FILE="${WEEKLY_FILE:-$SAVE_PATH/__weekly__/weekly.json}"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/logs/health_check.log}"

errors=""

# 1. Go API
if ! curl -sf --max-time 10 "$API_URL" > /dev/null; then
    errors="$errors\n- Go API 无响应 ($API_URL)"
fi

# 2. Worker 容器
if ! sudo docker ps --format '{{.Names}}' | grep -q av-garden-worker; then
    errors="$errors\n- Worker 容器未运行"
fi

# 3. qBittorrent
if ! curl -sf --max-time 5 -c /tmp/qb_health -X POST "$QB_URL/api/v2/auth/login" \
     --data "username=$QB_USER&password=$QB_PASS" > /dev/null; then
    errors="$errors\n- qBittorrent 无法连接 ($QB_URL)"
fi

# 4. weekly.json 不为空
if [ ! -s "$WEEKLY_FILE" ] || [ "$(cat "$WEEKLY_FILE")" = "[]" ] || [ "$(cat "$WEEKLY_FILE")" = "null" ]; then
    errors="$errors\n- weekly.json 为空或损坏"
fi

# 发送飞书通知
if [ -n "$errors" ]; then
    msg="AV/GARDEN 健康检查异常：$errors"
    curl -sf -X POST "$FEISHU_WEBHOOK" \
        -H "Content-Type: application/json" \
        -d "{\"msg_type\":\"text\",\"content\":{\"text\":\"$msg\"}}" > /dev/null
    echo "[$(date '+%Y-%m-%d %H:%M')] FAIL $errors" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M')] OK" >> "$LOG_FILE"
fi
