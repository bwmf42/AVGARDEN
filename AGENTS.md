# A/GARDEN Agent Guide

本文件是项目 **规则真身**（`CLAUDE.md` 为其软链）。供 AI agent 与维护者快速理解、配置和验证。

## 项目定位

面向 NAS / 家庭服务器的媒体下载、整理和浏览：

- 用户输入番号或从每日推荐选择；统一选源链按 98堂中文、Sukebei、在线流依次解析，有磁链交 qBittorrent。
- 完成后刮削 NFO / 封面 / 预览；Go API + Vue 前端浏览管理。

## 命令速查

| 操作 | 命令 / 验证范围 |
|------|----------------|
| 一键验证 | `scripts/check.sh --layer 1`（默认：本地静态/单测）；`--quick` 仅 Python；`--layer 2` 只读 NAS；`--layer all` 两层；退出码 0/1/2，详见 [验证命令](docs/verification.md)，第 3 层需人工验收 |
| 在家 Mac 部署（须授权） | `bash deploy.sh`，配置与选服务详见 [运维规则](docs/operations.md) |
| 外面飞书 / NAS 本地部署（须授权） | `bash deploy_local.sh`；**禁止在 Hermes 里跑 Mac 的 `deploy.sh`**，详见 [运维规则](docs/operations.md) |
| 版本对齐 | `./check_version.sh`；额外检查 NAS 源码：`./check_version.sh --nas-tree` |
| Worker 日志 | `ssh zspace 'sudo docker logs avgarden-worker --tail 40'` |

## 关键入口

| 组件 | 路径 / 端口 |
|------|-------------|
| Go API + 前端 | `backend/main.go`、`backend/handlers.go` → **31471**；`frontend/`（Vue 3 + Vite） |
| Queue API | `queue_api.py` → **31473** |
| Worker / 入口 | `worker.py`、`launcher.py` |
| 每日推荐 / 元数据 | `weekly_updater.py`、`src/weekly/`；`metadata.py`、`src/scraper.py` |
| NAS 部署 | `/tmp/zfsv3/sata11/13049108160/data/docker/AVGARDEN`（极空间 `/42/docker/AVGARDEN`） |
| qB | NAS **8888** |

## 每次必读红线

- 真实 `.env`、`cfg/configs.json`、`db/`、`logs/`、媒体目录、Cookie、Token、API key、webhook 不应提交；详见 [docs/product-rules.md](docs/product-rules.md)。
- `Dockerfile.worker.dockerignore` 必须持续排除 `cfg/configs.json`；Worker 镜像只能含公开示例配置，不得写入 NAS 现役配置；详见 [docs/product-rules.md](docs/product-rules.md)。
- 中文字幕合并必须按 qB 精确文件编号、路径、大小并持久记录来源，禁止按新旧或仅凭 `.av_garden_chinese` 删除正片；进行中、校验中、做种中的目录不得清理；合并后只用 `deleteFiles=false` 移除任务，禁止 qB 递归删除作品目录；删除替代原版须先停止任务、按 qB 清单逐文件删，不能删整个作品目录；详见 [docs/product-rules.md](docs/product-rules.md)。
- 115 云下载与极空间同步独立，禁止将其同步目录软链接或映射进本地媒体库；详见 [docs/operations.md](docs/operations.md)。
- Queue API 删除任务须先发送 Worker 取消信号并移除匹配 qB 任务，再移出队列记录；默认保留文件，只有显式 `delete_files=1` 才允许删文件；详见 [docs/product-rules.md](docs/product-rules.md)。
- 一次性清理只走 `tools/maintenance/storage_cleanup.py` 的 dry-run manifest → apply；日常图片清理同样须保留 manifest/结果，应用前复核签名和运行态；详见 [docs/operations.md](docs/operations.md)。
- 98堂站内搜索每番号只请求一次，跨进程间隔至少 31 秒，不得为中文/普通版连续搜索两次；只接受 forum-103 精确番号，普通版不从 98堂取；详见 [docs/product-rules.md](docs/product-rules.md)。
- 不自动答题、不绕过验证；详见 [docs/product-rules.md](docs/product-rules.md)。
- MGS 的 `PROXY` 只走日本代理，禁止直连优先；详见 [docs/weekly-rules.md](docs/weekly-rules.md)。

## 高风险操作

以下操作必须单独确认后再做：

- 数据迁移、数据库结构变化、批量清理、删除视频文件。
- 改下载策略、队列状态机、失败恢复、fallback 源或 qB 行为。
- 改部署路径、端口、`.env`、Docker Compose 服务名或挂载。
- 引入新服务、新依赖或新架构。

## Git 与 Changelog 规则

- 本仓库已初始化本地 Git；不要为“初始化”重复创建仓库。
- 每次功能完成后，先完成本地验证，并把变更写入根目录 `CHANGELOG.md` 的 `Unreleased` 区。
- 常规改动验证通过后，可自主修复问题，但不得自动 commit、push 或部署；由 Claude 最终验收后向 Vigo 汇报修改内容和验证结果，Vigo 明确授权后才提交、推送 GitHub、部署 NAS 并完成部署后检查。
- 涉及数据删除或迁移、端口/路径/环境配置、队列状态机、下载策略或大范围清理时，必须先让用户确认，再执行、提交和部署。
- commit 必须按功能拆分并保持范围干净，不要把无关改动或用户已有改动混进去。
- 如果 `CHANGELOG.md` 过长，将较早的已发布条目归档到 `docs/changelog-archive/`，并在 `CHANGELOG.md` 保留归档链接。

## Agent 文档索引

| 什么时候读 | 文档 |
|------------|------|
| 改下载选源、队列、115、番号、配置或合并前 | [产品规则与配置边界](docs/product-rules.md) |
| 改每日推荐、刮削、回填或保留前 | [每日推荐与刮削规则](docs/weekly-rules.md)（含模块索引） |
| 改前端视觉或操作页前 | [前端设计规则](docs/frontend-design.md) |
| 排查 NAS、代理、自愈、日志或部署前 | [运维、部署与版本对齐](docs/operations.md) |
| 操作极空间部署前 | [极空间 Docker 部署说明](docs/deploy-zspace.md) |
| 开工基线、分项验证或验收前 | [验证命令与证据层级](docs/verification.md) |
| 管理 Issue | Issue tracker：[`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)（GitHub Issues `bwmf42/AVGARDEN`） |
| 做问题分诊 | Triage labels：[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md) |
| 改领域模型 / ADR | Domain / ADR：[`docs/agents/domain.md`](docs/agents/domain.md) |
| 开工恢复上下文 | 交接快照：根目录 [`handoff.md`](handoff.md)（当前会话状态，可随功能更新） |
| 外网改 NAS 后回家同步 | 跨项目「外网 Hermes → 回家同步本机」：工作区 [`../docs/nas-home-sync.md`](../docs/nas-home-sync.md)（`/Users/vigo/Public/code/docs/nas-home-sync.md`） |
