"""115 网盘云下载（Cookie，无需官方 OpenAPI）。

将 magnet 提交到 115「云下载」（原离线下载），保存到指定网盘目录（如 /艾薇），
本地落盘由极空间「115生活 · 自动备份」完成。

优先走 urllib 直连（避免 p115client 在部分环境下 generator/context 兼容问题），
p115client 作为可选增强。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional, Tuple

CONFIG_PATH = os.environ.get("P115_CONFIG_PATH", "/db/p115_config.json")
COOKIES_PATH = os.environ.get("P115_COOKIES_PATH", "/db/115-cookies.txt")

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


PROBE_TTL_SECONDS = max(30, int(os.environ.get("P115_PROBE_TTL", "120") or "120"))


def load_config() -> dict:
    cfg = {
        "enabled": False,
        "save_path": "/艾薇",
        "cookies": "",
        # 仅测试连接成功后为 True；改 Cookie/路径后清零
        "verified": False,
        "verified_at": 0.0,
        "last_error": "",
        "last_msg": "",
    }
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in cfg if k in data})
    except Exception:
        pass
    try:
        if os.path.isfile(COOKIES_PATH):
            text = Path(COOKIES_PATH).read_text(encoding="utf-8").strip()
            if text:
                cfg["cookies"] = text
    except Exception:
        pass
    env_ck = (os.environ.get("P115_COOKIES") or "").strip()
    if env_ck:
        cfg["cookies"] = env_ck
    env_path = (os.environ.get("P115_SAVE_PATH") or "").strip()
    if env_path:
        cfg["save_path"] = env_path
    if os.environ.get("P115_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        cfg["enabled"] = True
    return cfg


def _persist_store(cur: dict) -> None:
    store = {
        "enabled": bool(cur.get("enabled")),
        "save_path": cur.get("save_path") or "/艾薇",
        "verified": bool(cur.get("verified")),
        "verified_at": float(cur.get("verified_at") or 0),
        "last_error": str(cur.get("last_error") or ""),
        "last_msg": str(cur.get("last_msg") or ""),
        "cookies_file": COOKIES_PATH,
        "has_cookies": bool(cur.get("cookies")),
    }
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


# 保存时只保留这些键（整表粘贴会丢掉 acw_tc 等噪音）
_COOKIE_KEEP = (
    "UID",
    "CID",
    "SEID",
    "KID",
    "USERSESSIONID",
    "PHPSESSID",
    "115_lang",
)


def normalize_cookies_input(raw: str) -> str:
    """把各种粘贴格式归一成 Cookie 头一行：UID=…; CID=…; SEID=…

    支持：
    - 标准头：``UID=x; CID=y; SEID=z``
    - 开发者工具 Application → Cookies 整表（Name / Value / Domain 多列，Tab 或空格）
    - 多行 ``Name=Value`` / ``Name: Value``
    """
    text = (raw or "").strip()
    if not text:
        return ""

    found: dict[str, str] = {}

    def _put(name: str, value: str, domain: str = "") -> None:
        name = (name or "").strip()
        value = (value or "").strip().strip('"').strip("'")
        if not name or not value:
            return
        # 不要 acw_tc 等
        upper = name.upper()
        keep = {k.upper(): k for k in _COOKIE_KEEP}
        if upper not in keep:
            return
        canonical = keep[upper]
        dom = (domain or "").strip().lower()
        # 有 Domain 列时优先 .115.com / 115.com；子域 acw 已被过滤
        if dom and "115.com" not in dom and "115" not in dom:
            return
        # 同名后写覆盖（表里通常只有一条有效）
        found[canonical] = value

    # 1) 标准 cookie header：含 UID= 且有分号
    if "UID=" in text and ";" in text and "\t" not in text.split("\n", 1)[0]:
        # 可能混有换行，先压成一行再按 ; 拆
        one = re.sub(r"[\r\n]+", " ", text)
        for part in one.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            n, v = part.split("=", 1)
            _put(n, v)

    # 2) 多行表格 / Name Value Domain
    if len(found) < 3:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("name"):
                continue
            # Tab 分隔（Chrome 复制常见）
            if "\t" in line:
                cols = [c.strip() for c in line.split("\t")]
            else:
                # 多空格：Name  Value  Domain  Path  ...
                cols = re.split(r"\s{2,}|\s+", line, maxsplit=6)
            if len(cols) >= 2:
                name, value = cols[0], cols[1]
                domain = cols[2] if len(cols) >= 3 else ""
                # 避免把 Medium/会话 当 value
                if name.upper() in {k.upper() for k in _COOKIE_KEEP}:
                    _put(name, value, domain)
                    continue
            # Name=Value / Name: Value
            m = re.match(r"^([A-Za-z0-9_]+)\s*[=:]\s*(.+)$", line)
            if m:
                _put(m.group(1), m.group(2).split()[0] if m.group(2) else "")

    # 3) 仍不够：全文扫 KEY=value
    if len(found) < 3:
        for key in _COOKIE_KEEP:
            m = re.search(rf"(?:^|[;\s\t]){re.escape(key)}=([^\s;]+)", text, re.I | re.M)
            if m:
                _put(key, m.group(1))

    # 有序输出
    parts = []
    for key in _COOKIE_KEEP:
        if key in found:
            parts.append(f"{key}={found[key]}")
    if not parts:
        # 兜底：当用户贴的已经是干净一行，原样压平
        return re.sub(r"\s*;\s*", "; ", re.sub(r"[\r\n]+", " ", text)).strip().strip(";")
    return "; ".join(parts)


def save_config(data: dict) -> dict:
    """Persist config. 改 Cookie/路径会清除 verified，须重新测试连接。"""
    cur = load_config()
    prev_cookies = (cur.get("cookies") or "").strip()
    prev_path = (cur.get("save_path") or "").strip()
    cookies_changed = False
    path_changed = False

    cookies_raw = str(data.get("cookies") or "").strip()
    if cookies_raw:
        cookies = normalize_cookies_input(cookies_raw)
        if not cookies or not re.search(r"(?:^|;\s*)UID=", cookies, re.I):
            # 无有效 UID 视为粘贴失败，不落盘、不改现有 Cookie
            raise ValueError(
                "未能识别有效 Cookie（需要至少含 UID）。"
                "可粘贴请求头 cookie 一行，或开发者工具 Cookies 整表"
            )
        os.makedirs(os.path.dirname(COOKIES_PATH) or ".", exist_ok=True)
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            f.write(cookies + "\n")
        try:
            os.chmod(COOKIES_PATH, 0o600)
        except OSError:
            pass
        if cookies != prev_cookies:
            cookies_changed = True
        cur["cookies"] = cookies
    elif "cookies" in data and not cookies_raw:
        if os.path.isfile(COOKIES_PATH):
            try:
                os.remove(COOKIES_PATH)
            except OSError:
                pass
        if prev_cookies:
            cookies_changed = True
        cur["cookies"] = ""

    if "enabled" in data:
        cur["enabled"] = bool(data["enabled"])
    if "save_path" in data and str(data["save_path"]).strip():
        new_path = str(data["save_path"]).strip()
        if new_path != prev_path:
            path_changed = True
        cur["save_path"] = new_path

    if cookies_changed or path_changed or not cur.get("cookies"):
        cur["verified"] = False
        cur["verified_at"] = 0.0
        cur["last_error"] = "" if cur.get("cookies") else "未配置 Cookie"
        cur["last_msg"] = ""

    _persist_store(cur)
    return public_config()


def set_verified(ok: bool, msg: str = "") -> dict:
    cur = load_config()
    cur["verified"] = bool(ok) and bool(cur.get("cookies"))
    cur["verified_at"] = time.time()
    text = str(msg or "").strip()[:200]
    if cur["verified"]:
        cur["last_error"] = ""
        cur["last_msg"] = text
    else:
        cur["last_error"] = text or ("未配置 Cookie" if not cur.get("cookies") else "Cookie 已失效")
        cur["last_msg"] = ""
    _persist_store(cur)
    return public_config()


def public_config(*, refresh: bool = False) -> dict:
    if refresh:
        probe_cached()
    cfg = load_config()
    ck = cfg.get("cookies") or ""
    masked = ""
    if ck:
        m = re.search(r"UID=([^;]+)", ck)
        uid = (m.group(1)[:12] + "…") if m else "已配置"
        masked = uid
    verified = bool(cfg.get("verified")) and bool(ck)
    enabled = bool(cfg.get("enabled"))
    message = ""
    if not ck:
        message = "未配置 Cookie"
    elif not verified:
        message = str(cfg.get("last_error") or "Cookie 已失效，请到设置重新测试连接")
    elif cfg.get("last_msg"):
        message = str(cfg.get("last_msg"))
    return {
        "enabled": enabled,
        "save_path": cfg.get("save_path") or "/艾薇",
        "has_cookies": bool(ck),
        "verified": verified,
        "cookies_hint": masked,
        "cookies_path": COOKIES_PATH,
        "available": enabled and bool(ck) and verified,
        "message": message,
        "verified_at": float(cfg.get("verified_at") or 0),
    }


def probe_cached(ttl: Optional[int] = None, force: bool = False) -> Tuple[bool, str]:
    """Reuse last test_connection() result within ttl seconds."""
    cfg = load_config()
    cookies = (cfg.get("cookies") or "").strip()
    if not cookies:
        set_verified(False, "未配置 Cookie")
        return False, "未配置 Cookie"
    wait = PROBE_TTL_SECONDS if ttl is None else max(0, int(ttl))
    last = float(cfg.get("verified_at") or 0)
    if not force and last > 0 and (time.time() - last) < wait:
        if cfg.get("verified"):
            return True, str(cfg.get("last_msg") or "cached ok")
        return False, str(cfg.get("last_error") or "Cookie 已失效")
    return test_connection()


def _auth_failure_message(body: Optional[dict], fallback: str = "") -> str:
    parts = [fallback or ""]
    errno = None
    if isinstance(body, dict):
        parts.extend(
            [
                str(body.get("error") or ""),
                str(body.get("msg") or ""),
                str(body.get("message") or ""),
                str(body.get("errormsg") or ""),
            ]
        )
        errno = body.get("errno") if body.get("errno") is not None else body.get("errNo")
        if errno is None:
            errno = body.get("code")
        if body.get("state") is False and errno in (99, "99", 401, "401", 911, "911"):
            return str(body.get("error") or body.get("msg") or "登录失效，请重新复制 Cookie")[:160]
    text = " ".join(p for p in parts if p).strip()
    low = text.lower()
    needles = ("请先登录", "登录失效", "未登录", "login", "cookie", "过期", "重新登录", "重新复制")
    if any(n.lower() in low for n in needles):
        return (text or "登录失效，请重新复制 Cookie")[:160]
    return ""


def _note_auth_failure(body: Optional[dict], fallback: str = "") -> None:
    msg = _auth_failure_message(body, fallback)
    if msg:
        set_verified(False, msg)


def _cookie_headers(cookies: str) -> dict:
    return {
        "User-Agent": _UA,
        "Cookie": cookies.strip(),
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }


def _http_json(
    url: str,
    *,
    cookies: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    timeout: int = 30,
) -> dict:
    headers = _cookie_headers(cookies)
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            return {"state": False, "error": f"HTTP {e.code}", "raw": raw[:300]}
        if isinstance(body, dict):
            body.setdefault("error", f"HTTP {e.code}")
            return body
        return {"state": False, "error": f"HTTP {e.code}", "raw": raw[:300]}
    try:
        body = json.loads(raw) if raw else {}
    except Exception:
        return {"state": False, "error": "invalid json", "raw": raw[:300]}
    return body if isinstance(body, dict) else {"state": False, "data": body}


def resolve_dir_id_raw(cookies: str, path: str) -> Tuple[Optional[int], str]:
    """Resolve /艾薇 → cid via webapi.files walk. Returns (cid, error_msg)."""
    path = (path or "/").strip() or "/"
    if path in ("/", ""):
        return 0, ""
    parts = [p for p in path.strip("/").split("/") if p]
    cid = 0
    for part in parts:
        url = "https://webapi.115.com/files?" + urllib.parse.urlencode(
            {"cid": cid, "show_dir": 1, "limit": 1150}
        )
        data = _http_json(url, cookies=cookies, timeout=30)
        if data.get("state") is False:
            return None, str(data.get("error") or data.get("msg") or "列目录失败")[:160]
        rows = data.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("list") or []
        found = None
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = row.get("n") or row.get("name") or ""
            if name != part:
                continue
            # directory rows typically have cid
            rid = row.get("cid")
            if rid is None:
                continue
            found = int(rid)
            break
        if found is None:
            return None, f"网盘目录不存在: {path}（缺「{part}」）"
        cid = found
    return cid, ""


def fetch_cloud_sign(cookies: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return (sign, time, err)."""
    # 新版 UI「云下载」对应 clouddownload space
    for url in (
        "https://115.com/?ct=clouddownload&ac=space",
        "https://115.com/?ct=offline&ac=space",
        "https://webapi.115.com/offline/space",
    ):
        try:
            data = _http_json(url, cookies=cookies, timeout=20)
        except Exception as e:
            continue
        # responses vary: {sign, time} or {data: {sign, time}}
        sign = data.get("sign")
        ts = data.get("time")
        if sign is None and isinstance(data.get("data"), dict):
            sign = data["data"].get("sign")
            ts = data["data"].get("time")
        if sign is not None and ts is not None:
            return str(sign), str(ts), ""
    return None, None, "无法获取云下载 sign（Cookie 可能失效）"


def _is_ok_body(body: dict) -> bool:
    if not isinstance(body, dict):
        return False
    if body.get("state") in (True, 1, "1"):
        return True
    # some endpoints use errno=0
    if body.get("errno") in (0, "0") and body.get("error") in (None, "", 0, "0"):
        return True
    return False


def submit_magnet(
    magnet: str,
    *,
    cookies: Optional[str] = None,
    save_path: Optional[str] = None,
) -> Tuple[bool, str, dict]:
    """Submit one magnet to 115 云下载.

    Returns (ok, message, raw_response_dict).
    """
    magnet = (magnet or "").strip()
    if not magnet.lower().startswith("magnet:"):
        return False, "invalid magnet", {}

    cfg = load_config()
    cookies = (cookies or cfg.get("cookies") or "").strip()
    if not cookies:
        return False, "未配置 115 Cookie", {}

    save_path = (save_path or cfg.get("save_path") or "/艾薇").strip() or "/艾薇"

    # ----- 1) raw HTTP（稳定，避免 p115client generator 问题）-----
    try:
        ok, msg, body = _raw_add_task_url(cookies, magnet, save_path)
        if ok:
            return True, msg, body
        raw_err = msg
        _note_auth_failure(body if isinstance(body, dict) else {}, raw_err)
    except Exception as e:
        raw_err = str(e)
        body = {}

    # ----- 2) p115client 兜底 -----
    try:
        from p115client import P115Client, check_response

        client = P115Client(cookies)
        pid, dir_err = resolve_dir_id_raw(cookies, save_path)
        if pid is None and save_path not in ("/", ""):
            _note_auth_failure(body if isinstance(body, dict) else {}, dir_err or "")
            return False, dir_err or f"目录无效: {save_path}", body if isinstance(body, dict) else {}

        payload: dict[str, Any] = {"url": magnet}
        if pid is not None:
            payload["wp_path_id"] = pid

        # 补 sign/time（部分账号接口需要）
        sign, ts, _ = fetch_cloud_sign(cookies)
        if sign and ts:
            payload["sign"] = sign
            payload["time"] = ts

        resp = None
        if hasattr(client, "clouddownload_task_add_url"):
            resp = client.clouddownload_task_add_url(payload)
        elif hasattr(client, "offline_add_url"):
            resp = client.offline_add_url(payload)
        else:
            resp = None

        resp = _coerce_dict(resp)
        if resp:
            try:
                check_response(resp)
                return True, f"已提交 115 云下载 → {save_path}", resp
            except Exception as e:
                # check_response 失败但 body 可能已成功
                if _is_ok_body(resp):
                    return True, f"已提交 115 云下载 → {save_path}", resp
                _note_auth_failure(resp, str(e))
                return False, f"115 拒绝: {e}; raw: {raw_err[:80]}", resp
    except ImportError:
        pass
    except Exception as e:
        raw_err = f"{raw_err}; p115client: {e}"[:200]

    fail_body = body if isinstance(body, dict) else {}
    _note_auth_failure(fail_body, raw_err)
    return False, f"115 云下载失败: {raw_err}"[:220], fail_body


def _coerce_dict(resp: Any) -> dict:
    if isinstance(resp, dict):
        return resp
    if resp is None:
        return {}
    # 避免把 generator 当 context manager
    if hasattr(resp, "__iter__") and not isinstance(resp, (str, bytes, list, tuple, dict)):
        try:
            # 同步 API 不应返回 generator；若返回则放弃
            return {}
        except Exception:
            return {}
    if isinstance(resp, (str, bytes)):
        try:
            data = json.loads(resp)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _raw_add_task_url(cookies: str, magnet: str, save_path: str) -> Tuple[bool, str, dict]:
    """Cookie 直连 115 云下载 add_task_url。"""
    cid, err = resolve_dir_id_raw(cookies, save_path)
    if cid is None:
        return False, err or f"目录无效: {save_path}", {}

    sign, ts, sign_err = fetch_cloud_sign(cookies)
    form_fields = {
        "url": magnet,
        "savepath": "",
        "wp_path_id": str(cid),
    }
    if sign and ts:
        form_fields["sign"] = sign
        form_fields["time"] = ts

    form = urllib.parse.urlencode(form_fields).encode()
    endpoints = (
        "https://115.com/web/lixian/?ct=lixian&ac=add_task_url",
        "https://clouddownload.115.com/lixianssp/?ac=add_task_url",
        "https://115.com/?ct=lixian&ac=add_task_url",
    )
    last_body: dict = {}
    last_err = sign_err or ""
    for post_url in endpoints:
        try:
            body = _http_json(post_url, cookies=cookies, method="POST", data=form, timeout=45)
        except Exception as e:
            last_err = str(e)
            continue
        last_body = body
        if _is_ok_body(body):
            return True, f"已提交 115 云下载 → {save_path}", body
        err = body.get("error") or body.get("message") or body.get("msg") or body.get("errormsg")
        if err is not None and str(err) not in ("", "0", "None"):
            last_err = str(err)[:160]
        else:
            last_err = str(body)[:160]

    return False, f"115 拒绝: {last_err or 'unknown'}", last_body


def test_connection() -> Tuple[bool, str]:
    """Probe Cookie + save_path. 成功则 verified=True。"""
    cfg = load_config()
    cookies = (cfg.get("cookies") or "").strip()
    if not cookies:
        set_verified(False, "未配置 Cookie")
        return False, "未配置 Cookie"
    path = cfg.get("save_path") or "/艾薇"

    # 轻量：列根目录
    try:
        root = _http_json(
            "https://webapi.115.com/files?" + urllib.parse.urlencode({"cid": 0, "show_dir": 1, "limit": 5}),
            cookies=cookies,
            timeout=20,
        )
    except Exception as e:
        set_verified(False, f"连接失败: {e}"[:160])
        return False, f"连接失败: {e}"[:160]

    if root.get("state") is False:
        msg = str(root.get("error") or root.get("msg") or "登录失效，请重新复制 Cookie")[:160]
        set_verified(False, msg)
        return False, msg

    cid, err = resolve_dir_id_raw(cookies, path)
    if cid is None and path not in ("/", ""):
        msg = err or f"Cookie 有效，但目录 {path} 未找到（请先在 115 创建）"
        set_verified(False, msg)
        return False, msg

    # 可选：云下载配额
    quota_hint = ""
    try:
        q = _http_json(
            "https://clouddownload.115.com/?ac=get_quota_info",
            cookies=cookies,
            timeout=15,
        )
        if isinstance(q, dict) and q.get("state") is not False:
            # fields vary
            left = q.get("surplus") or q.get("count") or (q.get("data") or {}).get("surplus")
            if left is not None:
                quota_hint = f"，云下载配额信息已读到"
    except Exception:
        pass

    ok_msg = f"测试通过：Cookie 有效，目标目录 {path} cid={cid}{quota_hint}"
    set_verified(True, ok_msg)
    return True, ok_msg
