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
from queue_store import append_unique, clear_if_matches, read_queue, write_json as atomic_write_json
from src.log_writer import write as log_write
from src.scrape_pipeline import (
    PHASE_WEEKLY,
    begin_pipeline,
    finish_pipeline,
    interrupt_running_pipeline,
    read_status as read_scrape_status,
)

WORKER_PY = "/app/worker.py"
QUEUE_API_PY = "/app/queue_api.py"
QUEUE_PATH = os.environ.get("QUEUE_PATH", "/db/download_queue.txt")
CURRENT_PATH = os.environ.get("CURRENT_PATH", "/db/current_download.txt")
LOCK_PATH = "/app/work"
STATE_PATH = os.environ.get("STATE_PATH", "/db/queue_state.json")
DAILY_UPDATE_STATE_PATH = os.environ.get("DAILY_UPDATE_STATE_PATH", "/db/daily_updater_state.json")
MERGE_STATE_PATH = os.environ.get("MERGE_STATE_PATH", "/db/merge_chinese_state.json")

worker_proc = None
queue_proc = None
running = True


def log(msg):
    print(f"[Launcher] {msg}", flush=True)


def assert_download_source_healthy():
    """启动自检：_plwt_search_slot 必须是 contextmanager，否则磁链解析全挂。"""
    import tempfile
    from download_source import _plwt_search_slot

    fd, path = tempfile.mkstemp(prefix="plwt_slot_", suffix=".json")
    os.close(fd)
    try:
        os.unlink(path)
    except OSError:
        pass
    try:
        with _plwt_search_slot(path):
            pass
    except TypeError as e:
        if "generator" in str(e).lower() or "context manager" in str(e).lower():
            raise RuntimeError(
                "download_source._plwt_search_slot 缺少 @contextmanager，"
                "会导致所有下载在取磁链阶段失败。请部署修复后的 download_source.py"
            ) from e
        raise
    finally:
        for p in (path, path + ".slot.lock"):
            try:
                os.unlink(p)
            except OSError:
                pass


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
        atomic_write_json(path, data)
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
                    if (
                        line.startswith(day)
                        and "[DailyUpdater]" in line
                        and "刮削完成（含未看中文补链）" in line
                    ):
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


WATCHER_GUARD_ENABLE = os.environ.get("WATCHER_GUARD_ENABLE", "1").strip().lower() in (
    "1", "true", "yes", "on",
)
WATCHER_GUARD_BACKOFF_S = max(15, int(os.environ.get("WATCHER_GUARD_BACKOFF_S", "60") or "60"))
STATUS_REPORT_ENABLE = os.environ.get("STATUS_REPORT_ENABLE", "1").strip().lower() in (
    "1", "true", "yes", "on",
)
DB_BACKUP_ENABLE = os.environ.get("DB_BACKUP_ENABLE", "1").strip().lower() in (
    "1", "true", "yes", "on",
)


def start_guarded_thread(name, target):
    """Start daemon thread; on crash, backoff and restart while launcher running.

    Clean return (disable flags / normal exit) does not restart.
    Set WATCHER_GUARD_ENABLE=0 to disable restarts (still catch+log once).
    """
    def loop():
        while running:
            try:
                target()
                return
            except Exception as e:
                log(f"watcher {name} crashed: {e}")
                log_write("Launcher", f"watcher {name} 崩溃: {e}")
                if not WATCHER_GUARD_ENABLE or not running:
                    return
                log(f"watcher {name}: restart in {WATCHER_GUARD_BACKOFF_S}s")
                slept = 0
                while running and slept < WATCHER_GUARD_BACKOFF_S:
                    time.sleep(min(5, WATCHER_GUARD_BACKOFF_S - slept))
                    slept += 5

    t = threading.Thread(target=loop, name=name, daemon=True)
    t.start()
    return t


def run_morning_status_jobs():
    """04:30: sqlite backup + daily-report.json (same schedule as retention)."""
    if not STATUS_REPORT_ENABLE and not DB_BACKUP_ENABLE:
        return
    try:
        from src import status_report as sr

        if DB_BACKUP_ENABLE:
            bak = sr.backup_sqlite()
            if bak.get("ok"):
                log_write("Backup", f"数据库备份完成: {bak.get('path')}")
            else:
                log_write("Backup", f"数据库备份失败: {bak.get('msg')}")
        if STATUS_REPORT_ENABLE:
            sr.write_daily_report()
            log("daily-report.json updated")
    except Exception as e:
        log(f"morning status jobs failed: {e}")
        log_write("StatusReport", f"日报/备份失败: {e}")


def merge_completed_on(day):
    state = read_json(MERGE_STATE_PATH, {})
    return state.get("last_success_date") == day


def mark_merge_completed(day):
    write_json(MERGE_STATE_PATH, {
        "last_success_date": day,
        "last_success_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


def next_merge_target(now):
    """与每日推荐相同：当天 13:00–17:59 随机；今日已跑过则排到次日同窗口。"""
    today = now.strftime("%Y-%m-%d")
    if merge_completed_on(today):
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


def save_current_back_to_queue():
    """停止前将当前下载任务放回队列"""
    current_items = read_queue(CURRENT_PATH)
    current = current_items[0] if current_items else None
    
    if current:
        saved = False
        try:
            if append_unique(QUEUE_PATH, current):
                log(f"Saved current download back to queue: {current}")
            saved = True
        except Exception as e:
            log(f"Failed to save to queue: {e}")
        if saved:
            clear_if_matches(CURRENT_PATH, current)
    
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
    """每天一轮中文版合并/清理，定时逻辑与每日推荐一致（13:00–18:00 随机）。

    关闭：MERGE_ENABLE=0
    """
    import importlib

    if os.environ.get("MERGE_ENABLE", "1").strip().lower() in ("0", "false", "no", "off"):
        log("Merge watcher disabled (MERGE_ENABLE=0)")
        return

    while running:
        now = datetime.now()
        target = next_merge_target(now)
        delay = max(0.0, (target - now).total_seconds())
        log(f"Chinese merge: next run at {target.strftime('%Y-%m-%d %H:%M')} ({delay/60:.0f} min)")
        slept = 0.0
        while running and slept < delay:
            chunk = min(60.0, delay - slept)
            time.sleep(chunk)
            slept += chunk
        if not running:
            break

        run_day = datetime.now().strftime("%Y-%m-%d")
        if merge_completed_on(run_day):
            log(f"Chinese merge: {run_day} already completed, skipping")
            time.sleep(60)
            continue

        try:
            log("Checking Chinese torrent merge (daily)...")
            rc = importlib.import_module("replace_chinese")
            rc.merge_completed_chinese()
            mark_merge_completed(run_day)
            log_write("ReplaceCN", f"每日中文合并完成 ({run_day})")
        except Exception as e:
            log(f"Merge watcher error: {e}")
            log_write("ReplaceCN", f"每日中文合并失败: {e}")
            # 失败不 mark，当天窗口内可再排一次
            time.sleep(3600)


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


def link115_watcher():
    """周期把 115生活备份/艾薇 下的番号软链到 /data 根（不出现「艾薇」目录）。

    默认 10 分钟；备份落盘后较快能在 2 根目录看到。
    关闭：LINK115_ENABLE=0
    """
    if os.environ.get("LINK115_ENABLE", "1").strip().lower() in ("0", "false", "no", "off"):
        log("link115 watcher disabled (LINK115_ENABLE=0)")
        return
    minutes = float(os.environ.get("LINK115_INTERVAL_M", "10") or "10")
    interval = max(120.0, minutes * 60.0)
    # 启动后稍等，让 /data 挂载就绪
    time.sleep(60)
    log(f"link115 watcher every {interval:.0f}s")
    while running:
        try:
            from tools.maintenance.link_115_aiwei_into_data_root import sync_links

            save = os.environ.get("SAVE_PATH", "/data")
            stats = sync_links(data_root=save)
            if stats.get("missing_source"):
                log(f"link115: wait source {save}/115生活备份/艾薇")
            else:
                n = int(stats.get("linked") or 0) + int(stats.get("refreshed") or 0)
                if n or stats.get("removed_aiwei"):
                    names = ",".join((stats.get("names") or [])[:8])
                    msg = f"115链接: 新增/更新={n}" + (f" ({names})" if names else "")
                    log(msg)
                    try:
                        log_write("Heal", msg)
                    except Exception:
                        pass
        except Exception as e:
            log(f"link115 watcher error: {e}")
        slept = 0.0
        while running and slept < interval:
            time.sleep(min(30.0, interval - slept))
            slept += 30.0


def retention_watcher():
    """Daily 04:30: optional weekly retention + sqlite backup + status daily report."""
    retention_on = os.environ.get("WEEKLY_RETENTION_ENABLE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    if not retention_on:
        log("Weekly retention disabled (WEEKLY_RETENTION_ENABLE=0); backup/report still run at 04:30")
    py = os.environ.get("WORKER_PYTHON", "/app/venv/bin/python3")
    script = "/app/tools/maintenance/weekly_retention_maintenance.py"
    while running:
        now = datetime.now()
        target = next_retention_target(now)
        delay = max(0.0, (target - now).total_seconds())
        log(f"Weekly retention/backup: next run at {target.strftime('%Y-%m-%d %H:%M')}")
        slept = 0.0
        while running and slept < delay:
            chunk = min(60.0, delay - slept)
            time.sleep(chunk)
            slept += chunk
        if not running:
            return
        if retention_on:
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
        # Same 04:30 window: DB backup + status daily report
        try:
            run_morning_status_jobs()
        except Exception as e:
            log(f"morning status jobs: {e}")


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
        if not begin_pipeline(PHASE_WEEKLY, trigger="daily"):
            log("Daily updater: another scrape pipeline is running; retry later")
            time.sleep(3600)
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
                log_write("DailyUpdater", "每日推荐阶段完成 (weekly_updater)")
                scrape_ok = True
            else:
                msg = f"weekly_updater exit={proc.returncode}（详见 docker logs 中 WeeklyUpdater/Sources/ChineseForum）"
                log(msg)
                log_write("DailyUpdater", f"刮削失败: exit={proc.returncode} 见容器日志")
                finish_pipeline(summary="每日推荐刮削未完成", error=msg)
        except subprocess.TimeoutExpired:
            log("weekly_updater timed out after 7200s")
            log_write("DailyUpdater", "刮削失败: 超时 7200s")
            finish_pipeline(summary="每日推荐刮削未完成", error="weekly_updater 超时 7200s")
        except Exception as e:
            log(f"weekly_updater failed: {e}")
            log_write("DailyUpdater", f"刮削失败: {e}")
            finish_pipeline(summary="每日推荐刮削未完成", error=str(e))
        if not scrape_ok:
            time.sleep(3600)
            continue
        log("Running safe unwatched Chinese magnet follow-up...")
        try:
            followup = subprocess.run(
                ["/app/venv/bin/python3", "/app/run_scrape_followups.py"],
                timeout=3900,
                check=False,
            )
            if followup.returncode == 0:
                mark_daily_update_completed(run_day)
                log_write("DailyUpdater", "刮削完成（含未看中文补链）")
            else:
                log(f"unwatched Chinese follow-up failed: exit={followup.returncode}")
                log_write("DailyUpdater", f"未看中文补链失败: exit={followup.returncode}")
                status = read_scrape_status()
                if status.get("running"):
                    finish_pipeline(
                        summary="每日推荐已更新，但未看中文补链未完成",
                        error=str(status.get("last_error") or f"follow-up exit={followup.returncode}"),
                        stats=status.get("stats") if isinstance(status.get("stats"), dict) else {},
                    )
        except subprocess.TimeoutExpired:
            finish_pipeline(summary="每日推荐已更新", error="未看中文补链超时 3900s")
            log("unwatched Chinese follow-up timed out after 3900s")
        except Exception as e:
            finish_pipeline(summary="每日推荐已更新", error=f"未看中文补链异常: {e}")
            log(f"unwatched Chinese follow-up failed: {e}")
        time.sleep(3600)


def main():
    global worker_proc, queue_proc

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        assert_download_source_healthy()
        log("download_source slot contextmanager OK")
    except Exception as e:
        log(f"FATAL: download_source health check failed: {e}")
        log_write("Launcher", f"启动失败: download_source 异常 {e}")
        sys.exit(2)

    # 启动后自动捞回「瞬时/系统」失败项，避免 UI 一直挂着旧失败
    try:
        from src.failure_recovery import recover_transient_failures

        hours = float(os.environ.get("RECOVER_FAILED_MAX_AGE_H", "72") or "72")
        stats = recover_transient_failures(max_age_hours=hours, default_target="qb")
        rec = stats.get("recovered") or []
        if rec:
            msg = f"自动恢复失败项 {len(rec)} 个: {','.join(rec[:12])}"
            log(msg)
            log_write("Heal", msg)
        else:
            log("no transient failures to recover")
    except Exception as e:
        log(f"recover_transient_failures: {e}")

    if interrupt_running_pipeline():
        log("cleared interrupted scrape pipeline state after Worker restart")
        log_write("Launcher", "Worker 重启，上一轮刮削流程已标记为中断")

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

    # 3–8. background watchers (guarded: crash → 60s backoff restart)
    start_guarded_thread("daily_updater", daily_updater)
    start_guarded_thread("merge_watcher", merge_watcher)
    start_guarded_thread("titlezh_retry_watcher", titlezh_retry_watcher)
    start_guarded_thread("heal_watcher", heal_watcher)
    start_guarded_thread("retention_watcher", retention_watcher)
    start_guarded_thread("link115_watcher", link115_watcher)
    log(f"watchers started (guard={'on' if WATCHER_GUARD_ENABLE else 'off'})")

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
