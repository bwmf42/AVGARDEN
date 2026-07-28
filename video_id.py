import re
import unicodedata


_DASH_TRANSLATION = str.maketrans({
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\uff0d": "-",
})

_LOCAL_SOURCE_PREFIXES = ("328", "348", "390", "420", "857", "892")


def _prepare(raw):
    text = unicodedata.normalize("NFKC", str(raw or "")).translate(_DASH_TRANSLATION)
    text = text.strip().upper()
    if not text or len(text) > 64:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    if "/" in text or "\\" in text or ".." in text:
        return ""
    return text


def _canonical_variant_suffix(suffix):
    return "" if suffix == "V" else suffix


def normalize_video_id(raw):
    """Normalize a user-entered video ID without guessing ambiguous formats."""
    text = _prepare(raw)
    if not text:
        return ""

    match = re.fullmatch(r"FC2(?:\s*[-_]?\s*PPV)?\s*[-_]?\s*(\d{5,8})", text)
    if match:
        return f"FC2-{match.group(1)}"

    match = re.fullmatch(r"HEY(?:DOUGA)?\s*[-_]?\s*(\d{4})\s*[-_]\s*0?(\d{3,5})", text)
    if match:
        return f"HEYDOUGA-{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(HEYZO|GETCHU|GYUTTO)\s*[-_]?\s*(\d{3,8})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(MKB?D)\s*[-_]?\s*(S\d{2,3})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(MK3D2DBD|S2M|S2MBD)\s*[-_]?\s*(\d{2,3})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(T[23]8)\s*[-_]?\s*(\d{3})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"R18\s*[-_]?\s*(\d{3})", text)
    if match:
        return f"R18-{match.group(1)}"

    match = re.fullmatch(r"(IBW)\s*[-_]?\s*(\d{2,5}Z)", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(\d{6})[-_](\d{2,3})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    if re.fullmatch(r"(?:N|K)\d{4}|RED[01]\d{2}|SKY[0-3]\d{2}|EX00[01]\d", text):
        return text

    match = re.fullmatch(r"([A-Z0-9]*[A-Z][A-Z0-9]{0,15})\s*[-_]\s*(\d{2,8})([A-Z]?)", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}{_canonical_variant_suffix(match.group(3))}"

    match = re.fullmatch(r"([0-9]*[A-Z][A-Z0-9]*[A-Z])(\d{2,8})([A-Z]?)", text)
    if match and len(match.group(1)) <= 16:
        return f"{match.group(1)}-{match.group(2)}{_canonical_variant_suffix(match.group(3))}"

    if re.fullmatch(r"H_\d{3,4}[A-Z]{1,10}\d{2,5}[A-Z0-9]{0,8}", text):
        return text
    if re.fullmatch(r"\d{3}_\d{4,5}", text):
        return text
    if re.fullmatch(r"402[A-Z]{3,6}\d*_[A-Z]{3,8}\d{5,6}", text):
        return text

    return ""


def normalize_local_video_id(raw):
    """Normalize a local folder/torrent label without stripping real ID prefixes."""
    text = unicodedata.normalize("NFKC", str(raw or "")).translate(_DASH_TRANSLATION)
    text = os_path_basename(text.strip()).upper()
    if not text:
        return ""

    source_prefix = "|".join(re.escape(prefix) for prefix in _LOCAL_SOURCE_PREFIXES)
    match = re.match(
        rf"^(?:{source_prefix})([A-Z][A-Z0-9]{{1,15}}-\d{{2,8}})(?:[-_ .]?CH)(?:$|[-_ .(])",
        text,
    )
    if match:
        normalized = normalize_video_id(match.group(1))
        if normalized:
            return normalized

    match = re.match(
        rf"^(?:{source_prefix})([A-Z][A-Z0-9]{{1,15}}-\d{{2,8}}[A-Z]?)",
        text,
    )
    if match:
        normalized = normalize_video_id(match.group(1))
        if normalized:
            return normalized

    for match in re.finditer(
        r"([0-9]*[A-Z][A-Z0-9]{0,15}-\d{2,8})(?:[-_ .]?CH)(?:$|[-_ .(])",
        text,
    ):
        normalized = normalize_video_id(match.group(1))
        if normalized:
            return normalized

    match = re.match(r"^([0-9]*[A-Z][A-Z0-9]{0,15}-\d{2,8}[A-Z]?)(?:$|[-_ .(])", text)
    if match:
        normalized = normalize_video_id(match.group(1))
        if normalized:
            return normalized

    for match in re.finditer(r"([A-Z][A-Z0-9]{1,15}-\d{2,8}[A-Z]?)", text):
        normalized = normalize_video_id(match.group(1))
        if normalized:
            return normalized
    return normalize_video_id(text)


def local_video_id_aliases(raw):
    """Return a local ID plus its unambiguous pre-migration short alias."""
    code = normalize_local_video_id(raw)
    if not code:
        return ()

    aliases = [code]
    match = re.fullmatch(r"\d+([A-Z][A-Z0-9]{1,15}-\d{2,8}[A-Z]?)", code)
    if match:
        short = normalize_video_id(match.group(1))
        if short and short != code:
            aliases.append(short)
    return tuple(aliases)


def os_path_basename(value):
    return re.split(r"[/\\]", value)[-1]


def safe_video_dir(base_path, raw):
    import os

    code = normalize_video_id(raw)
    if not code:
        raise ValueError("invalid video ID")
    base = os.path.realpath(base_path)
    target = os.path.realpath(os.path.join(base, code))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("video path escapes base directory")
    return target


def safe_local_dir(base_path, raw):
    import os

    name = str(raw or "").strip()
    if not name or name in (".", "..") or os.path.basename(name) != name:
        raise ValueError("invalid local directory name")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("invalid local directory name")
    base = os.path.realpath(base_path)
    target = os.path.realpath(os.path.join(base, name))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("local path escapes base directory")
    return target
