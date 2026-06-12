<div align="center">
  <img style="max-width:50%;" src="pic/logo.png" alt="AV/GARDEN" />
  <br>
  <strong>给 NAS 和家庭服务器用的媒体下载、刮削、整理小站</strong>
  <br>
  <br>
  <img src="https://img.shields.io/github/license/bwmf42/AVGARDEN?style=for-the-badge&color=FF69B4" alt="License">
  <img src="https://img.shields.io/badge/version-0.1.0-FF69B4?style=for-the-badge" alt="Version">
</div>

# AV/GARDEN

AV/GARDEN 是一个面向 NAS、家庭服务器和个人媒体库的 Web 工具。

它把“找资源、加入下载、等待完成、整理元数据、进入媒体库”放到一个网页里处理。你可以在浏览器里看每日推荐、添加下载任务、查看下载状态、搜索本地影片，并让它在下载完成后自动生成 Jellyfin 等媒体服务器能识别的封面和 NFO。

当前版本：`0.1.0`

## 项目简介

如果你已经有一台 NAS、一个 qBittorrent 和一个视频保存目录，AV/GARDEN 可以帮你少做很多重复动作：

- 从每日推荐里挑片。
- 优先找 Sukebei 磁链。
- 有磁链时交给 qBittorrent 下载。
- 没有磁链时再尝试在线流兜底。
- 下载完成后补封面、预览图、NFO 和标题。
- 最后在网页里浏览和搜索本地媒体库。

简单说，它不是播放器，而是一个围绕 NAS 媒体库的下载和整理控制台。

## 核心特性

- **网页操作**：媒体库、每日推荐、详情页、下载管理、设置、日志都在浏览器里完成。
- **qBittorrent 优先**：先找磁链，再交给 qB 下载和做进度管理。
- **在线流兜底**：没有磁链时，才尝试 MissAV、Jable、Memo、KanAV、HohoJ 等来源。
- **元数据整理**：下载后生成封面、预览图和 Jellyfin 可识别的 NFO。
- **每日推荐**：抓取近期条目，补 JavBus 元数据、中文标题、演员、标签和磁链。
- **本地搜索**：同时搜索本地媒体库和已刮削条目。
- **下载管理**：只展示进行中、等待中、最近完成和最近失败，成功项不会一直占状态栏。
- **偏好设置**：支持屏蔽演员、屏蔽标签、标题关键词、收藏女优和已看状态。
- **手动刮削**：设置页可手动触发每日推荐刮削。

## 系统要求

- Docker 和 Docker Compose
- 一个可写的视频保存目录
- qBittorrent Web UI
- 建议准备稳定代理
- 可选：DeepSeek API key、飞书 webhook

## 安装指南

### 1. 克隆项目

```bash
git clone https://github.com/bwmf42/AVGARDEN.git
cd AVGARDEN
```

### 2. 复制配置

```bash
cp .env.example .env
cp cfg/configs.json.example cfg/configs.json
mkdir -p db logs
```

### 3. 修改 `.env`

至少改这几项：

```text
AV_GARDEN_DATA_DIR=/absolute/path/to/your/video-library
QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your_password
```

如果 qBittorrent 不在 Docker 主机上，把 `QBITTORRENT_URL` 改成它的局域网地址，例如：

```text
QBITTORRENT_URL=http://192.168.1.10:8080
```

### 4. 启动服务

```bash
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

### 5. 打开网页

```text
http://<你的服务器地址>:31471
```

更完整的安装、更新和排错步骤见 [INSTALL.md](INSTALL.md)。

## 使用方法

### 浏览每日推荐

打开“每日推荐”，选择感兴趣的条目，进入详情页查看标题、封面、演员、标签、磁链状态和下载按钮。

### 添加下载任务

你可以在详情页点击“加入下载队列”，也可以在右上角输入番号后点击“添加”。

下载流程默认是：

```text
Sukebei 磁链 -> qBittorrent 下载 -> 在线流兜底 -> 元数据刮削 -> 媒体库
```

在线流只在没有找到可用磁链时尝试。

### 搜索本地媒体

右上角输入关键词后点击“搜索”，结果页会区分本地媒体和每日推荐数据。

### 查看下载状态

“下载管理”会展示等待中、下载中、最近完成和最近失败。失败记录默认只看最近一段时间，避免旧失败一直干扰判断。

### 手动刮削

进入“设置”，点击手动刮削按钮，可以立刻跑一次每日推荐更新。

## 配置说明

### `.env`

`.env` 放的是部署环境和外部服务账号，不要提交到 GitHub。

常用项：

```text
AV_GARDEN_HTTP_PORT=31471
AV_GARDEN_DATA_DIR=/absolute/path/to/video-library
QBITTORRENT_URL=http://host.docker.internal:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=change_me
PROXY=
DEEPSEEK_API_KEY=
FEISHU_WEBHOOK=
```

### `cfg/configs.json`

Docker 部署时建议保留这些容器内路径：

```json
{
  "LogPath": "/app/logs",
  "SavePath": "/data",
  "DBPath": "/db/downloaded.db",
  "QueuePath": "/db/download_queue.txt"
}
```

最重要的是：qBittorrent 的下载保存目录，要和 `AV_GARDEN_DATA_DIR` 指向同一份存储。否则 qB 已经下载完，AV/GARDEN 也可能找不到文件。

## 更新

```bash
git pull
docker compose -f docker-compose.example.yml --env-file .env up -d --build
```

更新前建议备份：

```text
.env
cfg/configs.json
db/
```

## 给 AI Agent 的接手清单

如果你让 AI agent 帮你部署或排查，先让它读取：

```text
README.md
INSTALL.md
AGENTS.md
.env.example
docker-compose.example.yml
cfg/configs.json.example
```

它需要先确认：

- Docker 主机的视频目录是什么。
- qBittorrent Web UI 地址、用户名、密码是否正确。
- qBittorrent 保存目录和 `AV_GARDEN_DATA_DIR` 是否指向同一份存储。
- 是否需要代理。
- 是否配置 DeepSeek 翻译和飞书通知。
- 不要读取、上传或提交真实 `.env`、`cfg/configs.json`、`db/`、`logs/` 和视频目录。

## 常见问题

### 页面能打开，但添加任务失败

优先检查 qBittorrent Web UI 地址、用户名、密码，以及容器能不能访问这个地址。

### qBittorrent 里有任务，但网页没有完成

通常是目录没对上。qB 下载到一个目录，AV/GARDEN 在另一个目录找文件，就会一直认为没完成。

### 日志里全是 DEBUG

新版默认隐藏 DEBUG 噪音。需要排查底层问题时，可以临时访问：

```text
/api/logs?debug=1
```

### 标题只显示番号

AV/GARDEN 会优先读 NFO 标题。如果没有 NFO，会尝试从每日推荐数据、JSON 元数据或网页缓存里补标题。

## 数据与安全

不要分享或提交：

- `.env`
- `cfg/configs.json`
- `db/`
- `logs/`
- 视频目录
- 任何账号、密码、Cookie、API key、webhook

建议定期备份 `db/` 和 `cfg/`。

## 来源与致谢

AV/GARDEN 基于 [Satoing/NASSAV](https://github.com/Satoing/NASSAV) 的源码继续整理和演进。感谢原作者提供的项目基础、下载流程和 NAS 部署思路。

本项目保留上游 MIT 许可证和版权声明，详细来源说明见 [NOTICE](NOTICE)。

也感谢 [m3u8-Downloader-Go](https://github.com/Greyh4t/m3u8-Downloader-Go) 提供 m3u8 下载能力。

## 注意事项

- 使用本项目需要稳定网络，部分来源可能会触发访问限制。
- 请遵守当地法律法规，仅在合法范围内使用。
- 下载频率不要过高。
- 建议定期备份数据库和配置文件。

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
