# Changelog

本文件记录本地功能变更。新功能先写入 `Unreleased`；常规改动验证通过后直接提交、推送和部署，高风险改动仍需先确认。

当本文件过长时，将较早的已发布条目移动到 `docs/changelog-archive/`，这里只保留近期记录和归档链接。

## Unreleased

### Added

- Added guarded daily Weekly retention at 04:30: unviewed entries stay indefinitely, watched entries and their Weekly artwork expire after 30 days, and every run writes and revalidates an exact manifest plus compressed JSON backups.
- Added metadata-first blocking in the Weekly updater. Items matching blocked actresses, genres, keywords, or the existing age filter are recorded as watched, kept metadata-only for 30 days, and never request artwork, magnets, or title translation.
- Added a separate dry-run-first Weekly artwork maintenance command that only selects unreferenced directories older than 30 days by default, validates direct-child paths and signatures again at apply time, and backs up the current Weekly index before deletion.
- Added a guarded NAS storage-maintenance command that first writes an exact JSON manifest, verifies file signatures and live qB state, backs up Weekly/watched/config/database state, and only then performs approved cleanup with `deleteFiles=false` for qB records.
- Added settings-page actress blocking by video ID: resolve Japanese actress names from the local media-library NFO first, fall back to MGS then DMM, require explicit selection for multi-actress titles, and match known rename aliases such as `河北彩花` / `河北彩伽` without confusing translated title text for actress metadata.
- Added exact DMM all-category search after the existing javdatabase and MGS sources, covering both mono DVD CIDs and digital products while rejecting similar codes and `NOW PRINTING` placeholders. DMM GraphQL now reads standard and amateur actress fields; when the search page misses a product, likely CIDs are queried in one batch and accepted only after exact `makerContentId` verification. Unknown maker prefixes can use javdatabase's exact `Content ID` as a resolver without blind CDN probing.
- Switched daily recommendation **list** source to 98堂 `forum-37` (`WEEKLY_FORUM_FID=37`, default 3 pages via `WEEKLY_MAX_PAGES`); Chinese daily remains `forum-103` with 2 pages. JavBus list available via `WEEKLY_LIST_SOURCE=javbus`.
- Cover/preview pipeline (`artwork.py`): **javdatabase** (`javdatabase.py`) → **MGS product images** → **DMM exact GraphQL/CDN** → the item's already-known forum attachments → item URLs. JavBus request code remains available but is currently excluded from active candidates.
- SOAV-style metadata enrich (`enrich.py`, `genre_zh.py`): MGS table fields → exact DMM metadata → exact javdatabase page fallback → artwork download; source-native Japanese/English genres are aligned through `genre_zh` (NTR kept).
- `plwt_art_backfill.py`: bulk cover/fanart fill; default **`BACKFILL_UNWATCHED_ONLY=1`** scopes to frontend 未看 (`/api/weekly` − watched − queue − downloaded), not full `weekly.json`.
- Added Chinese-subtitle forum backfill/daily modes in `replace_chinese.py`: scan local NFO premiered dates, list `forum-103` (stop at earliest work date for one-time `CHINESE_FORUM_BACKFILL=1`, or only 2 pages daily), open matching threads only for library items still missing Chinese, and pull in-post magnets into qB.
- Added a Chinese-subtitle Discuz list source (`src/weekly/chinese_forum.py` + `tools/maintenance/chinese_forum_updater.py`): passes the site `_safe` gate once, reuses the session, paginates `forum-103` list pages only (no thread visits), extracts codes/titles with polite page delays, and writes local verification output under `work/chinese_scrape/`.
- Added a full repository, deployment-tree, and Weekly-cache audit under `docs/`, including exact cleanup boundaries and deferred correctness/security findings.

### Changed

- Made Server and Worker share a locked, atomic watched-state format with an internal manual/blocked reason while preserving the existing `/api/weekly-watched` response. The server is authoritative after browser migration, expired IDs absent from Weekly cannot be restored, online abnormal-search cache retention is 30 days, and routine maintenance records retain 30 days with at least the newest three copies.
- Deployment now records the two previously running A/GARDEN image IDs and removes only those exact images after both replacement containers and the public API pass health checks.
- Moved the Worker and Queue API onto the private Compose network, made the Go server use `http://worker:31473`, added server connection timeouts, and changed deployment sync to `rsync --delete` with explicit protection for runtime configuration, database, and logs.
- Upgraded Axios to 1.18.1, Vue to 3.5.40, Vite to 6.4.3, PostCSS to 8.5.24, and the overridden `form-data` to 4.0.6; the official npm audit now reports zero vulnerabilities.
- Canonicalize a trailing `V` edition marker to the base video ID across forum ingestion, Python, Go, and Vue (for example `START-612V` → `START-612`) while preserving other meaningful suffix letters; official DMM release dates now replace forum post dates while `postDate` remains intact.
- Genre labels: expand `genre_zh` Chinese map; persist learned src→zh in `/db/genre_zh_memory.json` (read on scrape, write only new keys); enrich always normalizes genres; `plwt_genre_normalize.py` one-shot rewrites weekly.json.
- Genre output **snaps to exact `blocked_genres.txt` spellings** (fold 繁简/中点) so existing block list keeps matching without re-blocking aliases.
- Blocking a genre/actress invalidates weekly API cache and refreshes the detail browse list so matching 未看 titles disappear immediately (not only the current card).
- Title translate: DeepSeek per-title retries with exponential backoff on 429/5xx, multi-pass for leftovers; `plwt_translate_missing.py` one-shot backfill.
- Soften DMM/javdatabase traffic: global request pacing (`DMM_DELAY`, higher `JAVDATABASE_DELAY`), fewer sample/cid/GraphQL probes, fail-streak backoff.
- Queue status: treat qB `queuedDL` as active; resolve codes from torrent **tags** first; keep `queue_state.json` until job is gone from queue/qB (fixes UI「加入下载队列」while already queued). Worker finds magnets by tags/name, not only save_path.
- Reconciled the current handoff, NAS deployment guide, frontend development guide, environment comments, and bundled operations skill with the deployed A/GARDEN runtime and active paths.
- Moved non-runtime recovery and maintenance commands out of the repository root into `tools/maintenance/`, preserving their runnable project-root resolution.
- Replaced sukebei-based Chinese magnet search in `replace_chinese.py` with the Discuz Chinese-subtitle forum; daily launcher path stays `weekly_updater` then `replace_chinese` (default 2 forum list pages).
- Hardened Chinese merge cleanup: after moving the Chinese video in, recursively delete non-Chinese videos and common promo junk in the target folder (no longer skip whole folders just because the directory name ends with `-C` / 中文); also sweep existing library leftovers that already have Chinese but still keep old non-Chinese files.
- Chinese merge now keeps a strict media set only: Chinese main video, `.nfo`, poster/cover, and fanart previews; removes ads, `.url`/`.html`/`.txt`, and other torrent junk.

- Added shared video ID normalization coverage across Vue, Go, and Python for dashed, compact, numeric-leading, FC2, multi-part, numeric-date, and selected special formats.
- Added automated tests for video ID safety, queue file concurrency, tracked-process cancellation, exact qB task removal, Queue API polling, Go blocked-list concurrency, and JSON escaping.
- Added one-time online code search: exact code searches can fetch a JavBus detail, show it in the weekly-card style, reuse download/favorite/block actions, and mark already-local items with a local badge.
- Added temporary online artwork cleanup under `__online__`: online search/detail cache is removed when leaving the online search flow and never written into `weekly.json`.
- Added a `/api/cover/{id}` lookup endpoint that searches local media, current weekly data, and orphaned `__weekly__` cover folders without mutating `weekly.json`.
- Added a local changelog workflow: completed work is recorded here before commit, then waits for manual testing confirmation.
- Added a media-library NFO title backfill script to translate older local titles while preserving original titles.
- Added preview artifacts for the 02 media-hub direction under `design-demos/`.
- Added a visible-unwatched weekly backfill script for filling details, local covers, magnets, and translated titles only for items that pass current filters and are still 未看.
- Added JavBus detail-page magnet list lookup as the first weekly magnet source, before Sukebei/Nyaa and MissAV fallbacks.

- Moved the NAS deployment root to `/42/docker/AVGARDEN` and updated local deployment guidance to keep future deploys in the Docker app folder.
- Limited normal weekly scraping to JavBus cards marked 今日新種; 昨日新種 can still be included via `WEEKLY_FRESHNESS_MARKERS` for one-off recovery runs.
- Weekly merge now keeps undownloaded recommendations beyond the old 30-day window, so the 未看 pool can continue accumulating until you watch or download them.
- Kept weekly recommendation artwork on full weekly covers instead of generated portrait crops.
- Ordered blocked actresses by newest addition first in settings.
- Replaced remaining project-visible legacy naming with `AVGARDEN`, including local deployment references and archived package naming.
- Restyled the Vue frontend toward the 02 media-hub layout with a left navigation rail, central media workspace, and right activity rail.
- Updated public-facing documentation wording to use more neutral media-library language.

### Removed

- Applied the first reviewed Weekly-retention manifest in production: expired 844 watched Weekly entries and 1,605 watched-state records, removed 1,315 exact expired/blocked artwork directories containing 7,470 files, and released 795.66 MiB while preserving every unexpired/unwatched entry and creating compressed index/state backups.
- Applied the reviewed NAS storage manifests: removed 1,237 unreferenced Weekly artwork directories, 7 sparse residues, 10 metadata-only shells, 6 exact stale files, 160 `missingFiles` and 7 orphan/false-complete qB records with `deleteFiles=false`, releasing 13.47 GiB of allocated space while preserving 1,811 Weekly entries and 2,017 watched records.
- Removed 21 exact stale paths from the NAS deployment tree using a saved JSON manifest, releasing 25,108,415 bytes while preserving runtime configuration, databases, logs, artwork caches, media, and qBittorrent tasks.
- Cleaned the deployed media library while preserving multipart and metadata-only directories: kept five verified high-bitrate copies, removed their five lower-bitrate duplicates, disabled and removed 152 exact-name bundled promo clips, and removed a stale 135 MiB project copy from the weekly cache.
- Removed the rejected 05-07 design exploration artifacts while retaining the adopted 02 direction and the undecided 01/03/04 explorations.
- Removed the remaining implemented design explorations, the unused Tauri CLI dependency, default Vite/Vue assets, the obsolete cron entrypoint, and the assertion-free legacy test script.

### Fixed

- Prevented blocked Weekly entries from repeatedly consuming image, magnet, and translation requests, and removed the old release-date/downloaded merge eviction so entries that have not been watched are not discarded by age.
- Prevented scheduled title repair from rewriting an unchanged `weekly.json`, so no-op runs no longer invalidate reviewed maintenance manifests or churn the 5.5 MB index.
- Excluded active qB downloads from completed-media poster repair even when a nearly finished sparse file temporarily passes the 95% allocation rule, derived the final repair count from execution-time state while still requiring a source for every poster, and made cleanup apply-time activity guards honor numeric-prefix compatibility aliases.
- Added read-only compatibility aliases from shortened qB labels such as `LUXU-1881` and `MIUM-1389` to their numeric-leading media directories, while keeping explicit short-code directories authoritative. Local `CH` subtitle suffixes such as `fns-224ch` now resolve to the base code instead of a false `FNS-224C` variant.
- Preserved real numeric-leading local IDs such as `300MIUM-*` and `259LUXU-*` while stripping only confirmed source prefixes; old shortened detail URLs remain compatible and resolve to the corrected canonical ID.
- Unified Python and Go completion checks on recursive MP4 lookup, a 100 MiB floor, 95% allocated-byte validation, largest-copy selection, and multipart part-one preference. Completed qB tasks without a valid disk file no longer block recovery or appear local.
- Serialized every `weekly.json` writer through one cross-process lock and atomic replacement, and added server-side 24-hour cleanup for abandoned `__online__` search caches.
- Restricted `/file/` requests to one media, Weekly, or online owner directory, rechecked resolved symlinks after opening, and served Range requests from the opened file descriptor.
- Prevented duplicate downloads when qB already has the same code in another category: Worker now checks all qB categories before any online-stream fallback while ignoring broken `missingFiles` / `error` tasks.
- Unified local main-video detection across the media list, detail playback, weekly local index, video status, and failed queue: recursively select MP4 files above 100 MiB with at least 95% allocated data, prefer part 1 for multipart titles, otherwise choose the largest copy, and hide metadata-only or incomplete sparse directories from the library.
- Audited all 228 selected media files with `ffprobe`: 221 are valid; seven incomplete sparse files with missing MP4 indexes are retained for recovery but no longer exposed as playable local media.
- Filled the DMM search-page blind spot with exact batched GraphQL CID lookup, parsed standard AV actresses in addition to amateur profiles, rejected generic empty MGS pages as false metadata hits, and added exact javdatabase metadata plus known-forum artwork fallbacks for the remaining weekly gaps.
- Normalized MGS amateur performer profiles to nickname-only actress labels, repaired existing weekly labels during detail backfill, and limited metadata backfill to genuinely missing fields. Metadata now uses MGS as authoritative when it has genres and falls back to exact DMM product metadata only when MGS genres are absent; progress is saved per item with remaining-field and failure summaries.
- Reduced scheduled cover refreshes from multi-minute CID/sample probing to exact cover-only searches, bounded fallback probes, and 1-3 second pacing. Weekly updater and backfill jobs now share a cross-process lock and unique atomic temp files so they cannot overwrite each other.
- Fixed unsafe queue input handling by separating format recognition from path safety, rejecting control/path characters, and replacing shell-built downloader commands with argument-based subprocess execution.
- Fixed queue deletion so it sends a cross-process cancellation request, terminates tracked online downloader/ffmpeg processes, removes matching tagged qB tasks, and only hides the frontend row after a successful API response.
- Fixed queue and retry state races with locked, atomic queue/JSON writes shared by Queue API, Worker, and Launcher.
- Fixed repeated qB polling by fetching the torrent list once per queue-status request instead of once per queued item.
- Fixed worker image builds on the NAS by using the configured China-accessible Go module proxy and pinning the runtime to Alpine 3.21/Python 3.12 instead of an incompatible moving `latest` image.
- Fixed Go blocked/favorite list concurrent map access, Queue API proxy requests without timeouts, invalid hand-built JSON responses, wildcard CORS credentials, and the hard-coded actress-age year.
- Fixed MGStage-hosted weekly preview image localization by retrying those images direct with MGStage referers, so filtered weekly backfills can save local fanarts instead of failing through the proxy/JavBus referer path.
- Fixed online/weekly exact code normalization so numeric-leading codes such as `300MIUM-1395` are not mistaken for source-prefixed folder names.
- Fixed broken weekly and online-search preview images by downloading JavBus sample images into local `__weekly__` / `__online__` folders, retrying DMM images through the working `.com` image host, returning `/file/...` URLs, and lazily localizing older weekly detail pages when opened.
- Fixed exact code search without a dash so queued weekly items open the weekly detail instead of being replaced by a one-time online result.
- Fixed online search local badges so active queued/downloading items are not treated as completed local media.
- Fixed weekly `downloaded` status so active queue items are not treated as completed just because a partial `.mp4` exists.
- Fixed weekly cache invalidation to include active queue state, preventing stale downloaded flags while a task is still downloading.
- Matched search-result cover cropping to the weekly 未看 list by using the same right-side cover framing and card aspect.
- Fixed one-time online search to reuse the worker `PROXY` setting for JavBus and magnet lookups.
- Fixed Queue API startup to use the worker virtualenv Python, so online search can import the scraper dependencies installed in the worker image.
- Fixed weekly detail queue buttons so a recent queue submission for one code no longer makes another code display as already queued.
- Reduced weekly detail browsing stalls by reusing the detail component, caching weekly data briefly, and saving watched state without blocking page navigation.
- Reset weekly detail cover and preview image nodes when changing items so the previous page's preview images do not remain visible while new images load.
- Warm weekly recommendation cache on server startup so the first browser request after deploy does not pay the full media-index scan cost.
- Refresh low-resolution weekly covers from JavBus detail-page `bigImage` instead of keeping list-page thumbnails enlarged in detail view.
- Added explicit manual weekly scrape start and finish/failure records to system logs.
- Added a one-off page-scan override for weekly scraping so missed recent JavBus cards can be backfilled from deeper paginated pages without changing the daily default.
- Added a `WEEKLY_LIST_ONLY` fast backfill mode so page-based weekly recovery can skip per-title detail fetch, magnet lookup, and translation when only the list-page cards are needed.
- Made weekly detail backfill treat empty actress lists as valid for omnibus/amateur items and report remaining missing fields instead of a vague `unchanged`.
- Fixed weekly detail artwork so it uses the full weekly cover instead of generated portrait poster crops that can cut artwork in half.
- Fixed source-prefixed codes such as `857OMG-032` so metadata scraping and Chinese-subtitle replacement search with `OMG-032` while keeping the original media folder.
- Fixed weekly detail keyboard navigation so arrow-key paging only fires once per press and does not conflict with image lightbox navigation.
- Made local no-backend preview safer by handling non-array `/api/videos` responses and non-JSON weekly/queue preview responses.
- Fixed manual weekly scrape leaving no completion record: `queue_api.py` now spawns a watcher thread that writes `[ManualScrape] 刮削完成/失败/超时` to `av-garden.log`.
- Fixed race condition in `start_weekly_scrape` by adding a lock to prevent concurrent scrape launches.
- Removed redundant qBittorrent API call in `get_download_info` (dead code in else branch).
- Unified `log_write` default `LOG_DIR` to `/app/logs` to match launcher and docker-compose.
- Guarded `existing_ids` in `weekly_updater.py` against missing `id` field (KeyError crash).
- Made `is_recent` in `merge.py` handle multiple date formats (`2026-06-20`, `2026/06/20`, `2026年6月20日`, etc.) instead of crashing; invalid dates now return `False` so stale entries get cleaned.
- Switched Queue API from single-threaded `HTTPServer` to `ThreadingHTTPServer` with a lock on `_speed_cache` to prevent download management page from blocking.
- Tightened `has_active_qb_task` matching to use delimiter boundaries instead of substring containment, preventing false matches like `ABF-361` matching `ABF-3612`.
- Optimized weekly page loading: replaced per-item disk stat with a cached media index (30s TTL), reducing cold-cache load from minutes to ~4s.
- Fixed weekly page re-fetching on tab switch: `activated()` now only loads data on first entry, tab switches use cached items.
- Fixed watched list ordering: server now returns watched IDs sorted by `watched_at` descending; frontend preserves this order instead of falling back to alphabetical sort.
