# A/GARDEN 交接（当前）

更新时间：2026-07-23

## 权威入口

- 项目规则真身：`AGENTS.md`；`CLAUDE.md` 是指向它的软链。
- 变更记录：`CHANGELOG.md` 的 `Unreleased`。
- 运维 skill：`codex-agent/skills/avgarden-ops/SKILL.md`，安装副本位于 `~/.codex/skills/avgarden-ops/SKILL.md`。
- 历史交接：`docs/handoff-2026-06-10.md`，只用于查历史，不代表现役状态。

`docs/deploy-zspace.md` 和 `codex-agent/` 由 `.gitignore` 明确设为本机运维资料，不进入公开仓库；公开安装说明以 `README.md`、`INSTALL.md` 和示例配置为准。

## 当前发布状态

- 本地 `main` 与 `origin/main` 当前都在 `7545ee1`。
- 每日推荐元数据、图片和原子写入改动已经部署到 NAS worker，但仍在本地工作树中，尚未 commit/push。
- 生产 worker 内相关 Python 文件与本地工作树 SHA-256 一致。
- 2026-07-23 验证：43 项 weekly 相关测试通过，Python 编译与 `git diff --check` 通过。
- 下一步是手动测试；确认后再按项目规则询问是否 commit/push。

## 每日推荐现役流程

| 项 | 现状 |
|----|------|
| 列表 | 98堂 `forum-37`，默认 3 页；`WEEKLY_LIST_SOURCE=javbus` 仅作回退 |
| 中文资源 | `forum-103`，默认 2 页；只对缺中文的库内条目进已知帖子找磁链 |
| 元数据 | MGS 有标签时以 MGS 为准；MGS 完全无标签才查精确 DMM；DMM 无商品时用 JAV Database 精确页兜底 |
| 封面/预览 | JAV Database -> MGS 商品图 -> DMM 精确商品 -> 已知论坛帖子附件 -> 条目已有 URL |
| 演员 | 同时读取 DMM 标准演员和素人演员字段；来源没有演员时保持空白，不从标题猜 |
| 本地图片 | `/data/__weekly__/{番号}/`，前端优先使用 `/file/__weekly__/...` |
| 未看 | 未下载条目长期累积；前端再减去已看、队列、已下载和屏蔽项 |
| 写入安全 | `weekly_updater.py` 与回填脚本共用文件锁，并通过唯一临时文件原子替换 `weekly.json` |

JavBus 的访问实现仍保留，但当前不参与主动元数据和图片候选。磁链日常默认走 Sukebei；中文资源只在已有论坛目标上进帖。

## 回填脚本

| 脚本 | 用途 |
|------|------|
| `plwt_art_backfill.py` | 补封面和预览；默认 `BACKFILL_UNWATCHED_ONLY=1` |
| `weekly_backfill_details.py` | 补真正缺失的元数据、磁链、翻译和本地图片；逐条保存 |

两个脚本均已由 `Dockerfile.worker` 复制到 worker 的 `/app/`，使用 `/app/venv/bin/python3` 运行。

2026-07-23 运行态快照：`/api/weekly` 返回 963 条可见记录，缺封面 0 条、缺本地预览 8 条。演员为空不一定是失败，部分官方商品本来就不提供演员字段；数量会随每日更新变化，不应当作固定验收值。

## NAS 部署

- 本地仓库：`/Users/vigo/Desktop/code/AVGARDEN`
- NAS 现役目录：`/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN`
- 极空间界面路径：`/42/docker/AVGARDEN`
- 服务：`http://192.168.5.14:31471`
- 部署：运行时传入 `AVGARDEN_PASS` 后执行 `bash deploy.sh`，或通过 `ssh zspace` 在现役目录执行 Compose。

部署后必须先确认容器、版本、队列和相关页面/API 正常，再核对镜像引用，只删除本次替换且未被容器引用的 A/GARDEN 旧镜像。不要使用宽泛的 Docker prune。

## 本轮工作树范围

核心改动集中在：

```text
Dockerfile.worker
weekly_store.py
weekly_updater.py
weekly_backfill_details.py
plwt_art_backfill.py
src/weekly/artwork.py
src/weekly/chinese_forum.py
src/weekly/dmm.py
src/weekly/enrich.py
src/weekly/genre_zh.py
src/weekly/javdatabase.py
src/weekly/merge.py
src/weekly/mgs.py
test_artwork_sources.py
test_genre_meta.py
test_weekly_backfill_details.py
test_weekly_store.py
```

其中 `weekly_store.py`、`test_weekly_store.py`、`test_weekly_backfill_details.py` 当前尚未被 Git 跟踪，但生产 worker 已依赖 `weekly_store.py`，提交时必须纳入。

## 验证命令

```bash
PYTHONPYCACHEPREFIX=/private/tmp/avgarden-pycache python3 -m py_compile \
  weekly_updater.py weekly_backfill_details.py weekly_store.py \
  src/weekly/artwork.py src/weekly/dmm.py src/weekly/enrich.py

python3 -m unittest \
  test_artwork_sources test_genre_meta \
  test_weekly_backfill_details test_weekly_store -v

ssh zspace 'cd /tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN && \
  sudo /usr/bin/docker compose ps && \
  curl -fsS http://127.0.0.1:31471/api/version && \
  curl -fsS http://127.0.0.1:31471/api/queue-status'
```
