# A/GARDEN 交接（当前）

更新时间：2026-10-23（Asia/Shanghai）；源码基线 `main@230af03`。

## 权威入口

- 项目规则：`AGENTS.md`；本机 `CLAUDE.md` 软链到该文件。
- 安装与公开说明：`README.md`、`INSTALL.md`。
- 变更记录：`CHANGELOG.md` 的 `Unreleased`。
- 完整审计结果：`docs/code-audit-2026-07-28.md`。
- 运维流程：`tools/maintenance/README.md` 和已安装的 `avgarden-ops` skill。

## 当前状态与最近工作

本次仅同步交接文档。开始时 tracked 工作树只有 `AGENTS.md`、`handoff.md` 两处未提交的文档改动；本地 HEAD 与缓存的 `origin/main` 相同，但未 fetch、推送或检查 NAS，不能据此宣称远端/生产已同步。

- **2026-10-17 `03c63e1`..`230af03`**：演员身份与产品描述分离。产品昵称、年龄/职业描述、DMM 素人署名、泛类别（个人拍摄、情侣等）和仅从标题推断的短名，只作为普通演员描述保留，不进入收藏/屏蔽/跳转；正式署名仍有效，演员偏好 API 拒绝新的描述类标签。Weekly 详情保存演员/标签块后保持展开，需显式完成或离开确认，并沿原筛选顺序继续浏览。
- **2026-10-17 `56089a2` / `d7a1a37` / `d756d65` / `81ab715`**：115 任务由 Queue API 内独立串行通道提交，不占本地下载锁；状态显示实际通道（qB / 在线流 / 115）；传输通道标签适配活动栏；详情预览图不再等懒加载；媒体目录日期锚点贯穿刮削与中文合并，新增带签名、可回滚的目录日期修复工具，视频文件时间戳不动。
- **2026-10-12 `94191b9` / `e4a03b4`**：修正健康告警（115 功能关闭时 Cookie 不再误报，失败记录按 NAS 当前时钟过期），未看中文补链超时随候选数缩放；同步 NAS 上已有的 98堂安全门会话复用热补丁。
- **2026-10-01 至 10-02 `d7d5777`..`fa6aa96`**：每日推荐新增筛选流程（浏览状态、字幕、演员/收藏、标签、时长、发行日、本地可用性），去掉「想看/不感兴趣」入口；屏蔽演员/标签/关键词/收藏演员支持持久删除；队列删除在 qB 不可用或任务在途时拒绝执行；Weekly 列表从详情返回时缓存 1 分钟，偏好变化或入队成功后立即失效。
- **2026-09-21 `f8cfc43` / `5b10896`**：删除 115 同步目录自动链接链路；Go 的媒体缓存与队列媒体索引统一跳过外部同步目录。显式选择的 115 云下载能力仍保留，云同步不能再当作本地媒体库扫描来源。
- **2026-09-17 `53f346e`**：队列 POST 的 `request_id` 幂等与在途去重；GET/POST 缩小锁范围，隔离慢 I/O。Worker 仍串行处理，不能把 API 并发改进理解成并行下载。
- **2026-09-17 `83863bb` / `094cd74`**：Go/Queue API 贯通请求 ID 与耗时诊断，默认只记录慢请求；`4a63429` 记录已有健康级别、NAS 地址和部署工具调整。
- **2026-08-30 `8a5a2e9` / `77ce122` / `3d24c32`**：拒绝无效中文翻译、翻译中继到 DeepSeek 回退、改进标题清理与重试。
- **2026-08-13 `16d5484` / `8f22454`**：统一刮削及未看中文补链流程，强化媒体替换、路径、状态写入与运行依赖处理。

证据入口：[CHANGELOG.md](CHANGELOG.md)、[queue_api.py](queue_api.py)、[backend/main.go](backend/main.go)、[backend/handlers.go](backend/handlers.go)、[weekly_updater.py](weekly_updater.py)、[run_scrape_followups.py](run_scrape_followups.py)。长期规则以 [AGENTS.md](AGENTS.md) 为准。

## 本次验证与下一步

- `verified-current`：核对本地提交、相关源码、项目规则与工作树。
- `changed-and-verified`：交接快照与本地引用检查。
- `pending`：本次没有跑 Python/Go/前端功能测试；没有检查 NAS 版本、接口或容器。下方命令是后续验证入口，不是本次已通过记录。
- `out-of-scope`：部署、运行数据、清理、远端同步；长期记忆只读。

接手时先运行 `./check_version.sh` 核对 server/worker 身份，再按任务选择验证；队列排错先按请求 ID 定位慢阶段。Git 还登记了一条 `prunable` 的旧 safe-scrape worktree，本次仅记录，未删除或 prune。

## 历史发布证据（2026-07-29，未重新验证）

旧交接曾记录 `be7ce5b` 增量部署基线、容器 Up、源码哈希一致和部署耗时。这些属于当日验收，不代表 2026-10-23 生产状态。下方清理记录同样仅供事故追溯，不代表当前队列或再次清理授权。

## 关键运行规则

- 用户输入番号与本地目录解析分开；数字前缀是真实番号的一部分，确认的来源前缀才可在本地解析时剥离。
- 旧短 qB 标签可通过只读别名找到数字前缀目录；本地 `CH` 字幕后缀折叠到基础番号。
- 主视频统一为递归 MP4、至少 100 MiB、实际分配至少 95%；普通作品选最大文件，多段优先第 1 段。
- qB 下载态始终有效；完成态只有磁盘存在有效主视频时才阻止恢复下载。
- 手动搜索/添加统一选源：98堂 `forum-103` 精确中文 → Sukebei 最大中文版 → Sukebei 上传日期最早的原版 → 在线流 → 失败。有磁链只走 qB。
- 在线搜索与 Worker 通过 `/db/download_source_cache.json` 复用解析结果；缓存默认 24 小时，未入队的在线详情离开时立即清理。98堂搜索跨进程至少间隔 31 秒。
- Worker 从队列取出番号后立即写 `current_download.txt`，Queue API 另有 120 秒登记宽限，避免顶部任务短暂消失；qB 查重和状态识别覆盖全部分类。
- 全部 `weekly.json` 写入使用跨进程锁和原子替换；无变化任务不得重写文件。
- Weekly 未看条目无限保留；手动已看从 `watched_at` 起保留 30 天，到期删除条目、图片和已看记录。
- 屏蔽条目先取最小匹配元数据并记为已看，跳过图片、磁链、翻译和下载，从收录时间起保留 30 天。
- Launcher 每天 04:30 按精确 manifest 执行保留清理并先备份；`__online__`、应用日志和日常维护记录保留 30 天。
- `deploy.sh` 先对比临时目录与现役源码，只构建并重启受影响服务；未知运行时文件安全地重建两者，纯文档和无变化部署不重启。
- Worker 构建上下文由 `Dockerfile.worker.dockerignore` 限制，必须排除 NAS 现役 `cfg/configs.json`；远端构建日志成功后删除，失败时保留供排查。

## 历史数据清理记录（2026-07-29）

- 主 manifest：`/db/maintenance/manifests/storage-cleanup-final-v2-20260729.json`
- 主结果：同路径追加 `.result.json`
- 媒体报告：`/db/maintenance/reports/main-video-ffprobe-20260729.json`
- 备份目录：`/db/backups`，权限 `700`
- 实际释放约 13.47 GiB 已分配空间。
- Weekly 保留 manifest：`/db/maintenance/manifests/weekly-retention-initial-20260729.json`
- Weekly 保留结果：同路径追加 `.result.json`；删除 844 条过期 Weekly、1,605 条过期已看记录和 1,315 个过期/屏蔽图片目录，释放约 795.66 MiB。
- 本次备份：`/db/backups/weekly-retention-index-20260729-040927.json.gz` 和 `weekly-retention-watched-20260729-040927.json.gz`。

2026-07-29 清理当时，`MIKR-109`、`PRED-886`、`SNOS-264` 被重新入队，`DEBZ-015` 原任务保留。这只是当次清理记录，不代表当前队列。

## 维护命令

一次性存储清理必须先生成并审核清单：

```bash
python3 /app/tools/maintenance/storage_cleanup.py \
  --manifest /db/maintenance/manifests/storage-cleanup.json
python3 /app/tools/maintenance/storage_cleanup.py \
  --apply /db/maintenance/manifests/storage-cleanup.json
```

日常 Weekly 图片清理默认只处理超过 30 天的无引用目录：

```bash
python3 /app/tools/maintenance/weekly_cache_maintenance.py \
  --manifest /db/maintenance/manifests/weekly-cache.json
python3 /app/tools/maintenance/weekly_cache_maintenance.py \
  --apply /db/maintenance/manifests/weekly-cache.json
```

已看/屏蔽 Weekly 保留由 Launcher 每天 04:30 自动执行；手动复核时先 dry-run：

```bash
python3 /app/tools/maintenance/weekly_retention_maintenance.py \
  --manifest /db/maintenance/manifests/weekly-retention.json
python3 /app/tools/maintenance/weekly_retention_maintenance.py \
  --apply /db/maintenance/manifests/weekly-retention.json
```

以上工具都必须保留 manifest 和结果；不得用模糊匹配删除运行数据。

## 验证基线

```bash
PYTHONPYCACHEPREFIX=/private/tmp/avgarden-pycache python3 -m unittest discover

cd backend
GOCACHE=/private/tmp/avgarden-gocache go test -race -count=1 ./...
GOCACHE=/private/tmp/avgarden-gocache go vet ./...

cd ../frontend
npm test
npm run build
npm audit --registry=https://registry.npmjs.org --audit-level=low
```

生产验证至少检查 Compose、`/api/version`、`/api/videos`、`/api/weekly`、`/api/queue-status` 和一个真实 Range 请求。

## 动态运行态

qB 下载、媒体数量和 Weekly 可见数量会持续变化。接手时直接检查 `/api/queue-status`、`/api/videos` 和 `/api/weekly`，不要把历史交接里的任务编号或数量当成当前事实。

## 2026-10-31 审计修复（未提交、未部署，待 Claude 验收）

- 身份构建进镜像（`Dockerfile.server` COPY VERSION BUILD_INFO.jso[n]）；`build_identity.sh` 不可读路径非 0 + stderr；`check_version.sh --nas-tree` 显示远端 stderr。
- 封面无远程来源不再下载本地地址；Worker 循环异常指数退避 30s→600s；首页失败标签显示 `message`。
- 每日推荐条目直接用 `weekly.json` 磁链（`worker.get_magnet_from_weekly`），其余走统一选源链。
- 新增 `test_audit_fixes.py`、前端 `downloadStatus.test.js` 用例。第 3 层（NAS 部署后 `/api/version` 含 tree_hash、`--nas-tree`、页面失败标签）未验证，待授权部署。
