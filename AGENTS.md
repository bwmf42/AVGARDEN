# A/GARDEN Agent Guide

本文件记录 A/GARDEN 项目专属规则，供 AI agent 或维护者快速理解、配置和验证项目。

## 项目定位

A/GARDEN 是面向 NAS 和家庭服务器的媒体下载、整理和浏览系统：

- 用户输入内容编号或从每日推荐中选择条目。
- Worker 优先使用 weekly 数据里的磁链并交给 qBittorrent。
- 只有未找到磁链时，才 fallback 到在线流下载器。
- 下载完成后刮削元数据，生成 Jellyfin NFO、封面和预览图。
- Go 后端提供 API 并托管 Vue 前端。
- Vue 前端负责媒体库、每日推荐、详情、下载管理、设置和日志。

## 关键入口

- Go 后端：`backend/main.go`，端口 `31471`，同时服务 API 和 `frontend/dist`。
- 后端处理器：`backend/handlers.go`。
- Python Worker：`worker.py`，下载主流程。
- Queue API：`queue_api.py`，端口 `31473`，负责队列、进度、失败记录和启动恢复。
- 容器入口：`launcher.py`，协调 worker 与 Queue API，并调度每日刮削。
- 每日推荐：`weekly_updater.py`，数据模块在 `src/weekly/`。
- 元数据：`metadata.py`、`src/scraper.py`。
- 前端：`frontend/`，Vue 3 + Vite，路由在 `frontend/src/router/index.js`。
- 通用部署模板：`docker-compose.example.yml`。
- NAS 生产部署目录：`/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN`，对应极空间文件管理里的 `/42/docker/AVGARDEN`。

## 配置边界

- 真实 `.env`、`cfg/configs.json`、`db/`、`logs/`、媒体目录、Cookie、Token、API key、webhook 不应提交。
- 公开部署应从 `.env.example` 和 `cfg/configs.json.example` 复制配置。
- qBittorrent 默认保存目录必须和 `AV_GARDEN_DATA_DIR` 指向同一份存储。
- 容器内路径建议保持：
  - `/data`：视频库
  - `/db`：运行状态和 SQLite
  - `/app/cfg`：运行配置
  - `/app/logs`：日志

## 重要产品规则

- `/api/queue-status` 不展示成功项。
- 失败项只展示最近一周内的失败记录。
- 下载管理页只保留最近一周的完成历史展示；不要删除视频文件。
- Queue API 的删除默认只移出记录；只有显式 `delete_files=1` 才允许删除文件。
- 下载流程必须是：有磁链就交给 qB；只有未找到磁链才转在线流。
- 手动刮削按钮触发的是 worker 容器内的 `weekly_updater.py`，不要让 Go server 直接依赖 Python 环境。
- 屏蔽演员、屏蔽标签、收藏演员、标题关键词是持久化配置，改动前要确认对应接口和文件。

## 每日推荐图片刮削规则

- 每日推荐封面和详情预览图应尽量本地化到 `/data/__weekly__/{番号}/`，前端优先使用 `/file/__weekly__/...`，避免用户浏览时再等外站图片。
- JavBus 详情页样张来自 `<a class="sample-box" ...>`；如果详情页没有 `sample-box`，不要把它当作下载失败，先确认源站是否本来没有预览图。
- DMM 图片源优先保留现有 `.co.jp` 路径，但下载失败时要尝试 `.com` / `awsimgsrc.dmm.com` 变体。
- MGStage 图片源常见域名是 `image.mgstage.com`；这类图不要只用 JavBus Referer 和代理下载，应优先直连，并尝试 `https://www.mgstage.com/product/product_detail/`、`https://www.mgstage.com/`、空 Referer，再兜底代理。
- `queue_api.py` 的在线/weekly 精确番号归一化不能套用本地文件夹清洗规则；`300MIUM-1395` 这类数字开头的真实番号必须保留，只有本地文件夹名清洗场景才把 `857OMG-032` 这类源站前缀还原成 `OMG-032`。
- 只补用户当前筛选出的 weekly 条目时，应从 `/api/weekly`、`/api/queue/`、`/api/weekly-watched` 复现前端筛选结果；不要扩大到全量 `weekly.json`。

## 前端设计规则

当前视觉方向是粉白色 A/GARDEN：

- 保持粉白色身份，不要改成深色后台、紫蓝渐变或通用 SaaS 风格。
- 使用白色/浅粉表面、玫瑰色细边框、紧凑卡片、8px 卡片圆角。
- 日志、下载队列、设置等操作页要融入 UI，不要出现大块黑色终端背景。
- 不要使用 emoji 作为主要 UI 图标或状态文案。
- 成功、警告、失败、下载中使用既定语义色，不要随意新增色系。
- 不编造卡片、统计数字、演员、媒体数据；没有真实数据就保持空状态。

## 常用验证命令

前端：

```bash
cd frontend
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

Compose 部署验证：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
curl -sS http://127.0.0.1:31471/api/version
curl -sS http://127.0.0.1:31471/api/queue-status
```

## Git 与 Changelog 规则

- 本仓库已初始化本地 Git；不要为“初始化”重复创建仓库。
- 每次功能完成后，先完成本地验证，并把变更写入根目录 `CHANGELOG.md` 的 `Unreleased` 区。
- 完成后让用户手动测试确认；用户确认前不要自动 commit。
- 用户确认测试通过后，先询问是否 commit；得到明确同意后再 stage 和 commit。
- commit 必须按功能拆分并保持范围干净，不要把无关改动或用户已有改动混进去。
- 如果 `CHANGELOG.md` 过长，将较早的已发布条目归档到 `docs/changelog-archive/`，并在 `CHANGELOG.md` 保留归档链接。

## 高风险操作

以下操作必须单独确认后再做：

- 数据迁移、数据库结构变化、批量清理、删除视频文件。
- 改下载策略、队列状态机、失败恢复、fallback 源或 qB 行为。
- 改部署路径、端口、`.env`、Docker Compose 服务名或挂载。
- 引入新服务、新依赖或新架构。
