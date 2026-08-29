#!/usr/bin/env python3
"""把 115 备份下的「艾薇」内容软链到 data 根目录（不出现 艾薇 文件夹本身）。

默认布局::

    {data_root}/115生活备份/艾薇/ABF-373/...
    {data_root}/ABF-373 -> 115生活备份/艾薇/ABF-373

用法::

    python3 tools/maintenance/link_115_aiwei_into_data_root.py
    python3 tools/maintenance/link_115_aiwei_into_data_root.py --data-root /data
    python3 tools/maintenance/link_115_aiwei_into_data_root.py --dry-run

也可被 launcher / heal_runner 周期调用（import sync_links）。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Optional


def sync_links(
    data_root: Optional[str] = None,
    source_rel: Optional[str] = None,
    *,
    dry_run: bool = False,
    remove_aiwei_link: bool = True,
) -> Dict[str, Any]:
    """Create/update per-title symlinks under data_root.

    Returns stats: linked, refreshed, skipped, removed_aiwei, missing_source, names.
    """
    root = os.path.realpath(
        data_root
        or os.environ.get("SAVE_PATH")
        or os.environ.get("DATA_ROOT")
        or "/data"
    )
    source_rel = (
        source_rel
        or os.environ.get("LINK115_SOURCE_REL")
        or "115生活备份/艾薇"
    )
    src = os.path.join(root, source_rel)
    result: Dict[str, Any] = {
        "root": root,
        "source_rel": source_rel,
        "linked": 0,
        "refreshed": 0,
        "skipped": 0,
        "removed_aiwei": 0,
        "missing_source": False,
        "names": [],
    }
    if not os.path.isdir(src):
        result["missing_source"] = True
        return result

    # 不要在 2 下出现「艾薇」入口
    aiwei = os.path.join(root, "艾薇")
    if remove_aiwei_link and os.path.islink(aiwei):
        if not dry_run:
            os.unlink(aiwei)
        result["removed_aiwei"] = 1

    for name in sorted(os.listdir(src)):
        if name.startswith("."):
            continue
        if name.lower().endswith((".url", ".parts", ".ds_store")):
            continue
        src_item = os.path.join(src, name)
        if not (os.path.isdir(src_item) or os.path.isfile(src_item)):
            continue
        dest = os.path.join(root, name)
        rel_target = os.path.join(source_rel, name)
        if os.path.islink(dest):
            cur = os.readlink(dest)
            if cur == rel_target or os.path.realpath(dest) == os.path.realpath(src_item):
                result["skipped"] += 1
                continue
            if not dry_run:
                os.unlink(dest)
                os.symlink(rel_target, dest)
            result["refreshed"] += 1
            result["names"].append(name)
        elif os.path.exists(dest):
            result["skipped"] += 1
        else:
            if not dry_run:
                os.symlink(rel_target, dest)
            result["linked"] += 1
            result["names"].append(name)
    return result


def remove_reverse_links(
    data_root: Optional[str] = None,
    source_rel: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Unlink 艾薇 placeholders that point back into the library.

    Only deletes symlinks. Real directories and files are left untouched.
    """
    root = os.path.realpath(
        data_root
        or os.environ.get("SAVE_PATH")
        or os.environ.get("DATA_ROOT")
        or "/data"
    )
    source_rel = (
        source_rel
        or os.environ.get("LINK115_SOURCE_REL")
        or "115生活备份/艾薇"
    )
    src = os.path.join(root, source_rel)
    result: Dict[str, Any] = {
        "root": root,
        "source_rel": source_rel,
        "removed": 0,
        "kept_real": 0,
        "kept_other": 0,
        "missing_source": False,
        "names": [],
    }
    if not os.path.isdir(src):
        result["missing_source"] = True
        return result

    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if not os.path.islink(path):
            if os.path.exists(path):
                result["kept_real"] += 1
            continue
        target = os.readlink(path)
        # reverse placeholders look like ../../CODE or an absolute path outside 艾薇
        abs_target = target if os.path.isabs(target) else os.path.normpath(os.path.join(src, target))
        inside_src = os.path.commonpath([os.path.realpath(src), os.path.realpath(os.path.dirname(abs_target) or src)]) == os.path.realpath(src)
        if inside_src and not target.startswith(".."):
            result["kept_other"] += 1
            continue
        if not dry_run:
            os.unlink(path)
        result["removed"] += 1
        result["names"].append(name)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        default=os.environ.get("SAVE_PATH") or os.environ.get("DATA_ROOT") or "/data",
        help="媒体根目录（容器内通常是 /data，对应 NAS 的 …/data2/115生活备份）",
    )
    parser.add_argument(
        "--source-rel",
        default=os.environ.get("LINK115_SOURCE_REL") or "115生活备份/艾薇",
        help="相对 data-root 的 115 备份源路径",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keep-aiwei-link",
        action="store_true",
        help="保留 data-root/艾薇 软链（默认会删掉）",
    )
    parser.add_argument(
        "--remove-reverse",
        action="store_true",
        help="只删除 艾薇 下指回片库的占位软链，不动真目录",
    )
    args = parser.parse_args()

    if args.remove_reverse:
        stats = remove_reverse_links(
            data_root=args.data_root,
            source_rel=args.source_rel,
            dry_run=args.dry_run,
        )
        if stats.get("missing_source"):
            print(f"source missing: {stats['root']}/{stats['source_rel']}", file=sys.stderr)
            return 1
        print(
            f"remove-reverse removed={stats['removed']} kept_real={stats['kept_real']} "
            f"kept_other={stats['kept_other']} root={stats['root']}"
        )
        return 0

    stats = sync_links(
        data_root=args.data_root,
        source_rel=args.source_rel,
        dry_run=args.dry_run,
        remove_aiwei_link=not args.keep_aiwei_link,
    )
    if stats.get("missing_source"):
        print(f"source missing: {stats['root']}/{stats['source_rel']}", file=sys.stderr)
        return 1
    if stats.get("removed_aiwei"):
        print("remove link: 艾薇")
    for name in stats.get("names") or []:
        print(f"link: {name}")
    print(
        f"done linked={stats['linked']} refreshed={stats['refreshed']} "
        f"skipped={stats['skipped']} root={stats['root']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
