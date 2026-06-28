# Changelog

本文件记录本地功能变更。新功能先写入 `Unreleased`，待手动测试确认后再询问是否提交 commit。

当本文件过长时，将较早的已发布条目移动到 `docs/changelog-archive/`，这里只保留近期记录和归档链接。

## Unreleased

### Added

- Added a local changelog workflow: completed work is recorded here before commit, then waits for manual testing confirmation.
- Added preview artifacts for the 02 media-hub direction under `design-demos/`.
- Added a visible-unwatched weekly backfill script for filling details, local covers, magnets, and translated titles only for items that pass current filters and are still 未看.
- Added JavBus detail-page magnet list lookup as the first weekly magnet source, before Sukebei/Nyaa and MissAV fallbacks.

### Changed

- Limited normal weekly scraping to JavBus cards marked 今日新種; 昨日新種 can still be included via `WEEKLY_FRESHNESS_MARKERS` for one-off recovery runs.
- Weekly merge now keeps undownloaded recommendations beyond the old 30-day window, so the 未看 pool can continue accumulating until you watch or download them.
- Kept weekly recommendation artwork on full weekly covers instead of generated portrait crops.
- Ordered blocked actresses by newest addition first in settings.
- Replaced remaining project-visible legacy naming with `AVGARDEN`, including local deployment references and archived package naming.
- Restyled the Vue frontend toward the 02 media-hub layout with a left navigation rail, central media workspace, and right activity rail.
- Updated public-facing documentation wording to use more neutral media-library language.

### Fixed

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
