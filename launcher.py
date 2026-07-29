#!/usr/bin/env python3
"""
AV/GARDEN Container Launcher — 统一管理 worker + queue_api 生命周期

行为：
- 启动时：先起 queue_api，再起 worker
- 停止时(SIGTERM/SIGINT)：先停 worker（保存当前下载→放回队列），再停 queue_api
- 重启后：放回队列的任务被 queue_api 启动自检索取，重新下载
"""
import os, sys, signal, subprocess, time, json, random, threading
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from queue_store import append_unique
from src.log_writer import write as log_write

WORKER_PY = "/app/worker.py"
QUEUE_API_PY = "/app/queue_api.py"
QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
CURRENT_PATH = os.environ.get("CURRENT_PATH", "/db/current_download.txt")
LOCK_PATH = "/app/work"
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
DAILY_UPDATE_STATE_PATH = os.environ.get("DAILY_UPDATE_STATE_PATH", "/db/daily_updater_state.json")

worker_proc = None
queue_proc = None
running = True


def log(msg):
    print(f"[Launcher] {msg}", flush=True)


def read_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        log(f"Failed to write {path}: {e}")


def daily_update_completed_on(day):
    state = read_json(DAILY_UPDATE_STATE_PATH, {})
    if state.get("last_success_date") == day:
        return True

    log_file = os.environ.get("LOG_FILE", os.path.join(os.environ.get("LOG_DIR", "/logs"), "av-garden.log"))
    try:
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                for line in f:
                    if line.startswith(day) and "[DailyUpdater]" in line and "刮削完成" in line:
                        return True
    except Exception:
        pass
    return False


def mark_daily_update_completed(day):
    write_json(DAILY_UPDATE_STATE_PATH, {
        "last_success_date": day,
        "last_success_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def random_time_between(start, end):
    seconds = max(0, int((end - start).total_seconds()))
    return start + timedelta(seconds=random.randint(0, seconds))


def next_daily_update_target(now):
    today = now.strftime("%Y-%m-%d")
    if daily_update_completed_on(today):
        target_day = now.date() + timedelta(days=1)
        start = datetime.combine(target_day, datetime.min.time()).replace(hour=13)
        end = datetime.combine(target_day, datetime.min.time()).replace(hour=17, minute=59)
        return random_time_between(start, end)

    start = now.replace(hour=13, minute=0, second=0, microsecond=0)
    end = now.replace(hour=17, minute=59, second=0, microsecond=0)
    if now < start:
        return random_time_between(start, end)
    if now <= end:
        start_from_now = min(now + timedelta(minutes=1), end)
        return random_time_between(start_from_now, end)

    tomorrow = now.date() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time()).replace(hour=13)
    end = datetime.combine(tomorrow, datetime.min.time()).replace(hour=17, minute=59)
    return random_time_between(start, end)


def next_retention_target(now):
    target = now.replace(hour=4, minute=30, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def save_current_back_to_queue():
    """停止前将当前下载任务放回队列"""
    current = None
    try:
        with open(CURRENT_PATH, "r") as f:
            current = f.read().strip()
    except:
        pass
    
    if current:
        try:
            if append_unique(QUEUE_PATH, current):
                log(f"Saved current download back to queue: {current}")
        except Exception as e:
            log(f"Failed to save to queue: {e}")
        
        # 清理当前下载标记
        try:
            os.remove(CURRENT_PATH)
        except:
            pass
    
    # 释放锁
    try:
        with open(LOCK_PATH, "w") as f:
            f.write("0")
        log("Lock released")
    except:
        pass


def signal_handler(sig, frame):
    global running
    log(f"Received signal {sig}, shutting down gracefully...")
    running = False
    
    # 1. 先停 worker（保存当前下载）
    if worker_proc and worker_proc.poll() is None:
        log("Stopping worker...")
        worker_proc.terminate()
        try:
            worker_proc.wait(timeout=10)
            log("Worker stopped")
        except:
            log("Worker force kill")
            worker_proc.kill()
    
    # 2. 保存当前下载到队列
    save_current_back_to_queue()
    
    # 3. 停 queue_api
    if queue_proc and queue_proc.poll() is None:
        log("Stopping queue_api...")
        queue_proc.terminate()
        try:
            queue_proc.wait(timeout=5)
        except:
            queue_proc.kill()
    
    sys.exit(0)


def merge_watcher():
    """每2小时检查中文版是否下载完成，完成则合并"""
    import importlib
    while running:
        time.sleep(7200)
        if not running:
            break
        try:
            log("Checking Chinese torrent merge...")
            rc = importlib.import_module("replace_chinese")
            rc.merge_completed_chinese()
        except Exception as e:
            log(f"Merge watcher error: {e}")


def run_titlezh_retry(reason=""):
    """补译缺失 titleZh（DeepSeek 偶发失败的自动重试）。

    前台只记有产出/失败；空转只打 launcher 控制台。
    """
    tag = f" ({reason})" if reason else ""
    log(f"Running plwt_translate_missing{tag}...")
    try:
        proc = subprocess.run(
            ["/app/venv/bin/python3", "/app/plwt_translate_missing.py"],
            timeout=3600,
            check=False,
            capture_output=True,
            text=True,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.stdout:
            sys.stdout.write(proc.stdout)
            sys.stdout.flush()
        if proc.stderr:
            sys.stderr.write(proc.stderr)
            sys.stderr.flush()
        # 解析补译结果：有 ok/fail/stripped 才写前台
        ok = fail = stripped = cleared = None
        for line in out.splitlines():
            if "Done ok=" in line or "Translate done: ok=" in line:
                # Done ok=48 fail=16 stripped=0 ...
                import re as _re
                m = _re.search(r"ok=(\d+).*fail=(\d+)", line)
                if m:
                    ok, fail = int(m.group(1)), int(m.group(2))
                m2 = _re.search(r"stripped=(\d+)", line)
                if m2:
                    stripped = int(m2.group(1))
                m3 = _re.search(r"cleared=(\d+)", line)
                if m3:
                    cleared = int(m3.group(1))
            if "Missing titleZh before:" in line and "0" in line.split(":")[-1]:
                pass
        if ok is None and fail is None:
            if proc.returncode != 0:
                log_write("TitleZhRetry", f"补译失败{tag}: exit={proc.returncode}")
            else:
                log(f"TitleZhRetry empty run{tag}")
        elif (ok or 0) > 0 or (fail or 0) > 0 or (stripped or 0) > 0 or (cleared or 0) > 0:
            log_write(
                "TitleZhRetry",
                f"补译完成{tag}: ok={ok or 0} fail={fail or 0}"
                + (f" stripped={stripped}" if stripped else "")
                + (f" cleared={cleared}" if cleared else ""),
            )
        else:
            log(f"TitleZhRetry nothing to do{tag}")
    except Exception as e:
        log(f"plwt_translate_missing failed{tag}: {e}")
        log_write("TitleZhRetry", f"补译失败{tag}: {e}")


def titlezh_retry_watcher():
    """定时补漏：缺 titleZh 时自动重试（默认每 3 小时）。

    自愈 heal_runner 也会补译；此处保留作更长周期兜底。
    """
    hours = float(os.environ.get("TITLEZH_RETRY_INTERVAL_H", "3") or "3")
    interval = max(1800.0, hours * 3600.0)
    # 启动后稍等，避免和开机刮削抢锁
    time.sleep(120)
    while running:
        try:
            run_titlezh_retry("scheduled")
        except Exception as e:
            log(f"titlezh_retry_watcher error: {e}")
        # sleep in chunks so SIGTERM can exit
        slept = 0.0
        while running and slept < interval:
            time.sleep(min(60.0, interval - slept))
            slept += 60.0


def heal_watcher():
    """周期自愈（默认 1h）：补译、队列对齐、探活告警。不重刮、不删种。"""
    if os.environ.get("HEAL_ENABLE", "1").strip().lower() in ("0", "false", "no", "off"):
        log("Heal watcher disabled (HEAL_ENABLE=0)")
        return
    hours = float(os.environ.get("HEAL_INTERVAL_H", "1") or "1")
    interval = max(900.0, hours * 3600.0)
    # 启动后 3 分钟再跑，避开开机刮削/锁
    time.sleep(180)
    py = os.environ.get("WORKER_PYTHON", "/app/venv/bin/python3")
    script = "/app/heal_runner.py"
    while running:
        try:
            log("Running heal_runner...")
            subprocess.run([py, script], timeout=3900, check=False)
        except Exception as e:
            log(f"heal_runner error: {e}")
        slept = 0.0
        while running and slept < interval:
            time.sleep(min(60.0, interval - slept))
            slept += 60.0


def retention_watcher():
    """Daily guarded retention: watched 30d, blocked metadata-only, routine records 30d."""
    if os.environ.get("WEEKLY_RETENTION_ENABLE", "1").strip().lower() in ("0", "false", "no", "off"):
        log("Weekly retention disabled (WEEKLY_RETENTION_ENABLE=0)")
        return
    py = os.environ.get("WORKER_PYTHON", "/app/venv/bin/python3")
    script = "/app/tools/maintenance/weekly_retention_maintenance.py"
    while running:
        now = datetime.now()
        target = next_retention_target(now)
        delay = max(0.0, (target - now).total_seconds())
        log(f"Weekly retention: next run at {target.strftime('%Y-%m-%d %H:%M')}")
        slept = 0.0
        while running and slept < delay:
            chunk = min(60.0, delay - slept)
            time.sleep(chunk)
            slept += chunk
        if not running:
            return
        try:
            proc = subprocess.run(
                [py, script, "--auto"],
                timeout=3600,
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.stdout:
                sys.stdout.write(proc.stdout)
                sys.stdout.flush()
            if proc.stderr:
                sys.stderr.write(proc.stderr)
                sys.stderr.flush()
            if proc.returncode == 0:
                log_write("WeeklyRetention", "自动清理完成")
            else:
                log_write("WeeklyRetention", f"自动清理失败: exit={proc.returncode}")
        except Exception as e:
            log(f"weekly retention failed: {e}")
            log_write("WeeklyRetention", f"自动清理失败: {e}")


def daily_updater():
    """每天 13:00-18:00 随机时间运行 weekly_updater"""
    while running:
        now = datetime.now()
        target = next_daily_update_target(now)
        delay = (target - now).total_seconds()
        log(f"Daily updater: next run at {target.strftime('%Y-%m-%d %H:%M')} ({delay/60:.0f} min)")
        time.sleep(delay)
        if not running:
            break
        run_day = datetime.now().strftime("%Y-%m-%d")
        if daily_update_completed_on(run_day):
            log(f"Daily updater: {run_day} already completed, skipping")
            time.sleep(60)
            continue
        log("Running weekly_updater...")
        scrape_ok = False
        try:
            # 不 capture：长任务实时进 docker logs；SSL 已在 sources/forum 内重试+回退
            proc = subprocess.run(
                ["/app/venv/bin/python3", "/app/weekly_updater.py"],
                timeout=7200,
                check=False,
            )
            if proc.returncode == 0:
                log_write("DailyUpdater", "刮削完成 (weekly_updater)")
                mark_daily_update_completed(run_day)
                scrape_ok = True
            else:
                msg = f"weekly_updater exit={proc.returncode}（详见 docker logs 中 WeeklyUpdater/Sources/ChineseForum）"
                log(msg)
                log_write("DailyUpdater", f"刮削失败: exit={proc.returncode} 见容器日志")
        except subprocess.TimeoutExpired:
            log("weekly_updater timed out after 7200s")
            log_write("DailyUpdater", "刮削失败: 超时 7200s")
        except Exception as e:
            log(f"weekly_updater failed: {e}")
            log_write("DailyUpdater", f"刮削失败: {e}")
        # 无论刮削成败都补译（偶发 DeepSeek 失败 / 中断后的缺口）
        run_titlezh_retry("after-scrape" if scrape_ok else "after-scrape-fail")
        if not scrape_ok:
            time.sleep(3600)
            continue
        log("Running replace_chinese...")
        try:
            subprocess.run(["/app/venv/bin/python3", "/app/replace_chinese.py"], timeout=3600)
        except Exception as e:
            log(f"replace_chinese failed: {e}")
        time.sleep(3600)


def main():
    global worker_proc, queue_proc

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log("Starting AV/GARDEN services...")
    
    # 1. 启动 queue_api（先于 worker，用于状态恢复）
    env = os.environ.copy()
    env["STATE_PATH"] = STATE_PATH
    env["QUEUE_PATH"] = QUEUE_PATH
    env["CURRENT_PATH"] = CURRENT_PATH
    env["LOCK_PATH"] = LOCK_PATH
    env["SAVE_PATH"] = env.get("SAVE_PATH", "/data")
    env["DB_PATH"] = env.get("DB_PATH", "/db/downloaded.db")
    env["HISTORY_PATH"] = env.get("HISTORY_PATH", "/db/download_history.json")
    
    log("Starting queue_api...")
    queue_python = os.environ.get("QUEUE_API_PYTHON", "/app/venv/bin/python3")
    queue_proc = subprocess.Popen(
        [queue_python, "-u", QUEUE_API_PY],
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    log(f"queue_api started (PID {queue_proc.pid})")
    
    # 等 queue_api 完成启动自检
    time.sleep(2)
    
    # 2. 启动 worker（使用 venv 的 Python）
    log("Starting worker...")
    worker_python = os.environ.get("WORKER_PYTHON", "/app/venv/bin/python3")
    worker_proc = subprocess.Popen(
        [worker_python, "-u", WORKER_PY],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    log(f"worker started (PID {worker_proc.pid})")

    # 3. 启动每日刮削定时器
    t = threading.Thread(target=daily_updater, daemon=True)
    t.start()
    # 4. 启动中文版合并检查(每2小时)
    t2 = threading.Thread(target=merge_watcher, daemon=True)
    t2.start()
    # 5. 缺 titleZh 定时补译（DeepSeek 偶发失败）
    t3 = threading.Thread(target=titlezh_retry_watcher, daemon=True)
    t3.start()
    # 6. 自愈：补译/队列对齐/探活（不重刮）
    t4 = threading.Thread(target=heal_watcher, daemon=True)
    t4.start()
    # 7. Weekly 已看/屏蔽条目和例行维护记录自动保留策略
    t5 = threading.Thread(target=retention_watcher, daemon=True)
    t5.start()

    # 等待任意一个退出
    while running:
        if worker_proc.poll() is not None:
            log(f"Worker exited with code {worker_proc.returncode}")
            break
        if queue_proc.poll() is not None:
            log(f"Queue API exited with code {queue_proc.returncode}")
            break
        time.sleep(1)
    
    # 清理
    save_current_back_to_queue()
    
    for proc, name in [(worker_proc, "worker"), (queue_proc, "queue_api")]:
        if proc and proc.poll() is None:
            log(f"Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except:
                proc.kill()
    
    log("All services stopped")


if __name__ == "__main__":
    main()
