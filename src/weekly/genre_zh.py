"""MGS 日文ジャンル → 与库内 JavBus 标签对齐的名称。

目标：屏蔽/收藏沿用 weekly 里已有字符串，不另起一套简体新标签。
- JavBus 已有的繁体/中文标签：原样通过（可做别名归一到主名）
- MGS 日文：映射到同义的 JavBus 名
- NTR 固定为 NTR（用户要求不变）
"""
from __future__ import annotations

import json
import os
import re
from typing import Iterable, List

# 值 = weekly.json 里已出现过的 JavBus 标签名（优先高频）
_GENRE_MAP = {
    # ----- quality / exclusivity / format -----
    "独占配信": "DMM獨家",
    "独占": "DMM獨家",
    "DMM独家": "DMM獨家",
    "DMM獨家": "DMM獨家",
    "dmm独家": "DMM獨家",
    "dmm獨家": "DMM獨家",
    "配信専用": "配信専用",
    "配信专用": "配信専用",
    "配信限定": "配信専用",
    "ハイビジョン": "高畫質",
    "フルハイビジョン": "高畫質",
    "フルハイビジョン(fhd)": "高畫質",
    "フルハイビジョン(FHD)": "高畫質",
    "高画質": "高畫質",
    "高畫質": "高畫質",
    "高清": "高畫質",
    "hd": "高畫質",
    "fhd": "高畫質",
    "4k": "4K",
    "4K": "4K",
    "Hi-Def": "高畫質",
    "Exclusive Distribution": "DMM獨家",
    "単体作品": "單體作品",
    "Featured Actress": "單體作品",
    "单体作品": "單體作品",
    "單體作品": "單體作品",
    "単体": "單體作品",
    "企画": "企畫",
    "企划": "企畫",
    "企畫": "企畫",
    "VR専用": "VR専用",
    "vr": "VR専用",
    "ハイクオリティVR": "ハイクオリティVR",
    "8KVR": "8KVR",
    # ----- people -----
    "素人": "業餘",
    "业余": "業餘",
    "業餘": "業餘",
    "人妻": "已婚婦女",
    "人妻・主婦": "已婚婦女",
    "若妻": "已婚婦女",
    "既婚婦女": "已婚婦女",
    "已婚婦女": "已婚婦女",
    "已婚妇女": "已婚婦女",
    "人妻・熟女": "已婚婦女",
    "熟女": "成熟的女人",
    "成熟的女人": "成熟的女人",
    "美少女": "美少女",
    "女子校生": "高中女生",
    "高中女生": "高中女生",
    "女子大生": "女大學生",
    "女大学生": "女大學生",
    "女大學生": "女大學生",
    "お姉さん": "姐姐",
    "姐姐": "姐姐",
    "ギャル": "女生",
    "痴女": "蕩婦",
    "荡妇": "蕩婦",
    "蕩婦": "蕩婦",
    "花癡": "花癡",
    "淫乱・ハード系": "花癡",
    "淫乱": "花癡",
    "M女": "M女",
    "S女": "SM",
    "M男": "M男",
    "女優": "女優",
    "女优": "女優",
    "母亲": "母親",
    "母親": "母親",
    "義母": "婆婆",
    "婆婆": "婆婆",
    "姉・妹": "姐妹",
    "姉": "姐姐",
    "妹": "姐妹",
    "姐妹": "姐妹",
    "女上司": "OL",
    "女教師": "女教師",
    "女教师": "女教師",
    "OL": "OL",
    "ナース・女医": "护士",
    "看護婦": "护士",
    "护士": "护士",
    "メイド": "女傭",
    "女佣": "女傭",
    "女傭": "女傭",
    "コスプレ": "角色扮演",
    "角色扮演": "角色扮演",
    "制服": "制服",
    "水着": "學校泳裝",
    "学校泳装": "學校泳裝",
    "學校泳裝": "學校泳裝",
    "ランジェリー": "內衣",
    "内衣": "內衣",
    "內衣": "內衣",
    "变性者": "變性者",
    "変性者": "變性者",
    "變性者": "變性者",
    "女装人妖": "女裝人妖",
    "女裝人妖": "女裝人妖",
    "偶像艺人": "偶像藝人",
    "偶像藝人": "偶像藝人",
    "妓女": "妓女",
    "触手": "觸手",
    "觸手": "觸手",
    "女战士": "女戰士",
    "女戰士": "女戰士",
    # ----- body -----
    "巨乳": "巨乳",
    "Big Tits": "巨乳",
    "爆乳": "超乳",
    "超乳": "超乳",
    "美乳": "巨乳",
    "貧乳・微乳": "貧乳",
    "貧乳": "貧乳",
    "贫乳": "貧乳",
    "乳房": "乳房",
    "美尻": "美尻",
    "巨尻": "巨尻",
    "デカ尻": "巨尻",
    "屁股": "屁股",
    "スレンダー": "苗條",
    "Slender": "苗條",
    "苗条": "苗條",
    "苗條": "苗條",
    "ぽっちゃり": "胖女人",
    "胖女人": "胖女人",
    "長身": "高",
    "高": "高",
    "パイパン": "無毛",
    "无毛": "無毛",
    "無毛": "無毛",
    "白虎": "無毛",
    "美脚": "美脚",
    "美腿": "美脚",
    "黒髪": "清楚",
    "メガネ": "眼鏡",
    "眼鏡": "眼鏡",
    "眼镜": "眼鏡",
    "嬌小的": "嬌小的",
    "娇小": "嬌小的",
    "タトゥー": "其他戀物癖",
    # ----- acts -----
    "中出し": "中出",
    "中出": "中出",
    "內射": "中出",
    "内射": "中出",
    "顔射": "顏射",
    "颜射": "顏射",
    "顏射": "顏射",
    "ぶっかけ": "顏射",
    "口内射精": "口交",
    "ごっくん": "吞精",
    "吞精": "吞精",
    "潮吹き": "潮吹",
    "潮吹": "潮吹",
    "放尿": "放尿",
    "アナル": "肛交",
    "アナルセックス": "肛交",
    "肛交": "肛交",
    "レズ": "女同性戀",
    "レズビアン": "女同性戀",
    "女同": "女同性戀",
    "女同性戀": "女同性戀",
    "女同接吻": "女同接吻",
    "乱交": "濫交",
    "滥交": "濫交",
    "濫交": "濫交",
    "3p・4p": "多P",
    "3P・4P": "多P",
    "3P": "多P",
    "4P": "多P",
    "複数プレイ": "多P",
    "多P": "多P",
    "多人": "多P",
    "ハメ撮り": "第一人稱攝影",
    "自拍": "第一人稱攝影",
    "第一人称摄影": "第一人稱攝影",
    "第一人稱攝影": "第一人稱攝影",
    "盗撮": "偷窥",
    "偷拍": "偷窥",
    "偷窥": "偷窥",
    # NTR fixed
    "寝取り・寝取られ": "NTR",
    "寝取り・寝取られ・NTR": "NTR",
    "寝取り": "NTR",
    "寝取られ": "NTR",
    "ntr": "NTR",
    "NTR": "NTR",
    "通姦": "通姦",
    "通奸": "通姦",
    "不倫": "出軌",
    "浮気": "出軌",
    "出轨": "出軌",
    "出軌": "出軌",
    "近親相姦": "亂倫",
    "乱伦": "亂倫",
    "亂倫": "亂倫",
    "部下・同僚": "各種職業",
    "職業色々": "各種職業",
    "各种职业": "各種職業",
    "各種職業": "各種職業",
    "痴漢": "猥褻穿著",
    "拘束": "拘束",
    "緊縛": "紧缚",
    "紧缚": "紧缚",
    "拘束プレイ": "紧缚",
    "調教": "SM",
    "SM": "SM",
    "イラマチオ": "深喉",
    "深喉": "深喉",
    "フェラ": "口交",
    "口交": "口交",
    "手コキ": "打手槍",
    "打手枪": "打手槍",
    "打手槍": "打手槍",
    "手交": "打手槍",
    "足コキ": "足交",
    "足交": "足交",
    "騎乗位": "女上位",
    "女上位": "女上位",
    "骑乘位": "女上位",
    "バック": "後入",
    "后入": "後入",
    "後入": "後入",
    "デカチン・巨根": "巨根",
    "巨根": "巨根",
    "処女": "處女",
    "初撮り": "首次亮相",
    "初拍": "首次亮相",
    "首次亮相": "首次亮相",
    "デビュー作品": "首次亮相",
    "Debut": "首次亮相",
    "ドキュメント": "纪录片",
    "ドキュメンタリー": "纪录片",
    "ドラマ": "戲劇",
    "纪录片": "纪录片",
    "主観": "主觀視角",
    "主观": "主觀視角",
    "主觀視角": "主觀視角",
    "ローション・オイル": "乳液",
    "ローション": "乳液",
    "Lotion": "乳液",
    "润滑油": "乳液",
    "乳液": "乳液",
    "オモチャ": "玩具",
    "おもちゃ": "玩具",
    "道具": "玩具",
    "玩具": "玩具",
    "バイブ": "按摩棒",
    "電マ": "女優按摩棒",
    "按摩棒": "按摩棒",
    "女優按摩棒": "女優按摩棒",
    "野外・露出": "野外・露出",
    "露出": "野外・露出",
    "温泉": "温泉",
    "旅行": "デート",
    "デート": "デート",
    "约会": "デート",
    "ナンパ": "獵豔",
    "搭讪": "獵豔",
    "猎艳": "獵豔",
    "獵豔": "獵豔",
    "マッサージ": "按摩",
    "按摩": "按摩",
    "エステ": "美容院",
    "美容院": "美容院",
    "性教育": "介紹影片",
    "キス・接吻": "接吻",
    "キス": "接吻",
    "接吻": "接吻",
    "クンニ": "舔陰",
    "舔阴": "舔陰",
    "舔陰": "舔陰",
    "乳首責め": "戀乳癖",
    "乳首": "戀乳癖",
    "恋乳": "戀乳癖",
    "戀乳癖": "戀乳癖",
    "羞恥": "羞恥",
    "羞耻": "羞恥",
    "辱め": "凌辱",
    "凌辱": "凌辱",
    "レイプ": "凌辱",
    "輪姦": "濫交",
    "監禁": "拘束",
    "ドラッグ": "藥物",
    "药物": "藥物",
    "藥物": "藥物",
    "泥酔": "粗暴",
    "アクメ・オーガズム": "高潮",
    "アクメ": "高潮",
    "オーガズム": "高潮",
    "高潮": "高潮",
    "サンプル動画": "樣片",
    "サンプル": "樣片",
    "样片": "樣片",
    "樣片": "樣片",
    "预览": "樣片",
    "淫語": "淫語",
    "自慰": "自慰",
    "乳交": "乳交",
    "パイズリ": "乳交",
    "戏剧": "戲劇",
    "戲劇": "戲劇",
    "4小时以上作品": "4小時以上作品",
    "4小時以上作品": "4小時以上作品",
    "4時間以上作品": "4小時以上作品",
    "カップル": "情侶",
    "情侣": "情侶",
    "情侶": "情侶",
    "连裤袜": "連褲襪",
    "連褲襪": "連褲襪",
    "恋腿": "戀腿癖",
    "戀腿癖": "戀腿癖",
    "局部特写": "局部特寫",
    "局部特寫": "局部特寫",
    "恶作剧": "惡作劇",
    "惡作劇": "惡作劇",
    "其他恋物癖": "其他戀物癖",
    "其他戀物癖": "其他戀物癖",
    "その他フェチ": "其他戀物癖",
    "妄想族": "妄想族",
    "合集": "合集",
    "介绍影片": "介紹影片",
    "介紹影片": "介紹影片",
    "迷你系列": "迷你係列",
    "迷你係列": "迷你係列",
    "エマニエル": "情色",
    "Emaniel": "情色",
    "ハーレム": "後宮",
    "后宫": "後宮",
    "後宮": "後宮",
    "汗だく": "大汗",
    "大汗": "大汗",
    "Athlete": "運動員",
    "オナサポ": "自慰輔助",
    "自慰辅助": "自慰輔助",
    "自慰輔助": "自慰輔助",
    "ハイクオリティVR": "高品質VR",
    "高品质VR": "高品質VR",
    "高品質VR": "高品質VR",
    "特典付き・セット商品": "特典套組",
    "特典套组": "特典套組",
    "特典套組": "特典套組",
    "アクション・格闘": "動作格鬥",
    "アクション": "動作",
    "动作": "動作",
    "動作": "動作",
    "動作格鬥": "動作格鬥",
    "アナルセックス（男の娘）": "肛交",
    "尻フェチ": "美尻",
    "ビッチ": "蕩婦",
    "女優按摩棒": "女優按摩棒",
    "女优按摩棒": "女優按摩棒",
    "颜面骑乘": "顏面騎乘",
    "顏面騎乘": "顏面騎乘",
    "清楚": "清楚",
    "中文字幕": "中文字幕",
    "有码高清": "高畫質",
    "无码高清": "高畫質",
    "女生": "女生",
    "处女": "處女",
    "處女": "處女",
    "处男": "處男",
    "處男": "處男",
    "オナニー": "自慰",
    "デート": "約會",
    "约会": "約會",
    "約會": "約會",
    "パンスト・タイツ": "連褲襪",
    "パンスト": "連褲襪",
    "タイツ": "連褲襪",
    "盗撮・のぞき": "偷窥",
    "のぞき": "偷窥",
    "ミニ系": "嬌小的",
    "脚フェチ": "戀腿癖",
    "エステ・マッサージ": "按摩",
    "マッサージ・リフレ": "按摩",
    "孕ませ": "中出",
    "巨乳フェチ": "巨乳",
    "ヘルス・ソープ": "風俗店",
    "風俗店": "風俗店",
    "お風呂": "洗澡",
    "洗澡": "洗澡",
    "縛り・緊縛": "紧缚",
    "縛り": "紧缚",
    "部活・マネージャー": "社團",
    "社團": "社團",
    "ディルド": "假陽具",
    "假阳具": "假陽具",
    "假陽具": "假陽具",
    "デジモ": "數位馬賽克",
    "数位马赛克": "數位馬賽克",
    "數位馬賽克": "數位馬賽克",
    "ニューハーフ": "變性者",
    "パンチラ": "走光",
    "走光": "走光",
    "アスリート": "運動員",
    "运动员": "運動員",
    "運動員": "運動員",
    "お母さん": "母親",
    "ホテル": "酒店",
    "酒店": "酒店",
    "ビジネススーツ": "OL",
    "ベスト・総集編": "合集",
    "総集編": "合集",
    "叔母さん": "叔母",
    "叔母": "叔母",
    "セーラー服": "水手服",
    "水手服": "水手服",
    "イメージビデオ": "形象影片",
    "形象影片": "形象影片",
    "放尿・お漏らし": "放尿",
    "お漏らし": "放尿",
    "病院・クリニック": "醫院",
    "医院": "醫院",
    "醫院": "醫院",
    "飲み会・合コン": "聯誼",
    "联谊": "聯誼",
    "聯誼": "聯誼",
    "ノーブラ": "無胸罩",
    "无胸罩": "無胸罩",
    "無胸罩": "無胸罩",
    "セクシー": "性感",
    "性感": "性感",
    "競泳・スクール水着": "學校泳裝",
    "女装・男の娘": "女裝人妖",
    "着エロ": "情趣衣著",
    "情趣衣着": "情趣衣著",
    "情趣衣著": "情趣衣著",
    "イタズラ": "惡作劇",
    "スパンキング": "打屁股",
    "打屁股": "打屁股",
    "看護婦・ナース": "护士",
    "ナース": "护士",
    "原作コラボ": "原作聯動",
    "原作联动": "原作聯動",
    "原作聯動": "原作聯動",
    "Gカップ": "G罩杯",
    "Fカップ": "F罩杯",
    "Hカップ": "H罩杯",
    "Iカップ": "I罩杯",
    "Eカップ": "E罩杯",
    "Dカップ": "D罩杯",
    "Cカップ": "C罩杯",
    "局部アップ": "局部特寫",
    "アイドル・芸能人": "偶像藝人",
    "アイドル": "偶像藝人",
    "お爺ちゃん": "爺爺",
    "爷爷": "爺爺",
    "爺爺": "爺爺",
    "体操着・ブルマ": "體操服",
    "体操服": "體操服",
    "體操服": "體操服",
    "鼻フック": "鼻鉤",
    "鼻钩": "鼻鉤",
    "鼻鉤": "鼻鉤",
    "Blu-ray（ブルーレイ）": "藍光",
    "ブルーレイ": "藍光",
    "蓝光": "藍光",
    "藍光": "藍光",
    "レオタード": "連體緊身衣",
    "胸チラ": "走光",
    "女優ベスト・総集編": "女優合集",
    "女优合集": "女優合集",
    "女優合集": "女優合集",
    # ----- long-tail leftover kana (NAS audit) -----
    "ゲロ": "呕吐",
    "呕吐": "呕吐",
    "嘔吐": "呕吐",
    "日焼け": "晒黑",
    "晒黑": "晒黑",
    "めがね": "眼鏡",
    "ファン感謝・訪問": "粉丝感谢",
    "粉丝感谢": "粉丝感谢",
    "ボンテージ": "束缚装",
    "束缚装": "束缚装",
    "キャバ嬢・風俗嬢": "风俗娘",
    "风俗娘": "风俗娘",
    "風俗嬢": "风俗娘",
    "キャバ嬢": "风俗娘",
    "学園もの": "校园",
    "校园": "校园",
    "学園": "校园",
    "淫語モノ": "淫語",
    "セレブ": "名媛",
    "名媛": "名媛",
    "レズキス": "女同接吻",
    "スポーツ": "运动",
    "运动": "运动",
    "運動": "运动",
    "MGSだけのおまけ映像付き": "MGS特典映像",
    "MGS特典映像": "MGS特典映像",
    "ファンタジー": "奇幻",
    "奇幻": "奇幻",
    "シックスナイン": "69",
    "ダンス": "舞蹈",
    "舞蹈": "舞蹈",
    "クスコ": "扩阴器",
    "扩阴器": "扩阴器",
    "インストラクター": "教练",
    "教练": "教练",
    "ショタ": "正太",
    "正太": "正太",
    "ミニスカ": "超短裙",
    "超短裙": "超短裙",
    "バニーガール": "兔女郎",
    "兔女郎": "兔女郎",
    "即ハメ": "即插",
    "即插": "即插",
    "男の潮吹き": "男潮",
    "男潮": "男潮",
    "レースクィーン": "赛车女郎",
    "レースクイーン": "赛车女郎",
    "赛车女郎": "赛车女郎",
    "BL（ボーイズラブ）": "BL",
    "ボーイズラブ": "BL",
    "BL": "BL",
    "ボディコン": "紧身衣",
    "紧身衣": "紧身衣",
    "アジア女優": "亚洲女优",
    "亚洲女优": "亚洲女优",
    "幼なじみ": "青梅竹马",
    "青梅竹马": "青梅竹马",
    "ローター": "跳蛋",
    "跳蛋": "跳蛋",
    "手マン": "手指",
    "手指": "手指",
    "ラブコメ": "爱情喜剧",
    "爱情喜剧": "爱情喜剧",
    "ノーパン": "真空",
    "真空": "真空",
    "お婆ちゃん": "老奶奶",
    "老奶奶": "老奶奶",
    "オタク": "宅",
    "宅": "宅",
    "パンストモノ": "連褲襪",
    "金髪・ブロンド": "金发",
    "ブロンド": "金发",
    "金发": "金发",
    "金髪": "金发",
    "ママ友": "妈妈友",
    "妈妈友": "妈妈友",
    "チアガール": "啦啦队",
    "啦啦队": "啦啦队",
    "スワッピング・夫婦交換": "换妻",
    "スワッピング": "换妻",
    "夫婦交換": "换妻",
    "换妻": "换妻",
    "ヨガ": "瑜伽",
    "瑜伽": "瑜伽",
}

def _default_memory_path() -> str:
    env = (os.environ.get("GENRE_ZH_MEMORY") or "").strip()
    if env:
        return env
    db = (os.environ.get("DB_PATH") or "").strip()
    if db:
        # DB_PATH may be a file (/db/downloaded.db) or a directory (/db)
        base = db if os.path.isdir(db) else (os.path.dirname(db) or "")
        if base and (os.path.isdir(base) or base.startswith("/db")):
            return os.path.join(base, "genre_zh_memory.json")
    # local dev: project ./db/
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "db", "genre_zh_memory.json")


# Persistent learned map (NAS /db). Only grows on new keys — not re-AI each scrape.
_MEMORY_PATH = _default_memory_path()

_memory: dict = {}
_memory_loaded = False
_memory_dirty = False

# User blocked genres (exact spellings from blocked_genres.txt) — canonical for filter match
_blocked_list: list = []
_blocked_fold: dict = {}  # fold(label) -> exact blocked string
_blocked_mtime = None
_blocked_path = ""
_blocked_loaded = False

# Minimal 繁简 folding so 触手≈觸手, 变≈變, without external deps
_FOLD_CHARS = str.maketrans({
    "觸": "触", "緊": "紧", "縛": "缚", "變": "变", "専": "专", "專": "专",
    "戰": "战", "紹": "绍", "裡": "里", "內": "内", "術": "术", "係": "系",
    "畫": "画", "質": "质", "體": "体", "獨": "独", "業": "业", "餘": "余",
    "婦": "妇", "與": "与", "無": "无", "髮": "发", "後": "后", "國": "国",
    "藝": "艺", "優": "优", "兒": "儿", "媽": "妈", "爺": "爷", "藍": "蓝",
    "鉤": "钩", "陽": "阳", "數": "数", "碼": "码", "聯": "联", "動": "动",
    "處": "处", "導": "导", "護": "护", "顏": "颜", "慾": "欲", "戀": "恋",
    "癡": "痴", "臟": "脏", "腸": "肠", "槍": "枪", "牆": "墙",
})


def _norm_key(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"\s+", "", t)
    return t


def _fold_for_block(text: str) -> str:
    """Normalize for comparing against blocked_genres (not for display)."""
    t = _norm_key(text)
    t = t.replace("・", "").replace("·", "").replace(".", "").replace("-", "")
    t = t.translate(_FOLD_CHARS)
    return t.lower()


def _looks_japanese(text: str) -> bool:
    """True if string still has hiragana/katakana (needs mapping)."""
    return bool(re.search(r"[\u3040-\u30ff]", text or ""))


def _default_blocked_path() -> str:
    env = (os.environ.get("BLOCKED_GENRES_FILE") or "").strip()
    if env:
        return env
    db = (os.environ.get("DB_PATH") or "").strip()
    if db:
        base = db if os.path.isdir(db) else (os.path.dirname(db) or "")
        if base:
            return os.path.join(base, "blocked_genres.txt")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "db", "blocked_genres.txt")


def load_blocked_genres(force: bool = False) -> list:
    """Load exact blocked genre spellings (same file as Go filter)."""
    global _blocked_list, _blocked_fold, _blocked_mtime, _blocked_path, _blocked_loaded
    path = _default_blocked_path()
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
                    _blocked_fold[_fold_for_block(name)] = name
    except Exception as e:
        print(f"[genre_zh] load blocked genres failed: {e}")
    _blocked_mtime = mtime
    _blocked_loaded = True
    return _blocked_list


def snap_to_blocked(label: str) -> str:
    """If label matches a blocked genre (folded), return the exact blocked spelling."""
    raw = (label or "").strip()
    if not raw:
        return raw
    load_blocked_genres()
    if raw in _blocked_fold.values() or raw in _blocked_list:
        # prefer list order spelling
        for b in _blocked_list:
            if b == raw:
                return b
        return raw
    key = _fold_for_block(raw)
    if key in _blocked_fold:
        return _blocked_fold[key]
    return raw


def load_memory(force: bool = False) -> dict:
    """Load genre memory file once (or force reload)."""
    global _memory, _memory_loaded
    if _memory_loaded and not force:
        return _memory
    _memory = {}
    path = _MEMORY_PATH
    try:
        if path and os.path.isfile(path) and os.path.getsize(path) > 2:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _memory = {str(k): str(v) for k, v in data.items() if k and v}
    except Exception as e:
        print(f"[genre_zh] load memory failed: {e}")
        _memory = {}
    _memory_loaded = True
    return _memory


def save_memory() -> bool:
    """Persist dirty memory to disk."""
    global _memory_dirty
    if not _memory_dirty:
        return True
    path = _MEMORY_PATH
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_memory, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        _memory_dirty = False
        return True
    except Exception as e:
        print(f"[genre_zh] save memory failed: {e}")
        return False


def remember(src: str, zh: str) -> None:
    """Record src→zh in memory if new (survives restarts, not re-translated)."""
    global _memory_dirty
    load_memory()
    key = _norm_key(src)
    val = (zh or "").strip()
    if not key or not val:
        return
    if _memory.get(key) == val:
        return
    _memory[key] = val
    _memory_dirty = True


def _lookup_static(key: str) -> str:
    if key in _GENRE_MAP:
        return _GENRE_MAP[key]
    low = key.lower()
    for k, v in _GENRE_MAP.items():
        if _norm_key(k).lower() == low:
            return v
    key2 = re.sub(r"\(.*?\)", "", key).strip()
    if key2 and key2 != key:
        if key2 in _GENRE_MAP:
            return _GENRE_MAP[key2]
        for k, v in _GENRE_MAP.items():
            if _norm_key(k).lower() == key2.lower():
                return v
    return ""


def translate_genre(name: str) -> str:
    """Map one genre to a display label, then snap to blocked_genres.txt spelling.

    Order: static map → memory → original; finally align to user blocked list
    so Go exact-match filter still works without re-blocking aliases.
    """
    raw = (name or "").strip()
    if not raw:
        return ""
    load_memory()
    key = _norm_key(raw)
    hit = _lookup_static(key)
    mem_val = _memory.get(key)
    # Static map wins when memory still holds Japanese (stale self-map)
    if hit:
        out = hit
        if mem_val != hit:
            remember(raw, hit)
    elif mem_val:
        out = mem_val
    elif not _looks_japanese(raw):
        out = raw
    else:
        # unknown Japanese: leave as-is until mapped into static/memory
        out = raw
    snapped = snap_to_blocked(out)
    if snapped != out:
        remember(raw, snapped)
    return snapped


def translate_genres(genres: Iterable[str], persist: bool = True) -> List[str]:
    """Translate/normalize and de-dupe, preserve order. Optionally flush memory."""
    out: List[str] = []
    seen = set()
    for g in genres or []:
        zh = translate_genre(g)
        if not zh or zh in seen:
            continue
        seen.add(zh)
        out.append(zh)
    if persist:
        save_memory()
    return out


def merge_genres(*lists: Iterable[str]) -> List[str]:
    """Merge genre lists, normalize, de-dupe."""
    combined = []
    for lst in lists:
        if not lst:
            continue
        for g in lst:
            if g:
                combined.append(str(g))
    return translate_genres(combined)


def normalize_item_genres(item: dict) -> bool:
    """Rewrite item['genres'] through translate_genres. Returns True if changed."""
    before = list(item.get("genres") or [])
    after = translate_genres(before)
    if after != before:
        item["genres"] = after
        return True
    return False
