"""Runtime relay settings and non-redirecting credential requests.

Base validation only checks literal hosts, without DNS or network access.
DNS rebinding remains a risk; this unauthenticated LAN API is not an SSRF boundary.
"""
import ipaddress
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from weekly_store import atomic_write_json, json_update_lock

TRANSLATION_MAX_TOKENS = 2048
MAX_SETTINGS_BODY = 4096


class SettingsValidationError(ValueError):
    """Safe, fixed validation messages that may be returned to the caller."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never copy Authorization to another request, including same-host redirects.
        raise urllib.error.HTTPError("", code, "translation redirect refused", None, None)


def open_translation_request(request, timeout):
    return urllib.request.build_opener(NoRedirectHandler()).open(request, timeout=timeout)


def redact_credentials(text, secrets):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[已隐藏]")
    return text


def _path():
    return os.environ.get("TRANSLATE_SETTINGS_PATH", "/db/translate_settings.json")


def _env_relay():
    return (os.environ.get("TRANSLATE_API_BASE", "").strip().rstrip("/"),
            os.environ.get("TRANSLATE_API_KEY", "").strip(),
            (os.environ.get("TRANSLATE_MODEL") or "gpt-5.4").strip())


def _unsafe(value):
    return any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)


def _private_host(host):
    host = host.lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return (address.is_loopback or address.is_link_local
            or address.is_private or address.is_unspecified)


def _validate(data, saved=False):
    if not isinstance(data, dict) or set(data) - {"base", "key", "model", "mode"}:
        raise SettingsValidationError("设置必须是仅含 base、key、model、mode 的 JSON 对象")
    data = dict(data)
    if "mode" in data and (not isinstance(data["mode"], str) or data["mode"] not in ("auto", "deepseek")):
        if saved:
            data.pop("mode")
        else:
            raise SettingsValidationError("翻译源模式只能是 auto 或 deepseek")
    for field, value in data.items():
        if not isinstance(value, str):
            raise SettingsValidationError("设置字段必须是字符串")
        if field == "base":
            if saved and value == "":
                continue
            try:
                url = urlsplit(value)
                valid = (value.startswith(("http://", "https://")) and url.hostname
                         and url.username is None and url.password is None
                         and "?" not in value and "#" not in value)
                url.port  # Reject malformed ports as well.
            except ValueError:
                valid = False
            if len(value) > 300 or _unsafe(value) or not valid:
                raise SettingsValidationError("Base URL 必须是有效的 HTTP/HTTPS 地址，不得含凭据、查询串、片段、空白或控制字符，最多 300 字符")
            if (_private_host(url.hostname)
                    and os.environ.get("TRANSLATE_ALLOW_PRIVATE_BASE", "").lower() not in ("1", "true")):
                raise SettingsValidationError("Base URL 不允许使用本机或私有地址")
        elif field == "key":
            if value and (not 8 <= len(value) <= 300 or _unsafe(value)):
                raise SettingsValidationError("API Key 须为 8 至 300 字符且无空白或控制字符；空字符串表示清除")
        elif field == "model" and not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", value):
            raise SettingsValidationError("模型名须为 1 至 100 字符，仅允许字母、数字和 ._:/-")
    return {k: v.rstrip("/") if k == "base" else v for k, v in data.items()}


def _read():
    try:
        with open(_path(), encoding="utf-8") as handle:
            return _validate(json.load(handle), saved=True)
    except (OSError, ValueError, UnicodeError):
        return {}


def effective_relay(fallback=None):
    """Read on every call; callers may supply their patchable environment defaults."""
    settings = _read()
    if settings.get("mode") == "deepseek":
        return "", "", settings.get("model") or "gpt-5.4"
    if settings.get("base") and settings.get("key"):
        return settings["base"], settings["key"], settings.get("model") or "gpt-5.4"
    return fallback if fallback is not None else _env_relay()


def _public(settings):
    # Show incomplete saved drafts so changing base/clearing key is visible to UI.
    # In auto mode, translation calls use the environment relay until complete.
    if settings:
        base, key, model = (settings.get(k, "") for k in ("base", "key", "model"))
        source = "file"
    else:
        base, key, model = _env_relay()
        source = "env" if base and key else "none"
    # Do not transform public fields based on any secret (a credential oracle).
    complete = bool(settings.get("base") and settings.get("key"))
    mode = settings.get("mode", "auto")
    result = {"base": base, "model": model, "key_set": bool(key), "source": source,
              "deepseek_set": bool(os.environ.get("DEEPSEEK_API_KEY")), "complete": complete,
              "mode": mode, "relay_enabled": mode == "auto"}
    if mode == "deepseek":
        result["hint"] = "当前只使用 DeepSeek，中继已停用"
    elif not complete:
        result["hint"] = "尚未生效：需要同时保存 Base URL 和 API Key，当前仍在使用环境变量里的配置"
    return result


def public_settings():
    return _public(_read())


def save_settings(changes):
    changes = _validate(changes)
    if changes.get("key") and "base" not in changes:
        raise SettingsValidationError("保存 API Key 时必须同时提交 Base URL，确保密钥发往你看到的地址")
    path = _path()
    with json_update_lock(path):
        stored = _read()
        # Compare the relay configuration independently of its enabled mode.
        current_base = (stored["base"] if stored.get("base") and stored.get("key")
                        else _env_relay()[0])
        # Environment credentials remain runtime fallback, never persisted implicitly.
        settings = stored
        if "base" in changes and changes["base"] != current_base and "key" not in changes:
            settings["key"] = ""
        settings.update(changes)
        atomic_write_json(path, settings)  # mkstemp creates a 0600 sibling.
        return _public(settings)
