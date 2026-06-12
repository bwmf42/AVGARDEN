"""JavBus 个体页刮削：元数据 + 封面下载"""
import re, os, time
from curl_cffi import requests

DOMAIN = "www.javbus.com"
PROXY = None
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cookie": "age=verified; existmag=mag",
}

def set_proxy(proxy):
    global PROXY
    PROXY = proxy

def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None

def fetch_page(avid):
    """获取 JavBus 个体页 HTML"""
    try:
        h = dict(HEADERS)
        h["Referer"] = f"https://{DOMAIN}/"
        r = requests.get(f"https://{DOMAIN}/{avid.upper()}",
                        proxies=_proxies(), headers=h,
                        impersonate="chrome110", timeout=15,
                        allow_redirects=False)
        if "Age Verification" in r.text[:500] or "<title>404" in r.text:
            return None
        return r.text
    except Exception as e:
        print(f"[JavBus] Fetch {avid}: {e}")
        return None

def parse_page(html):
    """解析个体页 HTML，返回元数据 dict"""
    title_m = re.search(r'<title>(.*?) - JavBus</title>', html)
    title = title_m.group(1).strip() if title_m else ""

    cover_m = re.search(r'<a class="bigImage" href="([^"]+)"', html)
    cover = cover_m.group(1) if cover_m else ""
    if cover and not cover.startswith("http"):
        cover = f"https://{DOMAIN}{cover}"

    actresses = [a.strip() for a in re.findall(
        r'<a class="avatar-box"[^>]*>\s*<div[^>]*>\s*<img[^>]*>\s*</div>\s*<span>([^<]+)</span>',
        html, re.DOTALL
    )]

    genres = []
    for pat in [r'<span class="genre">\s*<label[^>]*>\s*<input[^>]*>\s*<a[^>]*>([^<]+)</a>',
                r'gene">\s*<a href="[^"]*">([^<]+)</a>']:
        genres.extend(g.strip() for g in re.findall(pat, html))
        if genres:
            break

    date_m = re.search(r'發行日期:</span>\s*([^<]+)', html)
    release_date = date_m.group(1).strip() if date_m else ""

    dur_m = re.search(r'長度:</span>\s*([^<]+)', html)
    duration = dur_m.group(1).strip() if dur_m else ""

    fanarts = re.findall(r'<a class="sample-box" href="(.*?\.jpg)"', html)
    fanarts = [f if f.startswith("http") else f"https://{DOMAIN}{f}" for f in fanarts]

    return {
        "title": title, "titleZh": "", "titleJp": "",
        "cover": cover, "poster": "",
        "releaseDate": release_date, "duration": duration,
        "actresses": actresses, "genres": genres,
        "fanarts": fanarts,
        "hasChinese": False, "magnet": "", "downloaded": False, "size": "",
    }

def download_cover(avid, url, save_dir):
    """下载封面到本地，返回本地路径"""
    if not url:
        return url
    local_dir = os.path.join(save_dir, avid.upper())
    local_path = os.path.join(local_dir, f"{avid.upper()}-cover.jpg")
    if os.path.exists(local_path):
        return f"/file/__weekly__/{avid.upper()}/{avid.upper()}-cover.jpg"
    try:
        os.makedirs(local_dir, exist_ok=True)
        h = dict(HEADERS)
        h["Referer"] = f"https://{DOMAIN}/"
        r = requests.get(url, proxies=_proxies(), headers=h,
                        impersonate="chrome110", timeout=15)
        with open(local_path, "wb") as f:
            f.write(r.content)
        return f"/file/__weekly__/{avid.upper()}/{avid.upper()}-cover.jpg"
    except Exception as e:
        print(f"[JavBus] Cover {avid}: {e}")
        return url
