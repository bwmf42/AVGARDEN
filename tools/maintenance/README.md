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

### Title-only NFO maintenance

Peach handles artwork; this tool never downloads or writes images. The default
mode translates existing NFO titles, preserving the old title in `originaltitle`.
It ignores a leading code and a trailing space-separated Japanese actor token;
the remaining title needs translation only when it contains kana and Han makes
up less than 50% of Han plus kana characters (Latin brands/punctuation excluded).

Run inside the Worker with its virtualenv Python (system Python may lack
`curl_cffi`). From `/app`:

```bash
# Existing NFOs: preview, then apply if intended
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data --apply

# Missing NFOs: offline preview only; lists eligible folders and counts
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data --create-missing
# Fetch/translate at most one eligible folder and atomically create its NFO
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data --create-missing --apply --limit 1

# Use a local code-to-title JSON instead of fetching pages: preview, then apply
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data --create-missing --titles-json /tmp/jp_titles.json
/app/venv/bin/python3 tools/maintenance/translate_media_titles.py --path /data --create-missing --titles-json /tmp/jp_titles.json --apply --limit 1
```

`--create-missing` scans immediate work folders containing video files (including
nested videos), excluding `thumb`, underscore-prefixed folders and symlinks.
Any NFO anywhere within a work folder, including `._*.nfo` and uppercase `.NFO`,
prevents creation. The check is repeated just before atomic replacement.
Invalid codes, missing/unparseable pages and empty/non-Han translations are
counted and skipped without leaving an NFO or temporary file.

Without `--titles-json`, new `<code>.nfo` files contain only `title` (`code Chinese title`), `originaltitle`,
available `premiered`/`releasedate`, numeric `runtime`, and actor names. They
contain no artwork references, actor thumbnails, genres or plot. Creation uses
page fetching plus metadata extraction only, bypassing the full scraper.
Network calls are spaced by a random 3–6 seconds in this mode, including the
gap between fetching and translation and after failed calls. Override with
`--min-delay`/`--max-delay`; existing-NFO mode keeps its 0.5–2 second defaults.
This is manual maintenance and does not change Worker or launcher scheduling.

`--titles-json PATH` requires `--create-missing` and replaces page fetching
entirely: it never constructs a scraper or calls `fetch_metadata`. Supply a UTF-8
JSON object such as `{"ABF-123": "はじめてのデート", "abf-124": "中文标题"}`.
The entire file is validated before processing any folder; unreadable files,
invalid JSON, non-object roots and non-string values exit with an error and no
writes. Keys are matched case-insensitively in candidate order: the leading
code matching `^\d*[A-Z]+\d*-\d+` in the trimmed, uppercase folder name (numeric
prefixes retained), its version-free form, then `clean_avid(folder.name)` as a
fallback. The leading-code match already excludes version suffixes (`-U`, `-C`,
`-UC`, `-UCC`, `-CH`), so the first two candidates coincide and are deduplicated.
For example, `259LUXU-1881-UC` tries `259LUXU-1881` before `LUXU-1881`;
`MIHD-004-U` matches `MIHD-004`. The first present key wins and supplies both
the translated title prefix and `<code>.nfo` filename; a blank value still
reports `no_title`. Missing keys report `no_title` with the folder name, without
guessing another code. Invalid folders such as `艾薇` and `你在录视频` remain
`invalid_avid` and are never written. Review dry-run output before applying;
this option does not change `clean_avid` or page-fetch behavior.

For JSON titles needing translation, the file contains exactly `title` (`code
Chinese translation`) and `originaltitle` (the supplied original). Titles that
the existing heuristic considers already translated are used verbatim as
`title`, with no translation request and no `originaltitle`. No other metadata
or artwork fields are written. Missing/blank titles report `no_title` with the
code; empty/non-Han translations and translation errors report `unchanged` and
leave no files. Dry-run remains offline and read-only, reporting each folder as
`would_create`, `no_title`, or `would_create_no_translate`, with totals. In this
mode only actual translation calls count toward the 3–6 second network delay;
direct Chinese-title writes incur no wait. Existing NFO protection, atomic
writing and `--limit` work as above.

Media directory dates use `/db/media_directory_dates.json`. On the current NAS,
SMB derives creation time from POSIX directory dates, so repairs anchor directory
atime/mtime without changing video timestamps. Metadata scraping and Chinese
merges preserve these dates; the existing heal pass restores external drift.
New verified local completions get an immutable completion anchor. A release-date
fallback is labelled `release_date`, never presented as an actual download date.

For historical repair, prepare a JSON proposal array with `folder`, `code`,
timezone-bearing `date`, `basis` (`release_date` or `download_completed`), and
`source` (exact release-page URL or verified completion-log reference). Then:

```bash
python3 tools/maintenance/media_dates.py --dates dates.json --manifest /db/maintenance/media-dates.json
python3 tools/maintenance/media_dates.py --apply /db/maintenance/media-dates.json
python3 tools/maintenance/media_dates.py --rollback /db/maintenance/media-dates.json.result.json
```

Review the manifest first. Apply rechecks its hash, directory identity, timestamps
and direct-child signatures before changes. The result preserves the previous
registry and directory dates for rollback. Internal caches, hidden folders,
symlinks and replaced directory inodes are excluded. Never infer a release date
from a forum posting date, a file mtime or an inexact product search hit.
