"""Actress name cleanup + title-tail extraction.

- Drop placeholders like ----
- Optionally pull trailing names from JP title when field is empty
- Keep actress names untranslated in titleZh (append JP originals)
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Sequence, Tuple

# Forum/DMM scrape junk
_BAD_EXACT = {
    "",
    "-",
    "--",
    "---",
    "----",
    "-----",
    "——",
    "—",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "不明",
    "未定",
    "素人",  # too generic as sole "actress"
}

# Title endings that look like name tokens but are not people
_NOT_NAME = {
    "映像", "作品", "特別", "限定", "完全", "独占", "配信", "収録", "総集編",
    "時間", "分", "編", "版", "特典", "本編", "前編", "後編", "中編",
    "中出し", "痴女", "熟女", "美少女", "女子", "男子", "人妻", "女優",
    "ギャル", "素人", "痴漢", "凌辱", "輪姦", "近親", "相姦", "姉妹",
    "兄妹", "姉弟", "母子", "義父", "義母", "教師", "学生", "制服",
    "水着", "浴衣", "巨乳", "美乳", "貧乳", "中出し", "顔射", "口内",
    "セックス", "エッチ", "プレイ", "ドキュメント", "ドラマ",
    "オフィス", "学校", "教室", "家庭", "温泉", "旅行", "病院",
    "夏祭り", "真夏", "冬", "春", "秋", "夏",
    "ムスメ", "連続", "特化", "感謝祭", "ドキュメンタリー",
}

# Plot / act keywords that never appear in real person names
_PLOT_KW_RE = re.compile(
    r"フェラ|セックス|中出|中出し|巨尻|人妻|連続|屈さ|選手|限定|ムスメ|"
    r"プレイ|特化|潮吹|感謝|敏感|体質|寝取|ドキュメント|すべて表示|"
    r"ギャル女装|百戦|思春期|メガ|ファン|ノーハンド|吸引|耐え|"
    r"射精|絶頂|痙攣|拘束|調教|輪●|レ×プ|生ハメ|口内|顔射|"
    r"パイパン|痴女|熟女|美少女|女優|オナホ|肉便器|子宮|"
    r"イキ|喘|悶|咥|舐|挿入|ピストン|ハメ撮り"
)

# Real JP name shapes (used when extracting from title tail)
# 小島みこ / 宮西ひかる / もなみ鈴 / 藤沢麗央 / ありさ / みな
_PERSON_NAME_RE = re.compile(
    r"^(?:"
    r"[\u4e00-\u9fff]{1,3}[\u3040-\u309f]{1,5}"  # 小島みこ 宮西ひかる
    r"|[\u3040-\u309f]{1,4}[\u4e00-\u9fff]{1,2}"  # もなみ鈴
    r"|[\u3040-\u309f]{2,6}"  # ありさ みな
    r"|[\u4e00-\u9fff]{2,4}"  # 藤沢麗央
    r"|[A-Za-z][A-Za-z .·・\-]{1,24}"  # Marika Sonoda / Hitomi
    r"|[\u30a0-\u30ff]{2,8}"  # ニーナ (kata nicknames, short)
    r")$"
)

_CODE_PREFIX = re.compile(
    r"^(?:[A-Z]{2,10}|[0-9]{2,5}[A-Z]{2,10})-?\d+[A-Z]?\s*[:：\-]?\s*",
    re.I,
)
_NAME_TOKEN = re.compile(
    r"^[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{2,12}$"
)
# "小島みこ" / "宮西ひかる" / "もなみ鈴" / "藤沢麗央" / "ありさ"
_NAMEISH = re.compile(
    r"^["
    r"\u3040-\u309f"  # hira
    r"\u30a0-\u30ff"  # kata
    r"\u4e00-\u9fff"  # kanji
    r"]{2,12}$"
)
_TRAIL_SEP = re.compile(r"[、,／/|｜]\s*")
_WS_SPLIT = re.compile(r"[\s　・]+")
# Chinese name tails after em/en dash (DeepSeek habit), e.g. ——小岛美子、森彩美 / ——纺 19岁
# Do NOT match plain spaces alone — that would wipe whole Chinese titles.
_ZH_NAME_TAIL = re.compile(
    r"[—–\-]{1,3}\s*"
    r"(?:[\u4e00-\u9fff]{1,8}(?:\s*\d{1,2}\s*岁?)?"
    r"(?:[、，,/／\s]+[\u4e00-\u9fff]{1,8}(?:\s*\d{1,2}\s*岁?)?){0,5})\s*$"
)
# Trailing "show all" garbage from some sources
_SHOW_ALL_TAIL = re.compile(r"\s*▼\s*すべて表示する\s*$")


def _strip_name_alias(name: str) -> str:
    """森沢かな（飯岡かなこ） -> 森沢かな；Hitomi（田中瞳） -> Hitomi."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    s = re.sub(r"[（(][^）)]*[）)]", "", s).strip()
    return s


# 改名等同人：旧拼写 → 现行日文名（屏蔽/展示用）
_ACTRESS_RENAME = {
    "河北彩花": "河北彩伽",
}


def preferred_actress_spelling(name: str) -> str:
    """Map rename aliases to current JP spelling; keep other JP names as-is."""
    s = _strip_name_alias(name)
    if not s:
        return ""
    return _ACTRESS_RENAME.get(s, s)


def actress_alias_group(name: str) -> list:
    """All spellings for the same person (for blocklist write/match)."""
    pref = preferred_actress_spelling(name)
    if not pref:
        return []
    groups = (
        ("河北彩伽", "河北彩花"),
    )
    for g in groups:
        if pref in g or name in g:
            return list(g)
    return [pref]


def is_valid_actress_name(name: str) -> bool:
    """Reject placeholders and title/plot fragments mistaken for actresses."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    if not s:
        return False
    low = s.lower()
    if low in _BAD_EXACT or s in _BAD_EXACT:
        return False
    if re.fullmatch(r"[-—–_.=*]+", s):
        return False
    if "▼" in s or "すべて表示" in s:
        return False
    if s in _NOT_NAME:
        return False
    if re.fullmatch(r"[A-Z0-9\-]{2,}", s, re.I):
        return False
    if re.fullmatch(r"\d+時間?", s):
        return False
    if _PLOT_KW_RE.search(s):
        return False

    base = _strip_name_alias(s)
    if not base:
        return False
    if base in _NOT_NAME or _PLOT_KW_RE.search(base):
        return False
    # Too long for a person name (plot clause)
    if len(base) > 12 and not re.fullmatch(r"[A-Za-z][A-Za-z .·・\-]{1,28}", base):
        return False
    # Grammar particles mid-phrase: 快楽に屈 / 体質によっ
    if re.search(r"[\u4e00-\u9fff]に[\u4e00-\u9fffか-ん]", base):
        return False
    if re.search(r"[でにをはがへ]", base) and len(base) >= 5:
        # Allow rare names? Japanese given names rarely embed で/を/は
        if not re.fullmatch(r"[\u3040-\u309f]{2,6}", base):
            return False
    # Incomplete / truncated title tails
    if base.endswith(("ず", "っ", "フ", "によっ", "によ", "てっ", "して")):
        return False
    # Multi-cast junk joined with ＆
    if base.count("＆") >= 2 or base.count("&") >= 2:
        return False
    return True


def clean_actresses(values: Iterable[str] | None) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values or []:
        name = re.sub(r"\s+", " ", str(value or "")).strip()
        if not is_valid_actress_name(name):
            continue
        # Prefer primary name without alias clutter for display consistency
        primary = _strip_name_alias(name) or name
        # Keep original if alias form is standard JP listing and primary still valid
        display = name if ("（" in name or "(" in name) and is_valid_actress_name(primary) else primary
        if not is_valid_actress_name(display):
            continue
        display = preferred_actress_spelling(display)
        if not display or display in seen:
            continue
        seen.add(display)
        out.append(display)
    return out


def _looks_like_person_name(tok: str) -> bool:
    """Stricter check for title-tail extraction only."""
    if not tok or not is_valid_actress_name(tok):
        return False
    base = _strip_name_alias(tok)
    if not base:
        return False
    if not _PERSON_NAME_RE.match(base):
        return False
    if base.endswith(("編", "版", "集", "部", "課", "系", "祭", "戦")):
        return False
    # Pure katakana 3+ often product words; allow short nicknames only
    if re.fullmatch(r"[\u30a0-\u30ff]{5,}", base):
        return False
    return True


def strip_code_prefix(title: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    return _CODE_PREFIX.sub("", t).strip()


_LEAD_PUNCT = re.compile(
    r"^([』」》!！?？。．.、,：:\u3000\s]+)(.*)$"
)


def _peel_leading_punct(tok: str) -> Tuple[str, str]:
    """Split leading quotes/punct from a token stuck like 』もなみ鈴."""
    m = _LEAD_PUNCT.match(tok or "")
    if m and m.group(2):
        return m.group(1), m.group(2)
    return "", tok


def extract_trailing_actresses(title: str) -> Tuple[str, List[str]]:
    """Split JP title into (body, trailing_names).

    Conservative: only accept 1–5 trailing tokens that all look like person names.
    """
    raw = re.sub(r"\s+", " ", str(title or "")).strip()
    if not raw:
        return "", []

    body = strip_code_prefix(raw)
    if not body:
        return raw, []

    # Prefer segment after last Japanese enumeration comma
    for sep in ("、", ","):
        if sep in body:
            left, right = body.rsplit(sep, 1)
            right = right.strip()
            names = [t for t in _WS_SPLIT.split(right) if t]
            if names and all(_looks_like_person_name(n) for n in names) and 1 <= len(names) <= 5:
                return left.rstrip(" 、,。．.!！?？』」》"), names

    # Insert space when a name is glued after closing quote / punct
    body_spaced = re.sub(
        r"([』」》!！?？。．.]+)([\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{2,})",
        r"\1 \2",
        body,
    )
    tokens = _WS_SPLIT.split(body_spaced)
    if len(tokens) < 2:
        return body, []

    # peel residual punct-only tokens
    tokens = [t for t in tokens if t and not re.fullmatch(r"[』」》!！?？。．.、,：:]+", t)]

    # take longest trailing run of name-like tokens (max 5)
    i = len(tokens)
    while i > 0 and _looks_like_person_name(tokens[i - 1]) and (len(tokens) - i + 1) <= 5:
        i -= 1
    names = tokens[i:]
    if not names:
        return body, []
    if i == 0:
        return body, []
    body_tokens = tokens[:i]
    if len(names) > 3 and len(body_tokens) < 3:
        return body, []
    new_body = " ".join(body_tokens).rstrip(" 、,。．.!！?？』」》")
    return new_body, names


# --- blocked actress snap (same idea as genre_zh.snap_to_blocked) ---
_blocked_list: list = []
_blocked_fold: dict = {}  # fold(name) -> exact blocked spelling
_blocked_mtime = None
_blocked_path = ""
_blocked_loaded = False

# subset of 繁简 used when folding names (aligned with Go foldActressKey)
_FOLD_CHARS = str.maketrans({
    "優": "优", "愛": "爱", "澤": "泽", "辺": "边", "黒": "黑", "桜": "樱",
    "実": "实", "広": "广", "滝": "泷", "児": "儿", "亜": "亚", "斎": "斋",
    "満": "满", "浜": "滨", "戸": "户", "瀬": "濑", "亀": "龟", "竜": "龙",
    "嶋": "岛", "島": "岛", "斉": "齐", "緒": "绪", "絵": "绘", "華": "华",
    "葉": "叶", "薫": "薰", "蘭": "兰", "鷹": "鹰",
})


def fold_actress_key(name: str) -> str:
    s = re.sub(r"\s+", "", str(name or "").strip())
    s = s.strip(" \t　（）()【】[]「」『』・·.,。．!！?？:：;；-_—–")
    s = s.replace("・", "").replace("·", "").replace(".", "").replace("．", "")
    s = s.translate(_FOLD_CHARS)
    return s.lower()


def _default_blocked_actresses_path() -> str:
    env = (os.environ.get("BLOCKED_ACTRESSES_FILE") or "").strip()
    if env:
        return env
    db = (os.environ.get("DB_PATH") or "").strip()
    if db:
        base = db if os.path.isdir(db) else (os.path.dirname(db) or "")
        if base:
            return os.path.join(base, "blocked_actresses.txt")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "db", "blocked_actresses.txt")


def load_blocked_actresses(force: bool = False) -> list:
    """Load exact blocked actress spellings (same file as Go filter)."""
    global _blocked_list, _blocked_fold, _blocked_mtime, _blocked_path, _blocked_loaded
    path = _default_blocked_actresses_path()
    mtime = None
    try:
        if path and os.path.isfile(path):
            mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if (
        not force
        and _blocked_loaded
        and _blocked_mtime == mtime
        and _blocked_path == path
    ):
        return _blocked_list
    _blocked_list = []
    _blocked_fold = {}
    _blocked_path = path
    try:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if not name or name.startswith("#"):
                        continue
                    _blocked_list.append(name)
                    key = fold_actress_key(name)
                    if key and key not in _blocked_fold:
                        _blocked_fold[key] = name
        # env extras (queue_api style)
        for name in (os.environ.get("BLOCKED_ACTRESSES") or "").split(","):
            name = name.strip()
            if not name:
                continue
            if name not in _blocked_list:
                _blocked_list.append(name)
            key = fold_actress_key(name)
            if key and key not in _blocked_fold:
                _blocked_fold[key] = name
    except Exception as e:
        print(f"[actresses] load blocked failed: {e}")
    _blocked_mtime = mtime
    _blocked_loaded = True
    return _blocked_list


def is_blocked_actress(name: str) -> bool:
    raw = (name or "").strip()
    if not raw:
        return False
    load_blocked_actresses()
    for cand in actress_alias_group(raw) or [raw]:
        if cand in _blocked_fold.values() or cand in _blocked_list:
            return True
        if fold_actress_key(cand) in _blocked_fold:
            return True
    return False


def snap_to_blocked_actress(name: str) -> str:
    """If name matches a blocked actress (folded), return exact blocked spelling."""
    raw = (name or "").strip()
    if not raw:
        return raw
    load_blocked_actresses()
    if raw in _blocked_list:
        return raw
    key = fold_actress_key(raw)
    if key in _blocked_fold:
        return _blocked_fold[key]
    return raw


def ensure_actresses(item: dict) -> bool:
    """Clean actresses; if empty, try title tail; snap to blocked spelling."""
    before = list(item.get("actresses") or [])
    cleaned = clean_actresses(before)
    if not cleaned:
        _, names = extract_trailing_actresses(item.get("title") or "")
        cleaned = clean_actresses(names)
    # Align spelling with blocked_actresses.txt so Go exact/fold stay consistent
    snapped = [snap_to_blocked_actress(n) for n in cleaned]
    # de-dupe after snap
    out: List[str] = []
    seen = set()
    for n in snapped:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    if out != before:
        item["actresses"] = out
        return True
    item["actresses"] = out
    return out != before


def title_for_translate(title: str, actresses: Sequence[str] | None = None) -> Tuple[str, List[str]]:
    """Body only for translator; actress names stay in actresses field (not in titleZh)."""
    acts = clean_actresses(actresses)
    body, tail = extract_trailing_actresses(title)
    if not acts and tail:
        acts = tail
    work = body or strip_code_prefix(title)
    if acts:
        for name in reversed(acts):
            work = re.sub(rf"(?:[\s　、,・]*{re.escape(name)})+\s*$", "", work)
        work = work.rstrip(" 、,。．.!！?？』」》—–-")
    return work.strip() or strip_code_prefix(title), acts


def finalize_title_zh(item: dict) -> bool:
    """Strip actress names and Chinese em-dash name tails from titleZh.

    titleZh = Chinese plot/title only; JP names live only in actresses[].
    """
    zh = str(item.get("titleZh") or "").strip()
    if not zh:
        return False
    original = zh
    acts = clean_actresses(item.get("actresses") or [])
    act_set = set(acts)

    stripped = _SHOW_ALL_TAIL.sub("", zh).strip()
    # Drop Chinese name tails after em dash (——纺 19岁 / ——小岛美子、森彩美)
    stripped = _ZH_NAME_TAIL.sub("", stripped).rstrip(" ：:—–-")

    # Drop known actress names right after optional 番号: (best-of: "春原未来 本能之吻")
    for n in sorted(acts, key=len, reverse=True):
        stripped = re.sub(
            rf"^((?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\s*[:：]?\s*)?)"
            rf"{re.escape(n)}[\s　:：·・]+",
            r"\1",
            stripped,
        )

    # Drop known names from the end (repeat until stable; multi-name lists)
    changed = True
    while changed:
        changed = False
        for n in sorted(acts, key=len, reverse=True):
            new = re.sub(
                rf"(?:[\s　、,·・]*{re.escape(n)})+(?:\s*[（(][^）)]*[）)])?\s*$",
                "",
                stripped,
            )
            new = new.rstrip(" ：:—–-、,")
            if new != stripped and new:
                stripped = new
                changed = True

    # Drop trailing name-like tokens (JP/CJK) that match actresses or look like names
    while True:
        m = re.search(
            r"[\s　、,·・]+([\u3040-\u30ff\u4e00-\u9fffA-Za-z·]{2,16})$",
            stripped,
        )
        if not m:
            break
        tok = m.group(1)
        if tok in act_set or _looks_like_person_name(tok):
            stripped = stripped[: m.start()].rstrip(" ：:—–-、,")
            continue
        break

    # One more em-dash pass after name peels
    stripped = _ZH_NAME_TAIL.sub("", stripped).rstrip(" ：:—–-")

    if stripped != original and stripped:
        item["titleZh"] = stripped
        return True
    return False


def translate_system_prompt() -> str:
    return (
        "你是日语翻译助手。将日文成人影片标题翻译为简洁的中文。"
        "规则：1) 只输出中文标题正文，不要解释；"
        "2) 不要翻译或保留女优姓名（输入已去掉人名）；"
        "3) 番号可保留在开头。"
    )
