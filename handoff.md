# AVGARDEN 交接（当前）

更新时间：2026-07-23

## 规则真身

- **`AGENTS.md` 为项目规则真身**；`CLAUDE.md` 是指向它的软链（勿再维护两份正文）。
- 变更记录：`CHANGELOG.md` → `Unreleased`。

## 当前能力摘要

### 每日推荐

| 项 | 现状 |
|----|------|
| 列表源 | 98堂 `forum-37`，默认 3 页（`WEEKLY_LIST_SOURCE=plwt`） |
| 中文日常 | `forum-103`，默认 2 页 → `replace_chinese` 进帖取磁链 |
| 封面/预览 | **javdatabase → MGS 图 → DMM CDN → JavBus/URL**（`src/weekly/artwork.py`） |
| 元数据 | MGS 表字段 → JavBus 补缺 → artwork 落盘（`enrich.py` + `genre_zh.py`） |
| 已看同步 | `/db/weekly_watched.json` + `/api/weekly-watched`（跨域名共享） |
| 未看列表 | `/api/weekly`（已滤屏蔽标签/演员）− 已看 − 队列 − 已下载；前端约 **未看 492** |

### 图源细节

- **javdatabase**：`/movies/{code小写}/`，无需年龄 Cookie；**NAS 必须 `PROXY`**（直连超时）。
- **MGS**：`pb_e` / `cap_e_*`；SIRO/ABF 等独占片 javdatabase 常 404；日本代理 only。
- **DMM**：cid 探测放最后；无真实封面的 cid 不扫 `jp-N`；拒绝 NOW PRINTING 占位。
- 环境变量见 `.env.example`：`ARTWORK_SKIP_*`、`JAVDATABASE_DELAY`、`BACKFILL_*`。

### 回填脚本

| 脚本 | 用途 |
|------|------|
| `plwt_art_backfill.py` | 封面+预览；默认 `BACKFILL_UNWATCHED_ONLY=1`（未看 scope） |
| `weekly_backfill_details.py` | 元数据/磁链等，同未看 scope |

Worker 内示例：

```bash
# 日志 /tmp/plwt_art_backfill.log
PYTHONPATH=/app JAVDATABASE_DELAY=0.25 BACKFILL_UNWATCHED_ONLY=1 \
  /app/venv/bin/python3 -u /tmp/plwt_art_backfill.py
```

（脚本也可放在镜像 `/app/plwt_art_backfill.py`，视部署是否 COPY。）

## NAS 部署

- 目录：`/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN`
- 访问：`http://192.168.5.14:31471`（远程视 zconnect）
- 部署：`bash deploy.sh` 需 `AVGARDEN_PASS`；或 `ssh zspace` rsync + `docker compose build/up`
- 容器：`avgarden-server`、`avgarden-worker`；worker 环境含 `PROXY=http://192.168.5.14:7890`

## 本阶段已落地（相对 2026-06 handoff）

- [x] 已看服务端同步（`weekly_watched`）— 线上在用
- [x] 列表改 plwt forum-37；中文 forum-103
- [x] javdatabase 优先图源 + MGS/DMM 链路；PROXY 环境继承
- [x] 未看范围图回填（非全量 1000+）
- [x] AGENTS 真身 + CLAUDE 软链

## 进行中 / 可跟进

- [ ] 未看缺图回填跑完后，按需再开 **元数据 enrich** 回填（`weekly_backfill_details.py`）
- [ ] 个别番号 javdatabase/MGS/DMM 皆无图时仅 JavBus 或空
- [ ] `plwt_art_backfill.py` 是否正式 COPY 进 worker 镜像（当前可 docker cp / 挂载）

## 相关文件（本能力）

```
src/weekly/artwork.py
src/weekly/javdatabase.py
src/weekly/mgs.py
src/weekly/dmm.py
src/weekly/enrich.py
src/weekly/genre_zh.py
src/weekly/chinese_forum.py
plwt_art_backfill.py
weekly_backfill_details.py
weekly_updater.py
replace_chinese.py
AGENTS.md          # 真身
CLAUDE.md          # -> AGENTS.md
.env.example
CHANGELOG.md
```

## 验证

```bash
python3 -m unittest test_artwork_sources -v
curl -sS http://192.168.5.14:31471/api/weekly | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
curl -sS http://192.168.5.14:31471/api/weekly-watched | python3 -c "import json,sys; print(len(json.load(sys.stdin)))"
```
