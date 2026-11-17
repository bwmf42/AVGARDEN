# A/GARDEN 每日推荐与刮削规则

改列表、图片、元数据、回填或保留逻辑前，先读本页。

## `src/weekly/` 模块

- `sources.py` / `chinese_forum.py` — 列表（默认 plwt forum-37；中文 forum-103）
- `artwork.py` — 封面预览：javdatabase → MGS → DMM → 已知论坛帖附件
- `javdatabase.py` / `mgs.py` / `dmm.py` / `javbus.py`
- `enrich.py` / `genre_zh.py` — 元数据与标签中文映射
- `sukebei.py` / `merge.py`


## 每日推荐列表与图片刮削规则

- **列表源（默认）**：98堂 `https://plwt.kpqq4.com/forum-37-1.html`（`WEEKLY_FORUM_FID=37`，默认 **3 页** `WEEKLY_MAX_PAGES`）。实现：`sources.get_recent` → `chinese_forum.get_weekly_list`。
- **未看中文补链**：`weekly_updater.py` 成功后逐个精确搜索 `forum-103`，复用跨进程 31/60 秒槽位，只回写 `weekly.json` 的中文磁链字段；不创建下载任务。库内 `replace_chinese.main(daily=True)` 由独立 `merge_watcher` 每天调度，不属于刮削流水线：先合并已完成任务，再扫库，默认列 forum-103 最新 2 页（`CHINESE_FORUM_DAILY_PAGES`），只为精确命中的缺中文番号进帖并加入 qB。当日成功才记完成；论坛失败或添加失败不记完成，稍后重试。每次以 `ReplaceCN` 记录 list/hits/added/skip/失败摘要；无缺中文或安全门失败前也已先执行合并。
- **库内中文回补**：`CHINESE_FORUM_BACKFILL=1` 配合 `CHINESE_FORUM_BACKFILL_SINCE=YYYY-MM-DD`，按帖子发帖日期（含当天）停止翻页，覆盖库内最早 NFO 作品日；未指定 SINCE 才使用最早作品日。非法日期或未开启 BACKFILL 却指定 SINCE 均报错退出。日常调度固定使用日常模式，不继承一次性回补/演练开关。先用 `CHINESE_FORUM_DRY_RUN=1` 输出将新增的番号、目标目录、磁链前缀及最终 hits/added/skip；演练不合并、不暂停或添加 qB、不写 pending/weekly。命令和请求预算见 [运维规则](operations.md#库内中文替换回补)。
- JavBus 访问代码保留但当前不参与下载磁链候选。手动/搜索下载磁链按 98堂 forum-103 精确搜索 → Sukebei 选择规则执行；每日中文替换仍按 forum-103 列表命中后进帖。
- 每日推荐封面和详情预览图应尽量本地化到 `/data/__weekly__/{番号}/`，前端优先使用 `/file/__weekly__/...`，避免用户浏览时再等外站图片。
- 标题补全或规范化没有产生实际变化时不得重写 `weekly.json`，避免无意义失效缓存和已审核的维护 manifest。
- **封面/预览图源优先级（`src/weekly/artwork.py`）**：
  1. **javdatabase**：`https://www.javdatabase.com/movies/{番号小写}/` → DMM `pl.jpg` / `og:image` + 页内 `jp-N`（无年龄 Cookie；NAS **必须走 `PROXY`**，直连常超时）。
  2. **MGS 商品图**（单页快路径）：`pb_e` / `cap_e_*` — **SIRO / ABF 等 MGS 独占** javdatabase 常 404，靠这一层；也是标签元数据主源。
  3. **DMM 精确搜索**（放最后）：传统 DVD 读静态商品表格；数字商品走 `https://api.video.dmm.co.jp/graphql`，同时读取标准 `actresses` 和素人 `amateurActress`。搜索页漏结果时把常见 CID 在一次 GraphQL 请求内批量查询，并以 `makerContentId` 二次校验番号；未知厂商前缀只借 javdatabase 页内真实 `Content ID` 定位。**无真实封面的 cid 不要扫样片**；拒绝 NOW PRINTING 占位图。
  4. **已知 98堂帖子附件**：前三层都没有所需图片时，才进该条已有 `forumUrl`，首图作封面、后续附件作预览；不为此扫描无关帖子。
  5. **条目已有 URL** 兜底。JavBus 访问技巧保留，但当前不主动请求。
- **详情元数据（`src/weekly/enrich.py`）**：
  - 字段：演员、标签、发行日、时长、字幕、封面/预览、`titleZh`
  - 顺序：MGS 表字段；MGS 完全没有标签时才用 DMM 精确商品元数据补空字段；DMM 搜索与精确 CID 均没有商品时，最后使用 javdatabase 精确番号页的演员、标签、时长 → **artwork 下载图**（上表优先级）。JavBus 代码保留但当前不参与候选。
  - 标签经 `genre_zh.py`：静态表 + **`/db/genre_zh_memory.json` 持久记忆**（只在新键写入，不每次 AI）；最后 **对齐 `blocked_genres.txt` 原文拼写**（繁简折叠），避免同义标签要重新拉黑；enrich 结束统一 normalize；**NTR 保持 NTR**。批量：`plwt_genre_normalize.py`。
  - 标题：`weekly_updater.batch_translate`（只用 DeepSeek → `titleZh`；`TRANSLATE_*` 中继配置不再生效）
- 回退列表源：`WEEKLY_LIST_SOURCE=javbus`。
- **回填范围**：默认只补前端 **未看**（`/api/weekly` 已滤屏蔽标签/演员 − 已看 − 队列 − 已下载）。脚本 `plwt_art_backfill.py`（`BACKFILL_UNWATCHED_ONLY=1`）；全量才设 `0`。元数据回填用 `weekly_backfill_details.py`（同 scope）。
- **保留规则**：未浏览作品不按时间淘汰；历史已看记录视作已浏览。已浏览作品从 `watched_at` 起保留 30 天，到期同时删除 Weekly 条目、图片目录和浏览记录。早期选择功能留下的 `interest` 字段只作兼容读取，不再提供「想看」或「不感兴趣」入口，也不再创建这类记录；已有 `want` 记录继续按原规则保留，避免隐式删除数据。
- **屏蔽作品**：先拉取演员、番号、标签等最小匹配元数据，命中后立即记为已看；不再请求封面、预览图、磁链、下载或标题翻译，并从收录时间起保留 30 天。
- **自动清理**：Launcher 每天 04:30 运行 `weekly_retention_maintenance.py --auto`；每次均生成精确 manifest、复核签名并压缩备份 Weekly/已看 JSON。`__online__`、应用日志和日常维护记录保留 30 天，维护记录至少保留最新 3 份。
- JavBus 无 `sample-box` 时不要当下载失败。DMM 图优先 `.co.jp`，失败试 `.com` / `awsimgsrc`。
- MGS：`PROXY` 只走日本代理，禁止直连优先。
- `queue_api` 在线/weekly 番号归一化保留真实数字前缀（如 `300MIUM-1395`）；仅本地文件夹清洗可剥源站前缀。
