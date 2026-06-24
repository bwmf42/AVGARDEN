"""JavBus 个体页刮削：元数据 + 封面下载"""
import re, os, time
from curl_cffi import requests
from PIL import Image

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

def _weekly_file_url(avid, filename):
    return f"/file/__weekly__/{avid.upper()}/{filename}"

def _cover_paths(avid, save_dir):
    code = avid.upper()
    local_dir = os.path.join(save_dir, code)
    cover_name = f"{code}-cover.jpg"
    poster_name = f"{code}-poster.jpg"
    return (
        local_dir,
        cover_name,
        poster_name,
        os.path.join(local_dir, cover_name),
        os.path.join(local_dir, poster_name),
    )

def crop_weekly_poster(cover_path, poster_path):
    try:
        img = Image.open(cover_path)
        width, height = img.size
        if height <= 0 or width <= 0:
            return False
        if height > width:
            img.save(poster_path)
            return True
        target_width = int(height * 565 / 800)
        left = max(0, width - target_width)
        img.crop((left, 0, width, height)).save(poster_path)
        return True
    except Exception as e:
        print(f"[JavBus] Poster crop failed: {e}")
        return False

def ensure_poster(avid, save_dir):
    """确保 weekly 本地竖版 poster 存在，返回前端可访问路径。"""
    _, _, poster_name, cover_path, poster_path = _cover_paths(avid, save_dir)
    if os.path.exists(poster_path):
        return _weekly_file_url(avid, poster_name)
    if os.path.exists(cover_path) and crop_weekly_poster(cover_path, poster_path):
        return _weekly_file_url(avid, poster_name)
    return ""

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
    local_dir, cover_name, _, local_path, _ = _cover_paths(avid, save_dir)
    if os.path.exists(local_path):
        ensure_poster(avid, save_dir)
        return _weekly_file_url(avid, cover_name)
    try:
        os.makedirs(local_dir, exist_ok=True)
        h = dict(HEADERS)
        h["Referer"] = f"https://{DOMAIN}/"
        r = requests.get(url, proxies=_proxies(), headers=h,
                        impersonate="chrome110", timeout=15)
        with open(local_path, "wb") as f:
            f.write(r.content)
        ensure_poster(avid, save_dir)
        return _weekly_file_url(avid, cover_name)
    except Exception as e:
        print(f"[JavBus] Cover {avid}: {e}")
        return url
