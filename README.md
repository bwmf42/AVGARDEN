<div align="center">
<img style="max-width:50%;" src="pic/logo.png" alt="AV/GARDEN" />
<br>
</div>

# AV/GARDEN

AV/GARDEN 是一个面向 NAS 和家庭服务器的 AV 媒体下载、整理和浏览系统。

当前版本：`0.1.0`

建议仓库名：`AVGARDEN`。

它把“每日推荐浏览 -> 加入下载队列 -> Sukebei/qBittorrent 磁链下载 -> 在线流兜底 -> 元数据刮削 -> Jellyfin 可识别媒体库”整理成一套可部署的 Web 应用。

## 简介

AV/GARDEN 适合已经有 NAS、qBittorrent 和媒体库目录的用户。它提供一个粉白色 Web UI，用来浏览每日推荐、搜索本地与已刮削条目、管理下载队列、查看日志，并在下载完成后自动生成 NFO、封面和预览图。

下载策略是：

```text
优先 Sukebei/weekly 磁链 -> qBittorrent 下载 -> 仅当没有磁链时尝试在线流下载器
```

“在线流”指 MissAV、Jable、Memo、KanAV、HohoJ 等站点里的 m3u8 播放流。它是兜底路径，不会在 qB 已接管下载时继续执行。

## 核心功能

- Web 前端：媒体库、每日推荐、影片详情、下载管理、设置、日志。
- 每日推荐：抓取近期番号，补 JavBus 元数据、封面、标签、演员、磁链和中文标题。
- qBittorrent 优先：优先使用 Sukebei/weekly 磁链，并聚合 qB 下载状态。
- 在线流兜底：只有未找到磁链时才尝试 MissAV、Jable、Memo、KanAV、HohoJ。
- 元数据整理：下载完成后生成 Jellyfin 可识别的 NFO、封面、预览图。
- 下载队列：支持添加、排队、进行中、最近完成记录和最近失败记录。
- 搜索：支持本地媒体库与每日推荐数据的统一搜索。
- 屏蔽与收藏：支持屏蔽女优、屏蔽标签、标题关键词和收藏女优。
- 手动刮削：设置页可手动触发每日推荐刮削。
- 版本排查：`/api/version` 返回版本号、构建时间和前端资源 hash。

## 架构

```text
frontend/                 Vue 3 + Vite 前端
backend/main.go           Go HTTP 服务，托管 API 和 frontend/dist
backend/handlers.go       主要 API 处理逻辑
queue_api.py              Queue API，队列/进度/历史/失败聚合
worker.py                 下载主流程，磁链/qB 优先，在线流兜底
launcher.py               worker 容器入口，启动 Queue API、Worker 和每日刮削调度
weekly_updater.py         每日推荐更新
metadata.py               批量元数据刮削工具
src/weekly/               推荐源、JavBus、Sukebei、合并逻辑
src/downloader/           在线流下载器
src/data.py               SQLite 初始化与兼容迁移
docker-compose.example.yml 通用部署模板
```

运行时由两个容器组成：

- `av-garden-server`：Go 后端 + Vue 静态资源，默认端口 `31471`。
- `av-garden-worker`：Queue API + 下载 Worker + 每日推荐调度，Queue API 默认端口 `31473`。

qBittorrent 独立运行，AV/GARDEN 通过 qB Web API 添加磁链并读取任务状态。

## 快速部署

前置条件：

- Docker 与 Docker Compose
- 一个可写的视频库目录
- qBittorrent Web UI 地址、用户名和密码
- 可选：HTTP 代理、DeepSeek API key、飞书 webhook

启动：

```bash
cp .env.example .env
cp cfg/configs.json.example cfg/configs.json
mkdir -p db logs
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

最少需要编辑 `.env`：

```text
AV_GARDEN_DATA_DIR=/absolute/path/to/your/video-library
QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your_password
PROXY=
```

打开：

```text
http://<服务器地址>:31471
```

更完整的安装说明见 [INSTALL.md](INSTALL.md)。

## 配置说明

### `.env`

`.env` 存放部署路径、端口、qBittorrent、代理、DeepSeek、飞书等环境变量。不要提交真实 `.env`。

常用项：

```text
AV_GARDEN_HTTP_PORT=31471
AV_GARDEN_DATA_DIR=/absolute/path/to/video-library
AV_GARDEN_DB_DIR=./db
AV_GARDEN_CFG_DIR=./cfg
AV_GARDEN_LOG_DIR=./logs

QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=change_me

PROXY=http://127.0.0.1:7890
DEEPSEEK_API_KEY=
FEISHU_WEBHOOK=

WEEKLY_MAX_PAGES=3
WEEKLY_MAX_NEW=20
WEEKLY_MAX_AGE=30
```

### `cfg/configs.json`

容器部署时建议保留这些容器内路径：

```json
{
  "LogPath": "/app/logs",
  "SavePath": "/data",
  "DBPath": "/db/downloaded.db",
  "QueuePath": "/db/download_queue.txt"
}
```

下载器权重示例：

```json
"Downloader": [
  { "downloaderName": "MissAV", "domain": "missav.ai", "weight": 1000 },
  { "downloaderName": "Jable", "domain": "jable.tv", "weight": 900 },
  { "downloaderName": "Memo", "domain": "memojav.com", "weight": 600 },
  { "downloaderName": "KanAV", "domain": "kanav.info", "weight": 490 },
  { "downloaderName": "HohoJ", "domain": "hohoj.tv", "weight": 400 }
]
```

`.env` 中的 qBittorrent、代理、DeepSeek 和飞书配置会覆盖或补充运行配置。

## 关键 API

| API | 说明 |
| --- | --- |
| `GET /api/version` | 当前版本、构建时间和前端资源 hash |
| `GET /api/videos` | 已下载影片列表 |
| `GET /api/videos/{ID}` | 已下载影片详情 |
| `GET /api/weekly` | 每日推荐列表 |
| `GET/PUT /api/weekly-watched` | 每日推荐已看状态 |
| `GET /api/queue/` | 下载管理聚合状态 |
| `POST /api/queue/` | 加入下载队列 |
| `DELETE /api/queue/{ID}` | 移出下载管理记录，默认不删文件 |
| `GET /api/queue-status` | 顶部状态条，成功项不展示 |
| `GET/POST/DELETE /api/failed-ack` | 失败提示忽略状态 |
| `POST /api/weekly/scrape` | 手动触发每日推荐刮削 |
| `GET /api/logs` | 读取最近日志 |

真正删除视频目录需要显式调用：

```http
DELETE /api/queue/{ID}?delete_files=1
```

默认“移出记录”不会删除已下载文件。

## 给 AI Agent 的配置清单

如果你让 AI agent 帮你部署或排查，先让它读取这些文件：

```text
README.md
INSTALL.md
AGENTS.md
.env.example
docker-compose.example.yml
cfg/configs.json.example
```

它需要确认：

- Docker 主机的视频库绝对路径，并写入 `AV_GARDEN_DATA_DIR`。
- qBittorrent Web UI 地址、用户名、密码，并写入 `QBITTORRENT_*`。
- qBittorrent 的默认保存目录和 AV/GARDEN 的 `/data` 是否指向同一份存储。
- 是否需要代理，若需要写入 `PROXY`。
- 是否配置 DeepSeek 翻译和飞书通知。
- 不要读取或上传真实 `.env`、`cfg/configs.json`、`db/`、`logs/` 和视频目录。

## 验证与运维

检查容器：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
```

检查版本：

```bash
curl -sS http://127.0.0.1:31471/api/version
```

检查状态：

```bash
curl -sS http://127.0.0.1:31471/api/queue-status
```

查看日志：

```bash
docker compose -f docker-compose.example.yml --env-file .env logs -f server
docker compose -f docker-compose.example.yml --env-file .env logs -f worker
```

手动触发每日推荐刮削：

```bash
curl -X POST http://127.0.0.1:31471/api/weekly/scrape
```

## 开发

前端：

```bash
cd frontend
npm install
npm run dev
npm run build
```

Go 后端：

```bash
cd backend
GOCACHE=/private/tmp/av-garden-gocache go test ./...
```

Python 语法检查：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/av-garden-pycache python3 -m py_compile worker.py queue_api.py launcher.py weekly_updater.py metadata.py replace_chinese.py src/weekly/sukebei.py
```

## 数据与安全边界

不要提交或分享：

- `.env`
- `cfg/configs.json`
- `db/`
- `logs/`
- 视频库目录
- 包含账号、密码、Cookie、API key、webhook 的任何文件

常见运行状态文件：

```text
db/downloaded.db          SQLite 媒体数据库
db/download_queue.txt     等待队列
db/queue_state.json       下载状态
db/current_download.txt   当前下载
db/download_history.json  最近完成历史
db/failed_queue.json      失败记录
db/failed_ack.json        失败提示忽略状态
db/weekly_watched.json    每日推荐已看状态
```

## 注意事项

- 需要稳定网络和可用代理，部分源会触发 Cloudflare 或区域限制。
- qBittorrent 的保存路径必须和 AV/GARDEN 的 `/data` 指向同一份存储，否则完成检测会失效。
- DeepSeek 翻译和飞书通知是可选能力，没有 key/webhook 时对应功能会降级。
- 建议定期备份 `db/` 和 `cfg/`。
- 请遵守当地法律法规，仅在合法范围内使用。

## 致谢

AV/GARDEN 基于 [Satoing/NASSAV](https://github.com/Satoing/NASSAV) 的源码继续整理和演进。感谢原作者提供的项目基础、下载流程和 NAS 部署思路。

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。
