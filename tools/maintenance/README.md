# Maintenance Tools

These commands are manual recovery or one-time migration utilities. They are not
started by Docker Compose, the Worker launcher, or the web API.

Run them from the repository root unless a command explicitly says otherwise:

```bash
python3 tools/maintenance/chinese_forum_updater.py
python3 tools/maintenance/fill_gaps.py
python3 tools/maintenance/translate_media_titles.py --path /data
bash tools/maintenance/health_check.sh
```

NAS storage cleanup is a two-step operation inside the Worker container:

```bash
python3 /app/tools/maintenance/storage_cleanup.py --manifest /db/maintenance/manifests/storage-cleanup.json
python3 /app/tools/maintenance/storage_cleanup.py --apply /db/maintenance/manifests/storage-cleanup.json
```

The first command is a dry run that records exact paths, sizes, signatures, qB
hashes, guards, and baseline counts. The apply command refuses to run if that
manifest or any guarded runtime state has changed. qB records are always removed
with `deleteFiles=false`.

Routine Weekly artwork cleanup is separate and defaults to orphan directories
older than 30 days. It also requires a reviewed manifest before applying:

```bash
python3 /app/tools/maintenance/weekly_cache_maintenance.py \
  --manifest /db/maintenance/manifests/weekly-cache.json
python3 /app/tools/maintenance/weekly_cache_maintenance.py \
  --apply /db/maintenance/manifests/weekly-cache.json
```

The active retention policy uses a separate guarded command. Dry-run manually:

```bash
python3 /app/tools/maintenance/weekly_retention_maintenance.py \
  --manifest /db/maintenance/manifests/weekly-retention.json
```

After reviewing the manifest, apply it with `--apply`. The Worker launcher runs
the equivalent `--auto` path daily at 04:30. It keeps unviewed Weekly entries,
expires watched entries and watched records after 30 days, immediately removes
Weekly artwork for blocked entries, and retains only lightweight blocked
metadata until its watched timestamp expires. Each apply backs up both
`weekly.json` and `weekly_watched.json` first.

- `chinese_forum_updater.py` writes to `work/chinese_scrape/` by default. Set
  `SAVE_PATH` explicitly before targeting production data.
- `fill_gaps.py` changes `weekly.json` and performs remote requests. Use only for
  deliberate recovery work.
- `translate_media_titles.py` is read-only unless `--apply` is passed.
- `health_check.sh` requires the documented webhook, qBittorrent, API, and media
  path environment variables.
- `storage_cleanup.py` backs up current Weekly, watched, configuration, and
  SQLite state before applying an already-reviewed manifest.

Production scripts copied into the Worker image remain at the repository root.
