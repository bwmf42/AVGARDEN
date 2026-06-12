"""统一日志写入 /logs/av-garden.log，保留30天"""
import os, time
from datetime import datetime, timedelta

LOG_DIR = os.environ.get("LOG_DIR", "/logs")
LOG_FILE = os.path.join(LOG_DIR, "av-garden.log")
MAX_DAYS = 30


def write(source, message):
    """写入一条日志。source: DailyUpdater/ReplaceCN/Downloader/Worker"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{source}] {message}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except:
        pass


def cleanup():
    """删除30天前的旧日志行(重写文件)"""
    try:
        if not os.path.exists(LOG_FILE):
            return
        cutoff = datetime.now() - timedelta(days=MAX_DAYS)
        with open(LOG_FILE) as f:
            lines = f.readlines()
        kept = []
        for line in lines:
            try:
                ts_str = line[:19]
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if dt >= cutoff:
                    kept.append(line)
            except:
                kept.append(line)
        if len(kept) < len(lines):
            with open(LOG_FILE, "w") as f:
                f.writelines(kept)
    except:
        pass
