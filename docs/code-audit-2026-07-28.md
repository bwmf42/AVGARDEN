# A/GARDEN Code And Storage Audit

Date: 2026-07-28

## Conclusion

The reported twenty-thousand-file tree is not the source repository. It is the
NAS media volume's `__weekly__` artwork cache. The active source checkout had
130 tracked files before this cleanup; most local filesystem entries came from
Git metadata and reinstallable frontend dependencies.

This cleanup does not delete media, Weekly artwork, online-search artwork,
configuration, database state, logs, or qBittorrent tasks.

## Storage Inventory

| Area | Inventory | Decision |
| --- | ---: | --- |
| Current `weekly.json` | 1,811 entries | Keep |
| Current Weekly artwork directories | 1,811 directories, 13,183 JPG files, 1.53 GB | Keep |
| Weekly directories absent from current index | 1,237 directories, 5,589 JPG files, 602,879,376 bytes | Report only |
| Total Weekly artwork | 18,772 JPG files, about 2.13 GB | Keep |
| Old Weekly JSON backups | 3 files, about 15 MB | Keep in this pass |
| Online temporary artwork | 1 directory, about 160 KB | Keep in this pass |
| NAS deployment residue removed | 21 exact paths, 25,108,415 bytes (23.95 MiB) | Removed from the deployment tree |

Of the 1,237 unindexed Weekly directories, 729 codes remain in watched history
and 115 have an exact same-name media directory. Neither category is deleted in
this pass.

## Deferred Findings

These issues were verified during the audit and intentionally remain unchanged
because this pass is limited to file cleanup.

1. **High: numeric-leading local IDs are shortened.** `backend/main.go` still
   uses the older `cleanVideoID` path for media-library folders. Production
   currently exposes `300MIUM-*` as `MIUM-*` and `259LUXU-*` as `LUXU-*`, even
   though user-input normalization preserves those prefixes.
2. **High: Queue API completion detection differs from the server.**
   `queue_api.py` accepts a non-recursive MP4 above 10 MB after a 60-second age
   check. The Go server now requires a recursive MP4 above 100 MB with at least
   95 percent allocated data. A sparse or bundled file can therefore still
   trigger Queue API completion actions.
3. **High: not every `weekly.json` writer uses the shared lock.** Queue status,
   fanart localization, Chinese replacement, and older one-shot scripts contain
   direct or fixed-temp writes that can race with the scheduled updater.
4. **Medium: media file serving validates only the media root.** `/file/`
   requests can traverse between media subdirectories while remaining under the
   root, and symlink resolution is not checked.
5. **Medium: Queue API is reachable on all interfaces without its own auth.**
   The production Worker uses host networking and binds port 31473 to `0.0.0.0`.
6. **Medium: the Go HTTP listeners do not set read, write, header, or idle
   timeouts.**
7. **Medium: deployment merges source without deleting removed files.** A
   one-time exact cleanup is safe, but future source removals can leave new NAS
   residue until deployment synchronization is hardened.
8. **Low: online-search cleanup has no server-side expiry.** Browser cleanup is
   best-effort; one temporary directory from 2026-07-06 remains on the NAS.

## Baseline Verification

- Go race tests and `go vet`: passed.
- Frontend Node tests and production build: passed.
- Python: 76 effective tests passed and 2 Worker-container integration tests
  were skipped locally. The obsolete `test_clean.py` caused standard discovery
  to fail because it had no assertions and imported the full runtime at module
  load; it is removed by this cleanup.
- Production containers and API were healthy during the audit. Two qBittorrent
  tasks were active, with no online-stream downloader process and no Worker lock.

## Cleanup Result

The exact 21-path deletion manifest was saved on the NAS as
`/tmp/avgarden-cleanup-manifest-20260728.json` before removal. It contained only
reviewed project residue: implemented design demos, temporary genre scripts,
obsolete root-level module copies, an obsolete Vue file, two old backend
binaries, moved maintenance-script copies, unused starter assets, and dated
environment, Compose, and deployment-script backups.

After removal, the current Compose file, `.env`, `cfg/`, `db/`, and `logs/`
were verified present. Media directories, qBittorrent tasks, Weekly and online
artwork caches, and other runtime state were not touched.
