#!/usr/bin/env python3
"""Translate media-library titles without downloading or writing artwork.

This backfills older items whose NFO was generated before title translation was
available. It only changes title metadata: <title> gets the Chinese title and
the previous title is preserved in <originaltitle>.
"""
import argparse
import json
import os
import random
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from weekly_updater import translate_title_once


SAVE_PATH = Path(os.environ.get("SAVE_PATH", "/data"))
NFO_GENERATOR = "avgarden-title-only/1"
CODE_RE = re.compile(r"([A-Z]{2,}\d*)-(\d+)", re.I)
JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")
ACTOR_SUFFIX_RE = re.compile(r"\s+[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fffー・·]+$")
VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".ts"}


def clean_avid(name):
    text = str(name or "").strip().upper()
    source_prefixed = re.match(r"^\d+([A-Z]{2,}\d*-\d+)", text)
    if source_prefixed:
        return source_prefixed.group(1)
    for pattern in (r"-C$", r"CH$", r"-中文字幕$", r"_FHD_CH$", r"_CH$", r"\(\d+\)$", r"\.MP4$"):
        candidate = re.sub(pattern, "", text)
        if re.match(r"^[A-Z0-9]+-\d+$", candidate):
            return candidate
    match = CODE_RE.search(text)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}"
    return text


def normalize_title(title):
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    for suffix in (" - JavBus", " - MissAV", " | MissAV", " - Jable.TV", " - Jable"):
        title = title.removesuffix(suffix).strip()
    return title


def title_needs_translation(title, avid=""):
    """Translate if kana remains and Han / (Han + kana) is below 50%.

    Ignore the leading code and one space-separated trailing actor token.
    Latin brands, whitespace and punctuation do not dilute the Han ratio.
    This is a deterministic heuristic, not a language detector.
    """
    body = normalize_title(title)
    code = clean_avid(avid) if avid else ""
    if code:
        body = re.sub(r"^" + re.escape(code) + r"(?=\s|$)\s*", "", body, flags=re.I)
    else:
        body = re.sub(r"^[A-Z0-9]+-\d+[A-Z]?(?=\s|$)\s*", "", body, flags=re.I)
    body = ACTOR_SUFFIX_RE.sub("", body)
    kana = len(JAPANESE_KANA_RE.findall(body))
    han = len(HAN_RE.findall(body))
    return kana > 0 and han / (han + kana) < 0.5


def translate_title(avid, title, preserve_avid=False):
    translated = normalize_title(translate_title_once(avid, title, actresses=[]))
    translated = re.sub(
        rf"^(?:{re.escape(avid)}|{re.escape(clean_avid(avid))})(?=\s|[:：-]|$)\s*[:：-]?\s*",
        "",
        translated,
        count=1,
        flags=re.I,
    ).strip()
    if not translated or not HAN_RE.search(translated):
        return ""
    return f"{avid if preserve_avid else clean_avid(avid)} {translated}"


def title_key_candidates(folder_name):
    """Prefer the leading code with numeric prefixes intact, then the cleaner."""
    text = str(folder_name or "").strip().upper()
    match = re.match(r"^\d*[A-Z]+\d*-\d+", text)
    candidates = []
    if match:
        # Matching only through the code digits excludes version suffixes
        # (-U/-C/-UC/-UCC/-CH), so raw and suffix-free candidates coincide.
        candidates.append(match.group())
    candidates.append(clean_avid(folder_name))
    return list(dict.fromkeys(candidates))


def iter_nfo_files(root):
    for path in root.iterdir():
        if path.name == "thumb" or not path.is_dir():
            continue
        for nfo in path.glob("*.nfo"):
            if not nfo.name.startswith("._"):
                yield nfo


def write_xml(path, root, create=False):
    """Atomically write XML: new NFOs use 0644; rewrites keep existing permissions."""
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(pretty)
        if create and has_nfo_file(path.parent):
            return False
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        return True
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def has_nfo_file(folder):
    # Match metadata.has_nfo_file, without importing its config/logging side effects
    # during a read-only dry run. Includes nested, hidden and uppercase NFO names.
    return any(name.lower().endswith(".nfo") for _, _, files in os.walk(folder) for name in files)


def iter_missing_folders(root):
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name == "thumb" or folder.name.startswith("_"):
            continue
        if has_nfo_file(folder):
            continue
        if any(path.is_file() and not path.name.startswith("._") and path.suffix.lower() in VIDEO_SUFFIXES
               for path in folder.rglob("*")):
            yield folder


def process_missing_folder(folder, apply=False, before_network=lambda: None, titles_by_avid=None):
    if has_nfo_file(folder):
        return "skip", "NFO already exists"
    avid = clean_avid(folder.name)
    if not re.fullmatch(r"[A-Z0-9]+-\d+", avid):
        return "invalid_avid", folder.name
    metadata = None
    if titles_by_avid is not None:
        for candidate in title_key_candidates(folder.name):
            if candidate in titles_by_avid:
                avid = candidate
                break
        else:
            return "no_title", folder.name
        original_title = titles_by_avid[avid]
        if not normalize_title(original_title):
            return "no_title", folder.name
        needs_translation = title_needs_translation(original_title, avid)
        if not apply:
            return "would_create" if needs_translation else "would_create_no_translate", avid
        if needs_translation:
            before_network()
            try:
                title = translate_title(avid, original_title, preserve_avid=True)
            except Exception:
                return "unchanged", f"{avid}: translation failed"
            if not title:
                return "unchanged", avid
        else:
            title = original_title
            original_title = ""
    else:
        if not apply:
            return "would_create", avid

        # Import only on page-fetch apply: src.comm initializes runtime config/logging.
        from src.scraper import Sracper
        from src.comm import myproxy

        scraper = Sracper(str(folder.parent), proxy=os.environ.get("PROXY") or myproxy)
        before_network()
        metadata = scraper.fetch_metadata(avid)
        if metadata is None or not normalize_title(metadata.title):
            return "no_metadata", avid
        if clean_avid(metadata.avid) != avid:
            return "no_metadata", f"{avid}: page id mismatch"
        before_network()
        title = translate_title(avid, metadata.title)
        if not title:
            return "unchanged", avid
        original_title = metadata.title

    root = ET.Element("movie")
    ET.SubElement(root, "title").text = title
    if original_title:
        ET.SubElement(root, "originaltitle").text = original_title
    ET.SubElement(root, "generator").text = NFO_GENERATOR
    if metadata is not None:
        if metadata.release_date:
            ET.SubElement(root, "premiered").text = metadata.release_date
            ET.SubElement(root, "releasedate").text = metadata.release_date
        duration = re.search(r"\d+", metadata.duration or "")
        if duration:
            ET.SubElement(root, "runtime").text = duration.group()
        for name in metadata.actress:
            ET.SubElement(ET.SubElement(root, "actor"), "name").text = name
    if not write_xml(folder / f"{avid}.nfo", root, create=True):
        return "skip", "NFO appeared before write"
    return "created", title


def process_file(path, apply=False):
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return "parse_error", str(exc)

    root = tree.getroot()
    title_node = root.find("title")
    if title_node is None or not normalize_title(title_node.text):
        return "no_title", ""

    old_title = normalize_title(title_node.text)
    avid = clean_avid(path.stem or path.parent.name)
    if not title_needs_translation(old_title, avid):
        return "skip", old_title

    if not apply:
        return "would_update", old_title

    new_title = translate_title(avid, old_title)
    if not new_title or new_title == old_title:
        return "unchanged", old_title

    if apply:
        title_node.text = new_title
        original = root.find("originaltitle")
        if original is None:
            original = ET.Element("originaltitle")
            root.insert(list(root).index(title_node) + 1, original)
        original.text = old_title
        write_xml(path, root)
    return "updated", f"{old_title} -> {new_title}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default=str(SAVE_PATH), help="media library root")
    parser.add_argument("--apply", action="store_true", help="write translated titles to NFO files")
    parser.add_argument("--create-missing", action="store_true", help="create title-only NFOs for folders without any NFO")
    parser.add_argument("--titles-json", type=Path, help="offline code-to-title JSON object; requires --create-missing")
    parser.add_argument("--limit", type=int, default=0, help="max files to process")
    parser.add_argument("--min-delay", type=float, default=None, help="seconds between network calls (default: 0.5; create-missing: 3)")
    parser.add_argument("--max-delay", type=float, default=None, help="maximum delay (default: 2; create-missing: 6)")
    args = parser.parse_args()
    if args.titles_json is not None and not args.create_missing:
        parser.error("--titles-json requires --create-missing")
    if args.min_delay is None:
        args.min_delay = 3.0 if args.create_missing else 0.5
    if args.max_delay is None:
        args.max_delay = 6.0 if args.create_missing else 2.0
    if not 0 <= args.min_delay <= args.max_delay < float("inf"):
        parser.error("delays must be finite and 0 <= min-delay <= max-delay")

    titles_by_avid = None
    if args.titles_json is not None:
        try:
            with args.titles_json.open(encoding="utf-8") as handle:
                titles_by_avid = json.load(handle)
        except (OSError, UnicodeError, ValueError) as exc:
            parser.error(f"cannot read --titles-json {args.titles_json}: {exc}")
        if not isinstance(titles_by_avid, dict):
            parser.error("--titles-json must contain a JSON object")
        if any(not isinstance(title, str) for title in titles_by_avid.values()):
            parser.error("--titles-json values must all be strings")
        titles_by_avid = {avid.upper(): title for avid, title in titles_by_avid.items()}

    root = Path(args.path)
    if not root.is_dir():
        print(f"[MediaTitleTranslate] media path not found: {root}", file=sys.stderr, flush=True)
        return 2

    targets = list(iter_missing_folders(root) if args.create_missing else iter_nfo_files(root))
    if args.limit > 0:
        targets = targets[:args.limit]

    print(f"[MediaTitleTranslate] scan={root} {'folders' if args.create_missing else 'nfo'}={len(targets)} apply={args.apply}", flush=True)
    stats = {"updated": 0, "would_update": 0, "skip": 0, "parse_error": 0, "no_title": 0, "unchanged": 0, "failed": 0}
    if args.create_missing:
        stats.update(created=0, would_create=0, invalid_avid=0, no_metadata=0)
        if titles_by_avid is not None:
            stats.update(would_create_no_translate=0)
    network_started = False

    def before_network():
        nonlocal network_started
        if network_started:
            time.sleep(random.uniform(args.min_delay, args.max_delay))
        network_started = True

    for index, path in enumerate(targets, 1):
        try:
            if args.create_missing:
                status, detail = process_missing_folder(
                    path, apply=args.apply, before_network=before_network, titles_by_avid=titles_by_avid,
                )
            else:
                status, detail = process_file(path, apply=args.apply)
        except (OSError, KeyError, ValueError, TimeoutError, RuntimeError) as exc:
            status, detail = "failed", str(exc)
        stats[status] = stats.get(status, 0) + 1
        if args.create_missing or status in ("updated", "would_update", "failed", "parse_error"):
            print(f"[MediaTitleTranslate] {index}/{len(targets)} {status} {path.name if args.create_missing else path.parent.name}: {detail}", flush=True)
        if args.apply and status == "updated" and index < len(targets):
            time.sleep(random.uniform(args.min_delay, args.max_delay))

    print("[MediaTitleTranslate] done " + " ".join(f"{k}={v}" for k, v in sorted(stats.items())), flush=True)


if __name__ == "__main__":
    sys.exit(main())
