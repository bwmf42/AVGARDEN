# Changelog

本文件记录本地功能变更。新功能先写入 `Unreleased`，待手动测试确认后再询问是否提交 commit。

当本文件过长时，将较早的已发布条目移动到 `docs/changelog-archive/`，这里只保留近期记录和归档链接。

## Unreleased

### Added

- Added exact DMM all-category search after the existing javdatabase and MGS sources, covering both mono DVD CIDs and digital products while rejecting similar codes and `NOW PRINTING` placeholders. DMM GraphQL now reads standard and amateur actress fields; when the search page misses a product, likely CIDs are queried in one batch and accepted only after exact `makerContentId` verification. Unknown maker prefixes can use javdatabase's exact `Content ID` as a resolver without blind CDN probing.
- Switched daily recommendation **list** source to 98堂 `forum-37` (`WEEKLY_FORUM_FID=37`, default 3 pages via `WEEKLY_MAX_PAGES`); Chinese daily remains `forum-103` with 2 pages. JavBus list available via `WEEKLY_LIST_SOURCE=javbus`.
- Cover/preview pipeline (`artwork.py`): **javdatabase** (`javdatabase.py`) → **MGS product images** → **DMM exact GraphQL/CDN** → the item's already-known forum attachments → item URLs. JavBus request code remains available but is currently excluded from active candidates.
- SOAV-style metadata enrich (`enrich.py`, `genre_zh.py`): MGS table fields → exact DMM metadata → exact javdatabase page fallback → artwork download; source-native Japanese/English genres are aligned through `genre_zh` (NTR kept).
- `plwt_art_backfill.py`: bulk cover/fanart fill; default **`BACKFILL_UNWATCHED_ONLY=1`** scopes to frontend 未看 (`/api/weekly` − watched − queue − downloaded), not full `weekly.json`.
- Added Chinese-subtitle forum backfill/daily modes in `replace_chinese.py`: scan local NFO premiered dates, list `forum-103` (stop at earliest work date for one-time `CHINESE_FORUM_BACKFILL=1`, or only 2 pages daily), open matching threads only for library items still missing Chinese, and pull in-post magnets into qB.
- Added a Chinese-subtitle Discuz list source (`src/weekly/chinese_forum.py` + `chinese_forum_updater.py`): passes the site `_safe` gate once, reuses the session, paginates `forum-103` list pages only (no thread visits), extracts codes/titles with polite page delays, and writes local verification output under `work/chinese_scrape/`.

### Changed

- Genre labels: expand `genre_zh` Chinese map; persist learned src→zh in `/db/genre_zh_memory.json` (read on scrape, write only new keys); enrich always normalizes genres; `plwt_genre_normalize.py` one-shot rewrites weekly.json.
- Queue status: treat qB `queuedDL` as active; resolve codes from torrent **tags** first; keep `queue_state.json` until job is gone from queue/qB (fixes UI「加入下载队列」while already queued). Worker finds magnets by tags/name, not only save_path.
- Reconciled the current handoff, NAS deployment guide, frontend development guide, environment comments, and bundled operations skill with the deployed A/GARDEN runtime and active paths.
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

- Removed the rejected 05-07 design exploration artifacts while retaining the adopted 02 direction and the undecided 01/03/04 explorations.

### Fixed

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
