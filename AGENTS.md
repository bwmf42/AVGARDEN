# A/GARDEN Agent Guide

本文件是项目 **规则真身**（`CLAUDE.md` 为其软链）。供 AI agent 与维护者快速理解、配置和验证。

## 项目定位

面向 NAS / 家庭服务器的媒体下载、整理和浏览：

- 用户输入番号或从每日推荐选择；Worker 优先用 weekly 磁链交 qBittorrent，无磁链再 fallback 在线流。
- 完成后刮削 NFO / 封面 / 预览；Go API + Vue 前端浏览管理。

## 快速参考

| 操作 | 命令 |
|------|------|
| 部署 | `AVGARDEN_PASS=… bash deploy.sh`（或 `ssh zspace` rsync + compose） |
| 状态 | `curl -s http://192.168.5.14:31471/api/videos` |
| Worker 日志 | `ssh zspace 'sudo docker logs avgarden-worker --tail 40'` |
| 周更新 | `docker exec avgarden-worker … weekly_updater.py` |
| 未看图回填 | worker 内 `plwt_art_backfill.py`（默认 `BACKFILL_UNWATCHED_ONLY=1`） |

## 关键入口

| 组件 | 路径 / 端口 |
|------|-------------|
| Go API + 前端 | `backend/main.go`、`handlers.go` → **31471** |
| Queue API | `queue_api.py` → **31473** |
| Worker / 入口 | `worker.py`、`launcher.py` |
| 每日推荐 | `weekly_updater.py` + `src/weekly/` |
| 元数据 | `metadata.py`、`src/scraper.py` |
| 前端 | `frontend/`（Vue 3 + Vite） |
| NAS 部署 | `/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN`（极空间 `/42/docker/AVGARDEN`） |
| qB | NAS **8888** |

### `src/weekly/` 模块

- `sources.py` / `chinese_forum.py` — 列表（默认 plwt forum-37；中文 forum-103）
- `artwork.py` — 封面预览：javdatabase → MGS → DMM → 已知论坛帖附件
- `javdatabase.py` / `mgs.py` / `dmm.py` / `javbus.py`
- `enrich.py` / `genre_zh.py` — 元数据与标签中文映射
- `sukebei.py` / `merge.py`

## NAS 要点

- IP `192.168.5.14`；SSH 常用别名 `zspace` 或 `13049108160@192.168.5.14 -p 10000`
- 媒体库与 qB 保存目录须同一挂载；容器 `/data` `/db` `/app/cfg` `/app/logs`
- 出站刮削依赖 `PROXY`（mihomo 日本节点）；javdatabase / MGS / DMM 直连常失败

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
- Queue API 删除任务时必须先发送 Worker 取消信号并移除匹配的 qB 任务，再移出队列记录；默认保留已有文件，只有显式 `delete_files=1` 才允许删除文件。
- **队列 UI 状态**：以 `queue_state.json` 登记 + `/api/queue` 为准；qB 的 `queuedDL` 必须算在途；扫 qB 优先用 torrent **tags**（worker 写入番号）。前端只读 status API，不直连 qB。
- 用户输入番号的安全校验和本地文件夹名清洗必须分开：输入层支持无横杠、数字开头和已知特殊系列，但只允许归一化后的安全路径组件；本地文件夹清洗可以处理来源前缀，不能反过来改写用户输入的真实数字前缀。
- 下载流程必须是：有磁链就交给 qB；只有未找到磁链才转在线流。
- 手动刮削按钮触发的是 worker 容器内的 `weekly_updater.py`，不要让 Go server 直接依赖 Python 环境。
- 屏蔽演员、屏蔽标签、收藏演员、标题关键词是持久化配置，改动前要确认对应接口和文件。

## 每日推荐列表与图片刮削规则

- **列表源（默认）**：98堂 `https://plwt.kpqq4.com/forum-37-1.html`（`WEEKLY_FORUM_FID=37`，默认 **3 页** `WEEKLY_MAX_PAGES`）。实现：`sources.get_recent` → `chinese_forum.get_weekly_list`。
- **中文资源日常**：同站 `forum-103`，默认 **2 页**（`CHINESE_FORUM_DAILY_PAGES`），`replace_chinese` 在 weekly 之后跑；缺中文才进帖取磁链。
- JavBus 访问代码保留但当前不参与元数据和主动图片候选；磁链默认 sukebei（中文板缺磁链时才进帖）。
- 每日推荐封面和详情预览图应尽量本地化到 `/data/__weekly__/{番号}/`，前端优先使用 `/file/__weekly__/...`，避免用户浏览时再等外站图片。
- **封面/预览图源优先级（`src/weekly/artwork.py`）**：
  1. **javdatabase**：`https://www.javdatabase.com/movies/{番号小写}/` → DMM `pl.jpg` / `og:image` + 页内 `jp-N`（无年龄 Cookie；NAS **必须走 `PROXY`**，直连常超时）。
  2. **MGS 商品图**（单页快路径）：`pb_e` / `cap_e_*` — **SIRO / ABF 等 MGS 独占** javdatabase 常 404，靠这一层；也是标签元数据主源。
  3. **DMM 精确搜索**（放最后）：传统 DVD 读静态商品表格；数字商品走 `https://api.video.dmm.co.jp/graphql`，同时读取标准 `actresses` 和素人 `amateurActress`。搜索页漏结果时把常见 CID 在一次 GraphQL 请求内批量查询，并以 `makerContentId` 二次校验番号；未知厂商前缀只借 javdatabase 页内真实 `Content ID` 定位。**无真实封面的 cid 不要扫样片**；拒绝 NOW PRINTING 占位图。
  4. **已知 98堂帖子附件**：前三层都没有所需图片时，才进该条已有 `forumUrl`，首图作封面、后续附件作预览；不为此扫描无关帖子。
  5. **条目已有 URL** 兜底。JavBus 访问技巧保留，但当前不主动请求。
- **详情元数据（`src/weekly/enrich.py`）**：
  - 字段：演员、标签、发行日、时长、字幕、封面/预览、`titleZh`
  - 顺序：MGS 表字段；MGS 完全没有标签时才用 DMM 精确商品元数据补空字段；DMM 搜索与精确 CID 均没有商品时，最后使用 javdatabase 精确番号页的演员、标签、时长 → **artwork 下载图**（上表优先级）。JavBus 代码保留但当前不参与候选。
  - MGS/DMM 日文标签和 javdatabase 英文标签经 `genre_zh.py` 对齐库内名称；**NTR 保持 NTR**；来源没有演员时保持空白，不从标题猜名字。
  - 标题：`weekly_updater.batch_translate`（DeepSeek → `titleZh`）
- 回退列表源：`WEEKLY_LIST_SOURCE=javbus`。
- **回填范围**：默认只补前端 **未看**（`/api/weekly` 已滤屏蔽标签/演员 − 已看 − 队列 − 已下载）。脚本 `plwt_art_backfill.py`（`BACKFILL_UNWATCHED_ONLY=1`）；全量才设 `0`。元数据回填用 `weekly_backfill_details.py`（同 scope）。
- JavBus 无 `sample-box` 时不要当下载失败。DMM 图优先 `.co.jp`，失败试 `.com` / `awsimgsrc`。
- MGS：`PROXY` 只走日本代理，禁止直连优先。
- `queue_api` 在线/weekly 番号归一化保留真实数字前缀（如 `300MIUM-1395`）；仅本地文件夹清洗可剥源站前缀。

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
PYTHONPYCACHEPREFIX=/private/tmp/av-garden-pycache python3 -m py_compile \
  worker.py queue_api.py launcher.py weekly_updater.py metadata.py replace_chinese.py \
  plwt_art_backfill.py weekly_backfill_details.py \
  src/weekly/artwork.py src/weekly/javdatabase.py src/weekly/dmm.py src/weekly/mgs.py \
  src/weekly/enrich.py src/weekly/sukebei.py
python3 -m unittest test_artwork_sources -v
```

Compose 部署验证：

```bash
docker compose -f docker-compose.example.yml --env-file .env ps
curl -sS http://127.0.0.1:31471/api/version
curl -sS http://127.0.0.1:31471/api/queue-status
```

## 部署后镜像清理

- 新容器必须先确认处于 `Up`，且版本、队列等关键接口健康，再清理被替换的旧镜像。
- 清理前核对所有容器实际引用的 image ID，只删除未被引用的旧 `avgarden-server` / `avgarden-worker` 镜像。
- 不使用 `docker image prune -a` 等宽泛清理命令，不删除当前镜像、其它项目镜像或仍被容器引用的共享镜像；清理后再次检查容器和接口。

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

## Agent 文档索引

- Issue tracker：`docs/agents/issue-tracker.md`（GitHub Issues `bwmf42/AVGARDEN`）
- Triage labels：`docs/agents/triage-labels.md`
- Domain / ADR：`docs/agents/domain.md`
- 交接快照：根目录 `handoff.md`（当前会话状态，可随功能更新）
