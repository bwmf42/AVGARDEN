# A/GARDEN 交接（当前）

更新时间：2026-07-29

## 权威入口

- 项目规则：`AGENTS.md`；本机 `CLAUDE.md` 软链到该文件。
- 安装与公开说明：`README.md`、`INSTALL.md`。
- 变更记录：`CHANGELOG.md` 的 `Unreleased`。
- 完整审计结果：`docs/code-audit-2026-07-28.md`。
- 运维流程：`tools/maintenance/README.md` 和已安装的 `avgarden-ops` skill。

## 当前发布状态

- 本地 `main`、GitHub `main` 和 NAS 生产源码已对齐。
- Server 与 Worker 容器均为 `Up`；Server 对外端口 31471，Queue API 31473 仅容器网络可达。
- 生产媒体库 `/api/videos` 当前返回 218 部；媒体数量会随 qB 在途任务变化。
- 首次 30 天保留清理后，Weekly 原始数据为 967 条、API 可见 496 条、已看记录 1,010 条；Weekly 图片目录 496 个，孤儿和屏蔽图片目录都为 0。
- qB `missingFiles` 为 0，剩余任务分类全部为 `AV_GARDEN`。
- 本次部署替换且无容器引用的 Server/Worker 旧镜像各 1 个已精确删除，其他项目镜像未处理。

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

## 数据清理记录

- 主 manifest：`/db/maintenance/manifests/storage-cleanup-final-v2-20260729.json`
- 主结果：同路径追加 `.result.json`
- 媒体报告：`/db/maintenance/reports/main-video-ffprobe-20260729.json`
- 备份目录：`/db/backups`，权限 `700`
- 实际释放约 13.47 GiB 已分配空间。
- Weekly 保留 manifest：`/db/maintenance/manifests/weekly-retention-initial-20260729.json`
- Weekly 保留结果：同路径追加 `.result.json`；删除 844 条过期 Weekly、1,605 条过期已看记录和 1,315 个过期/屏蔽图片目录，释放约 795.66 MiB。
- 本次备份：`/db/backups/weekly-retention-index-20260729-040927.json.gz` 和 `weekly-retention-watched-20260729-040927.json.gz`。

`MIKR-109`、`PRED-886`、`SNOS-264` 已重新入队，`DEBZ-015` 原任务保留。它们的进度会继续变化，不应把本文件中的瞬时状态当固定验收值。

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

## 待观察

仅剩下载运行态：`SNOS-264`、`DEBZ-015`、`MIKR-109`、`PRED-886` 尚未全部结束。进度会继续变化，不应作为固定验收值。
