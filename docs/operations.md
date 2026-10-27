# A/GARDEN 运维、部署与版本对齐

本页保留原 Agent Guide 的运维规则；极空间完整操作步骤见 [deploy-zspace.md](deploy-zspace.md)。关键入口表中的 `handlers.go` 位于 `backend/`。

## 快速参考

| 操作 | 命令 |
|------|------|
| 在家 Mac 部署 | `AVGARDEN_PASS=… bash deploy.sh`（rsync→NAS；可 `AVGARDEN_DEPLOY_SERVICES=server\|worker\|all`） |
| 外面飞书 / NAS 本地部署 | `bash deploy_local.sh`（`server`/`worker`/`all`；`AVGARDEN_HOT=1` 热补 worker；**不要**跑 Mac `deploy.sh`） |
| 版本对齐 | `./check_version.sh`（Mac vs 运行中 `/api/version`） |
| 状态 | `curl -s http://192.168.5.17:31471/api/videos` |
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

## NAS 要点

- IP `192.168.5.17`；SSH 常用别名 `zspace` 或 `13049108160@192.168.5.17 -p 10000`
- 媒体库与 qB 保存目录须同一挂载（现为 `…/data/data2/115生活备份` → 容器 `/data`）；`/db` `/app/cfg` `/app/logs`。115 云下载与极空间同步是独立链路，不得将其同步目录软链接或映射进本地媒体库。
- 出站刮削依赖 `PROXY`（mihomo mixed-port）；javdatabase / MGS / DMM 走固定 rules（日本组等）
- mihomo：**订阅** `Clash_sub_v2.yaml` vs **固定** `config.yaml`（groups/rules）。98堂 `url-test` 组与 `kpqq4.com`/`plwt` 规则见 [`docs/mihomo-fixed-snippet.yaml`](../docs/mihomo-fixed-snippet.yaml)；勿用订阅覆盖固定配置
- 前台系统日志默认只读 `av-garden.log`（入队/开始/完成/失败）；明细在 loguru 日文件 / docker logs，`/api/logs?debug=1` 可看全量；日志保留约 **30 天**
- **自愈** `heal_runner.py`（launcher 默认每 1h）：补缺 `titleZh`、队列/qB 状态对齐、qB/翻译服务/98堂/115 Cookie 探活告警。翻译服务按 `TRANSLATE_*` 中继优先、DeepSeek 回退。115 Cookie 失效只黄不红，前台 `/api/p115/config` 带 120s 缓存活探测。**不**次日自动重刮、**不**自动删种。开关：`HEAL_ENABLE`、`HEAL_TITLEZH`、`HEAL_QUEUE_SYNC`、`HEAL_PROBE`、`HEAL_INTERVAL_H`
- mihomo **98堂** url-test 候选含日本（暂时失败的节点会被测活跳过）
- 一次性存储清理只能通过 `tools/maintenance/storage_cleanup.py` 的 dry-run manifest → apply 两阶段执行；日常 Weekly 图片清理使用 `weekly_cache_maintenance.py`，默认只处理不在当前 JSON 且超过 30 天的直接子目录。两者都必须保留 manifest/结果并在应用前重新验证签名和运行态。

## 版本对齐（Mac vs NAS）

部署前/回家后先核对本地源码是否与正在跑的 NAS 构建一致，避免“以为改了其实线上还是旧的”：

```bash
./check_version.sh              # local vs http://192.168.5.17:31471/api/version（分 server/worker）
./check_version.sh --nas-tree   # 额外 ssh zspace 指纹 NAS 现役源码目录
```

- 身份由 `tools/build_identity.sh` 计算：
  - `tree_hash_server` — Go/Vue/Dockerfile.server/VERSION
  - `tree_hash_worker` — Python/src/requirements/Dockerfile.worker
  - `tree_hash` — 两侧组合（兼容旧逻辑）
  - `git_dirty` — **仅**当未提交改动落在指纹路径内时为 true
- `deploy.sh` / `deploy_local.sh` 写 `BUILD_INFO.json` 并 `docker cp` 进 server；`/api/version` 透传 BUILD_INFO 字段。
- `check_version` 结果：`MATCH` / `SERVER_MISMATCH` / `WORKER_MISMATCH` / `BOTH_MISMATCH` / `UNKNOWN`。
- 退出码：`0` 两侧对齐、`1` 不对齐或部分对齐或 identity dirty、`2` API 不可达。

## 飞书 / Hermes 部署（NAS 本地）

- 脚本：[`deploy_local.sh`](../deploy_local.sh)；技能：[`skills/avgarden-deploy/SKILL.md`](../skills/avgarden-deploy/SKILL.md)
- Hermes 内路径：`/opt/data/projects/AVGARDEN`（bind-mount 到 NAS 现役树）
- **禁止**在 Hermes 里跑 Mac 的 `deploy.sh`（依赖 rsync/sshpass）
- Hermes `hermes-agent` 需要挂载：`AVGARDEN` 目录 + `/var/run/docker.sock`（见 skill 文末）

## 部署后镜像清理

- `deploy.sh` 会先对比临时目录和现役源码，Python/Worker 输入只构建 `worker`，Go/前端输入只构建 `server`，Compose 或未知运行时文件才重建两者；纯文档变化不重启容器。
- Docker 构建输出写入 NAS `/tmp` 临时日志，成功时只打印末尾摘要并删除日志，失败时保留日志并输出末尾内容；不要恢复持续传输完整 BuildKit 输出的做法。
- 新容器必须先确认处于 `Up`，且版本、队列等关键接口健康，再清理被替换的旧镜像。
- 清理前核对所有容器实际引用的 image ID，只删除未被引用的旧 `avgarden-server` / `avgarden-worker` 镜像。
- 不使用 `docker image prune -a` 等宽泛清理命令，不删除当前镜像、其它项目镜像或仍被容器引用的共享镜像；清理后再次检查容器和接口。
