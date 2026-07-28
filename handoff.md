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
- 生产媒体库 `/api/videos` 返回 220 部；220 个主视频全部通过 `ffprobe`。
- 原始 Weekly 为 1,811 条、已看历史为 2,017 条；Weekly 孤儿目录为 0。
- qB `missingFiles` 为 0，剩余任务分类全部为 `AV_GARDEN`。
- 本轮替换且无容器引用的 7 个旧镜像已删除，其他项目镜像未处理。

## 关键运行规则

- 用户输入番号与本地目录解析分开；数字前缀是真实番号的一部分，确认的来源前缀才可在本地解析时剥离。
- 旧短 qB 标签可通过只读别名找到数字前缀目录；本地 `CH` 字幕后缀折叠到基础番号。
- 主视频统一为递归 MP4、至少 100 MiB、实际分配至少 95%；普通作品选最大文件，多段优先第 1 段。
- qB 下载态始终有效；完成态只有磁盘存在有效主视频时才阻止恢复下载。
- 有磁链只走 qB；只有没有磁链时才允许在线流回退。
- 全部 `weekly.json` 写入使用跨进程锁和原子替换；无变化任务不得重写文件。
- `__online__` 缓存 TTL 为 24 小时，并每小时后台清理。

## 数据清理记录

- 主 manifest：`/db/maintenance/manifests/storage-cleanup-final-v2-20260729.json`
- 主结果：同路径追加 `.result.json`
- 媒体报告：`/db/maintenance/reports/main-video-ffprobe-20260729.json`
- 备份目录：`/db/backups`，权限 `700`
- 实际释放约 13.47 GiB 已分配空间。

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

仅剩下载运行态：`DEBZ-015` 与三条恢复任务尚未全部结束。代码、数据清理、文档同步、Git 推送和生产部署均已完成。
