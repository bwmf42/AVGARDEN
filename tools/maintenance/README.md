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

- `chinese_forum_updater.py` writes to `work/chinese_scrape/` by default. Set
  `SAVE_PATH` explicitly before targeting production data.
- `fill_gaps.py` changes `weekly.json` and performs remote requests. Use only for
  deliberate recovery work.
- `translate_media_titles.py` is read-only unless `--apply` is passed.
- `health_check.sh` requires the documented webhook, qBittorrent, API, and media
  path environment variables.

Production scripts copied into the Worker image remain at the repository root.
