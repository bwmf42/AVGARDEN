# 批量生成 metadata.json和nfo
from src.comm import *
from src import data
import os
import time
from src.scraper import Sracper
import re

# 缓存已清理过的番号
_cleaned_cache = {}

def clean_avid(folder_name):
    """从文件夹名中提取干净的车牌号（去掉 -C, ch, 中文字幕 等后缀）"""
    if folder_name in _cleaned_cache:
        return _cleaned_cache[folder_name]
    name = folder_name.strip()
    source_prefixed = re.match(r'^\d+([A-Za-z]{2,}\d*-\d+)', name)
    if source_prefixed:
        c = source_prefixed.group(1).upper()
        _cleaned_cache[folder_name] = c
        return c
    # 先直接匹配标准番号 A-Z0-9 + 连字符 + 数字
    m = re.match(r'^([A-Za-z0-9]+(?:-\d+)?)', name)
    if m:
        c = m.group(1).upper()
        if re.match(r'^[A-Z0-9]+-\d+$', c):
            _cleaned_cache[folder_name] = c
            return c
    # 逐个去掉常见后缀再匹配
    for pat in [r'-C$', r'ch$', r'-中文字幕$', r'_FHD_CH$', r'_CH$', r'\(\d+\)$', r'\.mp4$']:
        c = re.sub(pat, '', name).upper()
        if re.match(r'^[A-Z0-9]+-\d+$', c):
            _cleaned_cache[folder_name] = c
            return c
    # 在字符串中搜索标准番号模式（字母+数字-数字），如 18BT.NET_VENX-276C -> VENX-276
    search = re.search(r'([A-Za-z]{2,}\d*)-(\d+)', name)
    if search:
        c = f"{search.group(1).upper()}-{search.group(2)}"
        _cleaned_cache[folder_name] = c
        return c
    _cleaned_cache[folder_name] = name.upper()
    return name.upper()

def list_folders(path):
    """返回指定路径下的所有文件夹名称"""
    folders = []
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path):
            folders.append(item)
    return folders

def has_nfo_file(folder_path):
    """检查包括隐藏文件在内的所有.nfo文件"""
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith('.nfo'):
                return True
    return False

def gen_nfo():
    folders = list_folders(save_path)
    data.batch_insert_bvids(folders, downloaded_path, "MissAV") # 多点脏数据也无所谓
    for folder in folders:
        if folder == "thumb":
            continue

        # 检查文件夹中是否有.nfo文件
        if has_nfo_file(os.path.join(save_path, folder)):
            print(f"已有nfo: {folder}")
            continue
        # if os.path.exists(f"{folder}.html"):
        #     print(f"已刮削: {folder}")
        #     continue

        avid = clean_avid(folder)
        print(f"{folder} -> {avid}")
        scraper = Sracper(save_path, myproxy, output_subdir=folder)
        scraper.scrape(avid)

        time.sleep(5)

if __name__ == "__main__":
    data.initialize_db(downloaded_path, "MissAV")
    gen_nfo()
