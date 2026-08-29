#!/usr/bin/env python3
"""Translate existing media-library NFO titles in place.

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
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom


SAVE_PATH = Path(os.environ.get("SAVE_PATH", "/data"))
DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
CODE_RE = re.compile(r"([A-Z]{2,}\d*)-(\d+)", re.I)
JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")


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


def title_needs_translation(title):
    return bool(title and JAPANESE_KANA_RE.search(title))


def strip_code_prefix(title, avid):
    title = normalize_title(title)
    avid = clean_avid(avid)
    patterns = (
        rf"^{re.escape(avid)}\s+",
        rf"^\({re.escape(avid)}\)\s*",
        rf"^{re.escape(avid.replace('-', ''))}\s+",
    )
    for pattern in patterns:
        title = re.sub(pattern, "", title, flags=re.I).strip()
    return title


def remove_code_prefix(title, avid):
    title = normalize_title(title)
    stripped = strip_code_prefix(title, avid)
    return stripped or title


def translate_title(avid, title):
    if not DS_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    source = strip_code_prefix(title, avid)
    payload = json.dumps({
        "model": DS_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是日语翻译助手。将日文影视标题翻译为简洁自然的中文，只输出翻译结果，不要解释，不要添加番号。",
            },
            {"role": "user", "content": source},
        ],
        "max_tokens": 256,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    translated = normalize_title(result["choices"][0]["message"]["content"])
    translated = remove_code_prefix(translated, avid)
    if not translated or not HAN_RE.search(translated):
        return ""
    return f"{clean_avid(avid)} {translated}"


def iter_nfo_files(root):
    for path in root.iterdir():
        if path.name == "thumb" or not path.is_dir():
            continue
        for nfo in path.glob("*.nfo"):
            if not nfo.name.startswith("._"):
                yield nfo


def write_xml(path, root):
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(pretty)
    os.replace(tmp, path)


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
    if not title_needs_translation(old_title):
        return "skip", old_title

    avid = clean_avid(path.stem or path.parent.name)
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
    parser.add_argument("--limit", type=int, default=0, help="max files to process")
    parser.add_argument("--min-delay", type=float, default=0.5)
    parser.add_argument("--max-delay", type=float, default=2.0)
    args = parser.parse_args()

    root = Path(args.path)
    if not root.is_dir():
        print(f"[MediaTitleTranslate] media path not found: {root}", file=sys.stderr, flush=True)
        return 2

    targets = list(iter_nfo_files(root))
    if args.limit > 0:
        targets = targets[:args.limit]

    print(f"[MediaTitleTranslate] scan={root} nfo={len(targets)} apply={args.apply}", flush=True)
    stats = {"updated": 0, "would_update": 0, "skip": 0, "parse_error": 0, "no_title": 0, "unchanged": 0, "failed": 0}
    for index, path in enumerate(targets, 1):
        try:
            status, detail = process_file(path, apply=args.apply)
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError, RuntimeError) as exc:
            status, detail = "failed", str(exc)
        stats[status] = stats.get(status, 0) + 1
        if status in ("updated", "would_update", "failed", "parse_error"):
            print(f"[MediaTitleTranslate] {index}/{len(targets)} {status} {path.parent.name}: {detail}", flush=True)
        if args.apply and status == "updated" and index < len(targets):
            time.sleep(random.uniform(args.min_delay, args.max_delay))

    print("[MediaTitleTranslate] done " + " ".join(f"{k}={v}" for k, v in sorted(stats.items())), flush=True)


if __name__ == "__main__":
    sys.exit(main())
