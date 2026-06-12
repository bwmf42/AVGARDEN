#!/usr/bin/env python3
"""补漏：按系列前缀搜索 JavBus，补充首页遗漏的半个月内新片"""
import json, os, sys, re, time, random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.weekly import sources, javbus, sukebei

SAVE_PATH = os.environ.get("SAVE_PATH", "/data")
WEEKLY_DIR = os.path.join(SAVE_PATH, "__weekly__")
WEEKLY_JSON = os.path.join(WEEKLY_DIR, "weekly.json")
PROXY = os.environ.get("PROXY", "") or None
DAYS_BACK = int(os.environ.get("FILL_DAYS", "15"))
PREFIXES = [
    "ADN", "ATID", "WAAA", "START", "MIDV", "CAWD", "SONE", "JUQ",
    "IPZZ", "IPZ", "IPX", "ABF", "DLDSS", "SSIS", "FSDSS", "STARS",
    "PPPE", "MEYD", "MIAA", "MIDE", "MIRD", "MIFD", "MIMK", "MUDR",
    "NACR", "NHDTB", "NSFS", "RBK", "RBD", "RCTD", "ROE", "ROYD",
    "SDAB", "SDDE", "SDJS", "SDMF", "SDMM", "SDNM", "SDMU", "SDSI",
    "SHKD", "SNIS", "SQTE", "SSNI", "TPPN", "TPVR", "UMD", "VEC",
    "VENX", "WANZ", "XVSR", "YMDD", "YMDS", "DV", "DVAJ", "BF",
    "DASS", "HMN", "FNS", "FTHTD", "SNOS", "MKMP", "JUR", "ALDN",
    "NACT", "LUXU", "MIUM", "PARATHD", "MGNL", "NHDTC", "NGHJ",
    "KSBJ", "MFYD", "AWAW", "FTK", "SGKI", "NAMH", "INSTV",
    "MOGI", "CJOD", "MY", "SMOM", "DANDYA", "MOON", "SAN", "HNHU",
]

def log(msg):
    print(f"[FillGap] {msg}", flush=True)

def search_prefix(prefix):
    """搜索给定前缀，返回 movie-box 卡片列表"""
    from curl_cffi import requests
    try:
        h = dict(sources.HEADERS)
        r = requests.get(
            f"https://www.javbus.com/search/{prefix}",
            proxies=sources._proxies(), headers=h,
            impersonate="chrome110", timeout=15, allow_redirects=False
        )
        cards = re.findall(
            r'<a class="movie-box" href="https?://[^"]*?/([A-Z0-9]+-\d+)"[^>]*>'
            r'(.*?)</a>', r.text, re.DOTALL
        )
        results = []
        for avid, body in cards:
            date_m = re.search(r'<date>(\d{4}-\d{2}-\d{2})</date>', body)
            results.append({
                "id": avid.upper(),
                "releaseDate": date_m.group(1) if date_m else "",
            })
        return results
    except Exception as e:
        log(f"  Search {prefix}: {e}")
        return []

def main():
    log("=== Start ===")
    sources.set_proxy(PROXY)
    javbus.set_proxy(PROXY)
    sukebei.set_proxy(PROXY)

    cutoff = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    log(f"Scanning last {DAYS_BACK} days (since {cutoff})")

    existing = json.load(open(WEEKLY_JSON)) if os.path.exists(WEEKLY_JSON) else []
    existing_ids = {i["id"].upper() for i in existing}

    found_new = []
    for prefix in PREFIXES:
        results = search_prefix(prefix)
        for r in results:
            if r["releaseDate"] < cutoff:
                continue
            avid = r["id"]
            if avid in existing_ids:
                continue
            if avid in {f["id"] for f in found_new}:
                continue
            found_new.append(r)
            log(f"  + {avid} ({r['releaseDate']})")
        log(f"  Searched {prefix}: {len(results)} results")
        time.sleep(random.uniform(3, 6))

    log(f"Found {len(found_new)} missed avids")

    if not found_new:
        log("=== Done: nothing missed ===")
        return

    # 逐个刮详细信息
    added = 0
    for item in found_new:
        avid = item["id"]
        html = javbus.fetch_page(avid)
        detail = javbus.parse_page(html) if html else {}
        item.update({k: v for k, v in detail.items() if v})
        if not item.get("title"):
            item["title"] = avid
        item["cover"] = javbus.download_cover(avid, item.get("cover", ""), WEEKLY_DIR)
        item["magnet"] = sukebei.search(avid)
        for k in ["titleZh", "titleJp", "poster", "duration", "size"]:
            item.setdefault(k, "")
        for k in ["actresses", "genres", "fanarts"]:
            item.setdefault(k, [])
        item.setdefault("hasChinese", False)
        item.setdefault("downloaded", False)

        existing.append(item)
        added += 1
        log(f"  Added {avid}: {item.get('title','')[:50]}, magnet={'OK' if item['magnet'] else 'NONE'}")
        time.sleep(random.uniform(5, 10))

    tmp = WEEKLY_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    os.replace(tmp, WEEKLY_JSON)
    log(f"=== Done: {added} added, {len(existing)} total ===")

if __name__ == "__main__":
    main()
