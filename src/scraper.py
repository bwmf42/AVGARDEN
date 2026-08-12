# doc: 使用javbus刮削
import json
from loguru import logger
import os
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict
from pathlib import Path
from .comm import *
from curl_cffi import requests
from PIL import Image
from datetime import datetime
from urllib.parse import urljoin, urlparse
import time
import re
from xml.etree import ElementTree as ET
from xml.dom import minidom

def is_complete_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

# 详细的元数据
@dataclass
class AVMetadata:
    title: str = ""
    title_zh: str = ""
    cover: str = ""
    avid: str = ""
    actress: dict = field(default_factory=dict)
    description: str = ""
    duration: str = ""
    release_date: str = ""
    keywords: List[str] = field(default_factory=list)
    fanarts: List[str] = field(default_factory=list)

    def __str__(self):
        # 格式化演员信息
        actress_str = "\n    ".join(
            [f"{name} ({avatar})" for name, avatar in self.actress.items()]
        ) if self.actress else "无"

        # 格式化关键词
        keywords_str = ", ".join(self.keywords) if self.keywords else "无"

        # 格式化样品图像
        fanart_str = ", ".join(self.fanarts) if self.fanarts else "无"

        return (
            "=== 元数据详情 ===\n"
            f"番号: {self.avid or '未知'}\n"
            f"标题: {self.title or '未知'}\n"
            + (f"中文: {self.title_zh}\n" if self.title_zh else "") +
            f"发行日期: {self.release_date or '未知'}\n"
            f"时长: {self.duration or '未知'}\n"
            f"演员及头像:\n    {actress_str}\n"
            f"关键词: {keywords_str}\n"
            f"描述: {self.description or '无'}\n"
            f"封面URL: {self.cover or '无'}\n"
            f"样品图像: {fanart_str}\n"
            "================="
        )

    def to_json(self, file_path: str, indent: int = 2) -> bool:
        try:
            path = Path(file_path) if isinstance(file_path, str) else file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with path.open('w', encoding='utf-8') as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=indent)
            return True
        except (IOError, TypeError) as e:
            logger.error(f"JSON序列化失败: {str(e)}")
            return False

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cookie": "PHPSESSID=kesgcjj4fklf91ojbaocbkbao2; age=verified; existmag=mag",
    "Referer": scraperDomain,
    "Sec-Fetch-Mode": "navigate"
}
     
class Sracper:
    def __init__(self, path: str, proxy = None, timeout = 15, output_subdir = None):
        """
        :path: 配置的路径，如/vol2/user/missav
        :avid: 车牌号
        :output_subdir: 实际保存文件的子目录名（默认跟avid一致）
        """
        self.path = path
        self.proxy = proxy
        self.proxies = {
            'http': proxy,
            'https': proxy
        } if proxy else None
        self.timeout = timeout
        self.domain = scraperDomain
        self.output_subdir = output_subdir

    def scrape(self, avid: str) -> Optional[AVMetadata]:
        # 获取html
        url= f"https://{self.domain}/{avid.upper()}"
        logger.info(url)
        html = self._fetch_html(url, referer="self.domain")
        if html is None:
            return None
        logger.info("fetch html succ")
        
        # 解析元数据
        metadata = self._extract(html)
        if not metadata:
            return None
        logger.info(f"parse metadata succ: \n{metadata}")

        # 翻译标题
        self.translate_title(metadata)

        # 下载图像
        if not self.downloadIMG(metadata):
            return None
        logger.info(f"download img succ")

        # 生成nfo
        self.genNFO(metadata)
        logger.info(f"gennfo succ")
        return metadata


    def translate_title(self, metadata: AVMetadata):
        """使用中继优先、DeepSeek 回退的翻译服务生成中文标题。"""
        if not metadata.title:
            return
        try:
            import urllib.request
            relay_base = os.environ.get("TRANSLATE_API_BASE", "").strip().rstrip("/")
            relay_key = os.environ.get("TRANSLATE_API_KEY", "").strip()
            if relay_base and relay_key:
                api_base = relay_base
                api_key = relay_key
                model = (os.environ.get("TRANSLATE_MODEL") or "gpt-5.4").strip()
                provider = "relay"
            else:
                api_base = "https://api.deepseek.com"
                api_key = os.environ["DEEPSEEK_API_KEY"]
                raw_model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
                model = {
                    "deepseek-chat": "deepseek-v4-flash",
                    "deepseek-reasoner": "deepseek-v4-pro",
                }.get(raw_model, raw_model)
                provider = "deepseek"
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是日语翻译助手。将日文成人影片标题翻译为简洁的中文，只输出翻译结果，不要任何解释。"},
                    {"role": "user", "content": metadata.title}
                ],
                "max_tokens": 128,
                "temperature": 0.3
            }).encode()
            endpoint = api_base if api_base.endswith("/chat/completions") else f"{api_base}/chat/completions"
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read().decode())
            if provider == "deepseek":
                try:
                    from src.status_report import record_deepseek_usage
                    record_deepseek_usage(1)
                except Exception:
                    pass
            zh = result["choices"][0]["message"]["content"].strip()
            if zh and zh != metadata.title:
                metadata.title_zh = zh
                logger.info(f"Translated ({provider}/{model}): {metadata.title[:30]}... -> {zh}")
        except Exception as e:
            logger.warning(f"Translation failed: {e}")

    def _extract(self, html: str) -> Optional[AVMetadata]:
        try:
            metadata = AVMetadata()
            avid_match = re.search(r'<title>\s*([A-Z0-9]+-\d+[A-Z]?)', html, re.I)
            title_match = re.search(r'<title>(.*?) - JavBus</title>', html, re.I | re.S)
            cover_match = re.search(
                r'<a class="bigImage" href="([^"]+)"[^>]*>\s*<img[^>]+src="([^"]+)"',
                html,
                re.I,
            )
            if not avid_match or not title_match or not cover_match:
                logger.error("JavBus page is missing required id, title, or cover fields")
                return None
            avid = avid_match.group(1).upper()
            logger.debug(avid)
            title = title_match.group(1).strip()
            logger.debug(title)
            cover = cover_match.group(1).strip()
            logger.debug(cover)
            desc_match = re.search(r'<meta name="description" content="([^"]*)">', html, re.I)
            desc = desc_match.group(1).strip() if desc_match else ""
            logger.debug(desc)
            keywords_match = re.search(r'<meta name="keywords" content="([^"]*)">', html, re.I)
            keywords = [value.strip() for value in keywords_match.group(1).split(',') if value.strip()] if keywords_match else []
            logger.debug(keywords)
            date_match = re.search(r'<span class="header">發行日期:</span>\s*([^<]+)', html, re.I)
            date = date_match.group(1).strip() if date_match else ""
            logger.debug(date)
            duration_match = re.search(r'<span class="header">長度:</span>\s*([^<]+)', html, re.I)
            duration = duration_match.group(1).strip() if duration_match else ""
            logger.debug(duration)
            # 7. 提取演员及头像
            actors_pattern = r'<a class="avatar-box" href="[^"]+">\s*<div class="photo-frame">\s*<img src="([^"]+)"[^>]+>\s*</div>\s*<span>([^<]+)</span>'
            actresses = re.findall(actors_pattern, html)
            logger.debug(actresses)
            # 匹配样品图像
            fanart_pattern = r'<a class="sample-box" href="(.*?\.jpg)">'
            fanarts = re.findall(fanart_pattern, html)
            metadata.avid = avid
            metadata.title = title
            if is_complete_url(cover):
                metadata.cover = cover
            else:
                metadata.cover = f"https://{self.domain}{cover}"
            metadata.description = desc
            metadata.keywords = keywords
            metadata.release_date = date
            metadata.duration = duration
            for img, name in actresses:
                if is_complete_url(img):
                    metadata.actress[name] = img
                else:
                    metadata.actress[name] = f"https://{self.domain}{img}"
            metadata.fanarts = fanarts

            return metadata
        
        except Exception as exc:
            logger.exception(f"JavBus metadata parse failed: {exc}")
            return None
    
    def _output_path(self, avid, *paths):
        """返回输出路径，如果设置了 output_subdir 则用它替代 avid"""
        subdir = self.output_subdir if self.output_subdir else avid
        return os.path.join(self.path, subdir, *paths)

    def downloadIMG(self, metadata: AVMetadata) -> bool:
        '''海报+封面+演员头像'''
        # 下载横版海报
        prefix = metadata.avid+"-" # Jellyfin海报格式
        fanartCount = 1
        if self._download_file(metadata.cover, self._output_path(metadata.avid, prefix+f"fanart-{fanartCount}.jpg"), referer=f"https://{self.domain}/{metadata.avid}"):
            # 裁剪竖版封面
            self._crop_img(self._output_path(metadata.avid, prefix+f"fanart-{fanartCount}.jpg"), self._output_path(metadata.avid, prefix+"poster.jpg"))
        else:
            logger.error(f"封面下载失败：{metadata.cover}")
            return False
        
        # 下载预览图
        for fanart in metadata.fanarts:
            fanartCount += 1
            self._download_file(fanart, self._output_path(metadata.avid, prefix+f"fanart-{fanartCount}.jpg"), referer=f"https://{self.domain}/{metadata.avid}")

        # 检查演员是否存在，不存在则下载图像
        for av, url in metadata.actress.items():
            logger.debug(av)
            # 判断是否已经存在
            if os.path.exists(os.path.join(self.path, "thumb", av+".jpg")):
                logger.info(f"av {av} already exist")
                continue
            else:
                self._download_file(url, os.path.join(self.path, "thumb/"+av+".jpg"), referer=f"https://{self.domain}/{metadata.avid}")
        return True

    def genNFO(self, metadata: AVMetadata) -> bool:
        prefix = metadata.avid+"-" # Jellyfin海报格式
        # 创建XML根节点
        root = ET.Element("movie")
        
        # 基础元数据: 中文标题在前，日文保留为 originaltitle
        display_title = metadata.title_zh or metadata.title
        ET.SubElement(root, "title").text = display_title
        if metadata.title_zh and metadata.title_zh != metadata.title:
            ET.SubElement(root, "originaltitle").text = metadata.title
        ET.SubElement(root, "plot").text = metadata.description
        ET.SubElement(root, "outline").text = metadata.description[:100] + "..."
        
        # 发行日期处理
        try:
            release_date = datetime.strptime(metadata.release_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            ET.SubElement(root, "premiered").text = release_date
            ET.SubElement(root, "releasedate").text = release_date
        except ValueError:
            pass
        
        # 时长转换（分钟）
        if "分鐘" in metadata.duration:
            mins = metadata.duration.replace("分鐘", "").strip()
            ET.SubElement(root, "runtime").text = mins
        
        # 海报
        art = ET.SubElement(root, "art") if metadata.cover or metadata.fanarts else None
        if metadata.cover:
            ET.SubElement(art, "poster").text = prefix+"poster.jpg"
        
        # 预览
        for i in range(1, len(metadata.fanarts) + 1):
            ET.SubElement(art, "fanart").text = prefix+f"fanart-{i}.jpg"
        
        # 演员信息
        for name, _ in metadata.actress.items():
            actor = ET.SubElement(root, "actor")
            ET.SubElement(actor, "name").text = name
            ET.SubElement(actor, "thumb").text = os.path.join(self.path, "thumb/"+name+".jpg")
        
        # 类型标签（来自关键词）
        for genre in metadata.keywords[:5]:  # 最多取5个关键词
            ET.SubElement(root, "genre").text = genre

        # 转换为格式化的XML
        xml_str = ET.tostring(root, encoding='utf-8')
        dom = minidom.parseString(xml_str)
        
        # 写入文件
        with open(self._output_path(metadata.avid, metadata.avid+".nfo"), 'w', encoding='utf-8') as f:
            dom.writexml(f, indent="  ", addindent="  ", newl="\n", encoding='utf-8')
        return True

    def _download_file(self, url: str, filename: str, referer: str = "") -> bool:
        """通用下载方法，下载到指定位置"""
        logger.debug(f"download {url} to {os.path.join(self.path, filename)}")
        try:
            newHeader = dict(headers)
            if referer:
                newHeader["Referer"] = referer
            response = requests.get(url, stream=True, impersonate="chrome110", proxies=self.proxies,\
                                    headers=newHeader,timeout=self.timeout, allow_redirects=False)
            response.raise_for_status()
            
            with open(os.path.join(self.path, filename), 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False
    
    def _fetch_html(self, url: str, referer: str = "") -> Optional[str]:
        try:
            newHeader = dict(headers)
            if referer:
                newHeader["Referer"] = referer
            response = requests.get(
                url,
                proxies=self.proxies,
                headers=newHeader,
                timeout=self.timeout,
                impersonate="chrome110",  # 可选：chrome, chrome110, edge99, safari15_5
                allow_redirects=False
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {str(e)}")
            return None
    
    def _crop_img(self, srcname, optname):
        img = Image.open(srcname)
        width, height = img.size
        if height > width:
            return
        target_width = int(height * 565 / 800)
        # 从右侧开始裁剪
        left = width - target_width  # 右侧起点
        right = width
        top = 0
        bottom = height
        # 裁剪并保存
        cropped_img = img.crop((left, top, right, bottom))
        cropped_img.save(optname)
        logger.debug(f"裁剪完成，尺寸: {cropped_img.size}")
