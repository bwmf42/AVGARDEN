# A/GARDEN 交接（当前）

更新时间：2026-07-29

## 权威入口

- 项目规则：`AGENTS.md`；本机 `CLAUDE.md` 软链到该文件。
- 安装与公开说明：`README.md`、`INSTALL.md`。
- 变更记录：`CHANGELOG.md` 的 `Unreleased`。
- 完整审计结果：`docs/code-audit-2026-07-28.md`。
- 运维流程：`tools/maintenance/README.md` 和已安装的 `avgarden-ops` skill。

## 当前发布状态

- 本地 `main` 与 GitHub `main` 已对齐；增量部署功能基线为 `be7ce5b`，之后的提交只同步知识面。NAS 的部署脚本和 Worker Dockerfile 与本地现役文件哈希一致。
- Server 与 Worker 容器均为 `Up`；Server 对外端口 31471，Queue API 31473 仅容器网络可达。
- 2026-07-29 实测 Worker 单服务构建 58-59 秒、完整部署 82-90 秒、无变化部署 2 秒；Worker 镜像为 13 层且不含现役 `cfg/configs.json`。
- 媒体、Weekly、已看和 qB 数量都是运行时数据，不在交接文档固定记录；以生产 API 和 qB 当前状态为准。

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

## 数据清理记录

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

两种工具都必须保留 manifest 和结果；不得用模糊匹配删除运行数据。

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
