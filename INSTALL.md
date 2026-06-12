# AV/GARDEN Docker Compose 安装指南

这份指南面向把 AV/GARDEN 部署到 NAS、Linux 服务器或 Docker 主机的用户。分发和提交时不要附带真实 `.env`、`cfg/configs.json`、`db/`、`logs/` 或视频目录。

## 前置条件

- Docker 与 Docker Compose
- 一个可写的视频保存目录
- 可访问的 qBittorrent Web UI
- 可选：HTTP 代理、DeepSeek API key、飞书 webhook

## 快速开始

1. 准备配置文件：

```bash
cp .env.example .env
cp cfg/configs.json.example cfg/configs.json
```

2. 编辑 `.env`：

```bash
AV_GARDEN_DATA_DIR=/absolute/path/to/your/video-library
QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your_password
PROXY=
```

如果 qBittorrent 不在 Docker 主机上，把 `QBITTORRENT_URL` 改成实际地址，例如 `http://192.168.1.10:8080`。

qBittorrent 的默认保存目录需要和 `AV_GARDEN_DATA_DIR` 指向同一份存储，否则 AV/GARDEN 可能能添加磁链，但无法在 `/data/<番号>` 下找到下载结果。

3. 编辑 `cfg/configs.json`：

容器部署时建议保留这些容器内路径：

```json
{
  "LogPath": "/app/logs",
  "SavePath": "/data",
  "DBPath": "/db/downloaded.db",
  "QueuePath": "/db/download_queue.txt"
}
```

下载器域名、代理和 qBittorrent 账号按自己的环境调整。`.env` 里的 qBittorrent 配置会覆盖 `cfg/configs.json` 里的同名配置。

4. 创建本地目录并启动：

```bash
mkdir -p ./db ./logs
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

同时确认你已经创建了 `.env` 里 `AV_GARDEN_DATA_DIR` 指向的视频目录。

5. 打开网页：

```text
http://<你的服务器地址>:31471
```

如果修改了 `AV_GARDEN_HTTP_PORT`，使用你设置的端口。

## 验证

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
curl -sS http://127.0.0.1:31471/api/version
curl -sS http://127.0.0.1:31471/api/queue-status
```

如果修改了 `AV_GARDEN_HTTP_PORT`，把验证命令里的 `31471` 替换成你的端口。

查看日志：

```bash
docker compose -f docker-compose.example.yml --env-file .env logs -f server
docker compose -f docker-compose.example.yml --env-file .env logs -f worker
```

## 分发清单

可以分享：

- 源码
- `Dockerfile.server`
- `Dockerfile.worker`
- `docker-compose.example.yml`
- `.env.example`
- `cfg/configs.json.example`
- `INSTALL.md`
- `README.md`
- `AGENTS.md`
- `LICENSE`

不要分享：

- `.env`
- `cfg/configs.json`
- `db/`
- `logs/`
- 视频目录
- 任何包含账号、密码、Cookie、API key 的文件

## 常见问题

### qBittorrent 连接不上

先确认 Web UI 地址、账号和密码正确。Linux Docker 主机上，模板已配置 `host.docker.internal:host-gateway`；如果你的 Docker 版本不支持它，改用主机局域网 IP。

再确认 qBittorrent 的保存路径和 `AV_GARDEN_DATA_DIR` 是同一份目录，尤其是 qBittorrent 也跑在容器里时，需要给它挂载同一个宿主机视频目录。

### 页面能打开，但下载队列不可用

模板里 Go 后端会通过 Docker 内部服务名 `http://worker:31473` 访问 Queue API。确认 `worker` 容器正在运行：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps worker
```

### 不想本地构建镜像

第一版模板默认本地构建。后续可以把 `server` 和 `worker` 镜像推到 Docker Hub 或 GHCR，再把 `build` 改成 `image`，用户就能直接拉取镜像运行。
