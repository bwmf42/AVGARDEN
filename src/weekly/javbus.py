"""JavBus 个体页刮削：元数据 + 封面下载"""
import html, re, os, time, random, urllib.parse
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

def _file_url(save_dir, avid, filename):
    bucket = os.path.basename(os.path.normpath(save_dir)) or "__weekly__"
    parts = [bucket, avid.upper(), filename]
    return "/file/" + "/".join(urllib.parse.quote(part) for part in parts)

def _cover_paths(avid, save_dir):
    code = avid.upper()
    local_dir = os.path.join(save_dir, code)
    cover_name = f"{code}-cover.jpg"
    return local_dir, cover_name, os.path.join(local_dir, cover_name)

def cover_needs_refresh(avid, save_dir, min_width=300, min_height=400, min_bytes=50 * 1024):
    """低清列表页缩略图需要用详情页 bigImage 刷新。"""
    _, _, local_path = _cover_paths(avid, save_dir)
    if not os.path.exists(local_path):
        return False
    try:
        if os.path.getsize(local_path) < min_bytes:
            return True
        size = _image_size(local_path)
        return bool(size and (size[0] < min_width or size[1] < min_height))
    except OSError:
        return False

def _fanart_paths(avid, save_dir, index):
    code = avid.upper()
    local_dir = os.path.join(save_dir, code)
    filename = f"{code}-fanart-{index}.jpg"
    return local_dir, filename, os.path.join(local_dir, filename)

def _image_url_candidates(url):
    candidates = []
    replacements = (
        ("https://awsimgsrc.dmm.co.jp/", "https://awsimgsrc.dmm.com/"),
        ("https://pics.dmm.co.jp/digital/video/", "https://awsimgsrc.dmm.com/pics_dig/digital/video/"),
        ("http://pics.dmm.co.jp/digital/video/", "https://awsimgsrc.dmm.com/pics_dig/digital/video/"),
    )
    for old, new in replacements:
        if isinstance(url, str) and url.startswith(old):
            candidates.append(new + url[len(old):])
    candidates.append(url)
    result = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result

def _image_fetch_attempts(url, referer):
    proxy = _proxies()
    for candidate in _image_url_candidates(url):
        host = urllib.parse.urlparse(candidate).netloc.lower()
        if host == "image.mgstage.com":
            referers = [
                "https://www.mgstage.com/product/product_detail/",
                "https://www.mgstage.com/",
                "",
                referer,
            ]
            proxy_options = [None]
            if proxy:
                proxy_options.append(proxy)
        else:
            referers = [referer]
            proxy_options = [proxy]
            if proxy:
                proxy_options.append(None)

        seen = set()
        for proxies in proxy_options:
            for ref in referers:
                key = (candidate, ref, bool(proxies))
                if key in seen:
                    continue
                seen.add(key)
                yield candidate, ref, proxies

def _fetch_image_content(url, referer, timeout=15):
    last_error = None
    for candidate, ref, proxies in _image_fetch_attempts(url, referer):
        h = dict(HEADERS)
        if ref:
            h["Referer"] = ref
        else:
            h.pop("Referer", None)
        try:
            r = requests.get(candidate, proxies=proxies, headers=h,
                            impersonate="chrome110", timeout=timeout)
            if r.status_code < 400 and r.content:
                return r.content
            last_error = f"status {r.status_code}"
        except Exception as e:
            last_error = e
    raise RuntimeError(last_error or "image download failed")

def _image_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
        if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        if not head.startswith(b"\xff\xd8"):
            return None
        f.seek(2)
        while True:
            marker = f.read(1)
            while marker and marker != b"\xff":
                marker = f.read(1)
            marker = f.read(1)
            if not marker:
                return None
            while marker == b"\xff":
                marker = f.read(1)
            if marker in (b"\xd8", b"\xd9"):
                continue
            length_data = f.read(2)
            if len(length_data) < 2:
                return None
            length = int.from_bytes(length_data, "big")
            code = marker[0]
            if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                data = f.read(5)
                if len(data) < 5:
                    return None
                return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
            f.seek(length - 2, os.SEEK_CUR)

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

def search_magnet(avid, page_html=""):
    """从 JavBus 详情页 AJAX 磁链列表挑一个磁链。"""
    avid = avid.strip().upper()
    if not avid:
        return ""
    html_text = page_html or fetch_page(avid) or ""
    gid_m = re.search(r'var\s+gid\s*=\s*(\d+)', html_text)
    uc_m = re.search(r'var\s+uc\s*=\s*(\d+)', html_text)
    img_m = re.search(r'var\s+img\s*=\s*[\'"]([^\'"]+)', html_text)
    if not (gid_m and uc_m and img_m):
        return ""

    query = urllib.parse.urlencode({
        "gid": gid_m.group(1),
        "lang": "zh",
        "img": img_m.group(1),
        "uc": uc_m.group(1),
        "floor": random.randint(1, 1000),
    })
    url = f"https://{DOMAIN}/ajax/uncledatoolsbyajax.php?{query}"
    try:
        h = dict(HEADERS)
        h["Referer"] = f"https://{DOMAIN}/{avid}"
        r = requests.get(url, proxies=_proxies(), headers=h,
                        impersonate="chrome110", timeout=20)
        if r.status_code != 200:
            return ""
        return _pick_javbus_magnet(avid, r.text)
    except Exception as e:
        print(f"[JavBus] Magnet {avid}: {e}")
        return ""

def _pick_javbus_magnet(avid, page_html):
    magnets = []
    seen = set()
    for match in re.finditer(r'href=["\'](magnet:\?xt=urn:btih:[^"\']+)["\']', page_html, re.I):
        magnet = html.unescape(match.group(1))
        if magnet in seen:
            continue
        seen.add(magnet)
        row_start = page_html.rfind("<tr", 0, match.start())
        row_end = page_html.find("</tr>", match.end())
        row = html.unescape(page_html[row_start:row_end] if row_start != -1 and row_end != -1 else "")
        text = re.sub(r"<[^>]+>", " ", row)
        text = re.sub(r"\s+", " ", text).strip()
        magnets.append((_javbus_magnet_score(avid, text), magnet))
    if not magnets:
        return ""
    magnets.sort(reverse=True, key=lambda item: item[0])
    return magnets[0][1]

def _javbus_magnet_score(avid, text):
    upper = text.upper()
    code_score = 1 if avid in upper or avid.replace("-", "") in upper.replace("-", "") else 0
    cn_score = 1 if any(k in upper for k in ["中文", "字幕", "-C", "-CH", "CHINESE"]) else 0
    size_score = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|TB)", upper)
    if m:
        size_score = float(m.group(1))
        if m.group(2) == "TB":
            size_score *= 1024
        elif m.group(2) == "MB":
            size_score /= 1024
    return (cn_score, code_score, size_score)

def download_cover(avid, url, save_dir, force=False):
    """下载封面到本地，返回本地路径"""
    if not url:
        return url
    local_dir, cover_name, local_path = _cover_paths(avid, save_dir)
    if os.path.exists(local_path) and not force:
        return _file_url(save_dir, avid, cover_name)
    try:
        os.makedirs(local_dir, exist_ok=True)
        content = _fetch_image_content(url, f"https://{DOMAIN}/", timeout=15)
        with open(local_path, "wb") as f:
            f.write(content)
        return _file_url(save_dir, avid, cover_name)
    except Exception as e:
        print(f"[JavBus] Cover {avid}: {e}")
        return url

def download_fanarts(avid, urls, save_dir, force=False, limit=0):
    """下载详情页预览图到本地，返回 /file/... URL 列表。"""
    if not isinstance(urls, list) or not urls:
        return []
    local_urls = []
    for index, url in enumerate(urls, 1):
        if not url:
            continue
        if limit and index > limit:
            break
        if isinstance(url, str) and url.startswith("/file/"):
            local_urls.append(url)
            continue
        local_dir, filename, local_path = _fanart_paths(avid, save_dir, index)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0 and not force:
            local_urls.append(_file_url(save_dir, avid, filename))
            continue
        try:
            os.makedirs(local_dir, exist_ok=True)
            content = _fetch_image_content(url, f"https://{DOMAIN}/{avid.upper()}", timeout=15)
            with open(local_path, "wb") as f:
                f.write(content)
            local_urls.append(_file_url(save_dir, avid, filename))
        except Exception as e:
            print(f"[JavBus] Fanart {avid} #{index}: {e}")
    return local_urls
