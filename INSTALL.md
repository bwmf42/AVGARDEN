# A/GARDEN 安装指南

这份文档按“先跑起来，再慢慢调”的顺序写。你只需要准备一台能跑 Docker 的 NAS、Linux 服务器或家用小主机。

## 你需要先准备什么

- Docker 和 Docker Compose
- 一个媒体保存目录，例如 `/volume1/media/library`
- qBittorrent，并开启 Web UI
- 可选：代理、OpenAI 兼容翻译中继或 DeepSeek API key、飞书 webhook

最容易出错的地方只有一个：qBittorrent 的保存目录，必须和 A/GARDEN 的媒体目录指向同一份存储。

## 1. 下载项目

```bash
git clone https://github.com/bwmf42/AVGARDEN.git
cd AVGARDEN
```

如果你是直接下载 zip，也可以解压后进入项目目录。

## 2. 复制配置文件

```bash
cp .env.example .env
cp cfg/configs.json.example cfg/configs.json
mkdir -p db logs
```

真实的 `.env`、`cfg/configs.json`、`db/` 和 `logs/` 不要上传到 GitHub。

## 3. 修改 `.env`

先只改最关键的四项：

```text
AV_GARDEN_DATA_DIR=/absolute/path/to/your/video-library
QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your_password
```

说明：

- `AV_GARDEN_DATA_DIR` 必须是 Docker 主机上的绝对路径。
- qBittorrent 跑在同一台机器上时，可以先试 `http://host.docker.internal:8080`。
- qBittorrent 跑在另一台机器上时，改成它的局域网地址，例如 `http://192.168.1.10:8080`。
- 需要代理时，再填 `PROXY=http://你的代理地址:端口`。

## 4. 检查 `cfg/configs.json`

Docker 部署时建议保留这些容器内路径：

```json
{
  "LogPath": "/app/logs",
  "SavePath": "/data",
  "DBPath": "/db/downloaded.db",
  "QueuePath": "/db/download_queue.txt"
}
```

下载器、来源域名、代理等高级项可以以后再调。qBittorrent 账号密码优先读 `.env`。

## 5. 启动

```bash
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

第一次启动会构建镜像，时间会比较久。

## 6. 打开网页

默认地址：

```text
http://<你的服务器地址>:31471
```

如果你修改了 `.env` 里的 `AV_GARDEN_HTTP_PORT`，就用你设置的端口。

## 7. 确认是否正常

查看容器：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
```

查看版本：

```bash
curl -sS http://127.0.0.1:31471/api/version
```

查看队列状态：

```bash
curl -sS http://127.0.0.1:31471/api/queue-status
```

查看日志：

```bash
docker compose -f docker-compose.example.yml --env-file .env logs -f server
docker compose -f docker-compose.example.yml --env-file .env logs -f worker
```

网页里的“日志”页会读取 `logs/` 目录里的最近日志。

## qBittorrent 怎么配

在 qBittorrent 里确认：

- Web UI 已开启。
- Web UI 地址、用户名、密码和 `.env` 一致。
- 默认保存路径和 `AV_GARDEN_DATA_DIR` 是同一份目录。

举个例子：

```text
AV_GARDEN_DATA_DIR=/volume1/media/av
```

那 qBittorrent 的默认保存路径也应该落到这份目录，或者是同一份目录在 qB 容器里的挂载路径。

如果 qBittorrent 也跑在 Docker 里，两个容器最好挂载同一个宿主机目录。

## 常见问题

### 页面能打开，但添加任务失败

先检查 qBittorrent Web UI 地址、用户名和密码。然后看：

```bash
docker compose -f docker-compose.example.yml --env-file .env logs -f worker
```

### qB 里有任务，但 A/GARDEN 认为没完成

通常是保存目录没对上。qB 下载到 A 目录，A/GARDEN 在 B 目录找文件，就会一直找不到。

### 日志页是空的

先看宿主机项目目录下有没有 `logs/*.log`。如果有日志文件但页面空，重启服务：

```bash
docker compose -f docker-compose.example.yml --env-file .env restart
```

### 刮削慢或失败

这通常和网络、代理、站点限制有关。可以先设置代理：

```text
PROXY=http://127.0.0.1:7890
```

如果代理在宿主机上，容器里可能需要写成宿主机局域网 IP 或 `host.docker.internal`。

## 可选功能

标题翻译优先使用 OpenAI 兼容中继：

```text
TRANSLATE_API_BASE=https://example.com/v1
TRANSLATE_API_KEY=你的key
TRANSLATE_MODEL=gpt-5.4
```

未配置中继时可回退 DeepSeek：

```text
DEEPSEEK_API_KEY=你的key
DEEPSEEK_MODEL=deepseek-chat
```

飞书通知：

```text
FEISHU_WEBHOOK=你的飞书机器人 webhook
```

每日推荐限制：

```text
WEEKLY_MAX_PAGES=3
WEEKLY_MAX_NEW=20
WEEKLY_MAX_AGE=30
```

## 更新项目

```bash
git pull
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

更新前建议备份：

```text
db/
cfg/configs.json
.env
```

## 数据安全

这些文件不要分享：

- `.env`
- `cfg/configs.json`
- `db/`
- `logs/`
- 媒体目录
- 任何账号、密码、Cookie、API key、webhook

建议定期备份 `db/` 和 `cfg/`。
