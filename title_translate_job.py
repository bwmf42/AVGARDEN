"""One asynchronous, title-only NFO job in the worker's Queue API process."""
import copy
import json
import os
from pathlib import Path
import random
import re
import socket
import tempfile
import threading
import time
from urllib.error import URLError

from tools.maintenance import translate_media_titles as titles
from weekly_updater import log

MAX_BODY = 64 * 1024
STATE_PATH = Path('/db/title_translate_state.json')
CODE_RE = re.compile(r'[A-Z0-9]{2,10}-[0-9]{1,6}[A-Z]?', re.I | re.ASCII)
ERROR_KINDS = {'auth', 'quota', 'network', 'config', 'rejected', 'no_folder',
               'unknown', 'aborted', 'interrupted'}


class ValidationError(ValueError):
    pass


def validate_payload(body):
    # Fixed messages only: never echo submitted titles or arbitrary values.
    if not isinstance(body, dict):
        raise ValidationError('请求体必须是 JSON 对象')
    items = body.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValidationError('items 必须包含 1 到 50 项')
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError('items 项必须是对象')
        code, title = item.get('code'), item.get('title')
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            raise ValidationError('番号格式无效')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 500:
            raise ValidationError('标题必须为 1 到 500 字符的字符串')
        normalized.append({'code': code.upper(), 'title': title.strip()})
    force = body.get('force', [])
    codes = {item['code'] for item in normalized}
    if not isinstance(force, list) or any(
        not isinstance(code, str) or code.upper() not in codes for code in force
    ):
        raise ValidationError('force 必须是 items 中的番号数组')
    return normalized, {code.upper() for code in force}


def classify_error(exc):
    message = str(exc).lower()
    if 'translation api is not configured' in message:
        return 'config'
    status = getattr(exc, 'code', None) or getattr(exc, 'status_code', None)
    if status is None:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
    if status in (401, 403) or re.search(r'\b(?:401|403)\b', message) or any(
        word in message for word in ('invalid api key', 'invalid_api_key', 'unauthorized',
                                     'unauthorised', 'authentication', 'forbidden')
    ):
        return 'auth'
    if status in (402, 429) or re.search(r'\b(?:402|429)\b', message) or any(
        word in message for word in ('insufficient', 'quota', 'rate limit', 'rate_limit', 'balance')
    ):
        return 'quota'
    if (isinstance(exc, (URLError, TimeoutError, socket.timeout, ConnectionError))
            or (isinstance(status, int) and 500 <= status < 600)
            or re.search(r'\b5\d\d\b', message)
            or any(word in message for word in (
                'timeout', 'timed out', 'connection', 'dns', 'urlerror',
                'name resolution', 'name or service not known', 'nodename nor servname',
            ))):
        return 'network'
    return 'unknown'


def idle_state():
    return dict(state='idle', started_at=0, finished_at=0, total=0,
                created=0, skipped=0, failed=0, errors=[])


class TitleTranslateJob:
    def __init__(self, media_root=None, state_path=STATE_PATH, logger=log):
        self.media_root = Path(media_root) if media_root is not None else titles.SAVE_PATH
        self.state_path = Path(state_path)
        self.log = logger
        self.lock = threading.Lock()
        self.thread = None
        self.state = idle_state()
        try:
            saved = json.loads(self.state_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return
        # Load only public fields, even if a state file has unexpected content.
        self.state.update({key: saved[key] for key in self.state if key != 'errors' and key in saved})
        self.state['errors'] = [
            {'code': error['code'], 'kind': error['kind']}
            for error in saved.get('errors', [])
            if isinstance(error, dict) and error.get('kind') in ERROR_KINDS
            and isinstance(error.get('code'), str)
            and (not error['code'] or CODE_RE.fullmatch(error['code']))
        ]
        if self.state['state'] == 'running':
            remaining = max(0, self.state['total'] - sum(self.state[key] for key in ('created', 'skipped', 'failed')))
            self.state['skipped'] += remaining
            self.state.update(state='done', finished_at=time.time())
            self.state['errors'].append({'code': '', 'kind': 'interrupted'})

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _save(self):
        """Caller holds lock; readers see either complete old or new JSON."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.state_path.parent, prefix='.title_translate.',
                                             suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(self.state, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
                os.fchmod(handle.fileno(), 0o644)
            os.replace(temporary, self.state_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def submit(self, body):
        items, force = validate_payload(body)
        with self.lock:
            if self.state['state'] == 'running':
                return 409, copy.deepcopy(self.state)
            previous = self.state
            self.state = idle_state()
            self.state.update(state='running', started_at=time.time(), total=len(items))
            try:
                self._save()
            except Exception:
                self.state = previous
                raise
            running = copy.deepcopy(self.state)
            self.thread = threading.Thread(target=self._run, args=(items, force), daemon=True,
                                           name='title-translate')
            try:
                self.thread.start()
            except Exception:
                self.state.update(state='done', finished_at=time.time(), failed=len(items))
                self.state['errors'] = [{'code': item['code'], 'kind': 'unknown'} for item in items]
                self._save()
                raise
            return 202, running

    def _record(self, code, counter, kind=None):
        with self.lock:
            self.state[counter] += 1
            if kind:
                self.state['errors'].append({'code': code, 'kind': kind})
            self._save()
        self.log(f'title-translate code={code} kind={kind or counter}')

    def _run(self, items, force):
        network_started = False

        def before_network():
            nonlocal network_started
            if network_started:
                time.sleep(random.uniform(2.0, 3.0))
            network_started = True

        processed = 0
        try:
            folders = {}
            for folder in titles.iter_missing_folders(self.media_root):
                for code in titles.title_key_candidates(folder.name):
                    folders.setdefault(code, folder)
            aborted = False
            for item in items:
                code = item['code']
                kind = None
                if aborted:
                    counter, kind = 'skipped', 'aborted'
                elif code not in folders:
                    counter, kind = 'skipped', 'no_folder'
                else:
                    errors = []
                    try:
                        result, _ = titles.process_missing_folder(
                            folders[code], apply=True, titles_by_avid={code: item['title']},
                            before_network=before_network, errors=errors, force=code in force,
                        )
                        if result == 'created':
                            counter = 'created'
                        elif result == 'skip':
                            counter = 'skipped'
                        else:
                            counter = 'failed'
                            kind = classify_error(errors[0]) if errors else (
                                'rejected' if result == 'unchanged' else 'unknown')
                    except Exception as exc:
                        counter, kind = 'failed', classify_error(exc)
                processed += 1
                self._record(code, counter, kind)
                if kind in ('auth', 'quota', 'config'):
                    aborted = True
        except Exception:
            # Filesystem/scan failures must finish the job without leaking paths,
            # exception messages, submitted titles or provider responses.
            with self.lock:
                for item in items[processed:]:
                    self.state['failed'] += 1
                    self.state['errors'].append({'code': item['code'], 'kind': 'unknown'})
            self.log('title-translate kind=unknown')
        finally:
            with self.lock:
                self.state.update(state='done', finished_at=time.time())
                try:
                    self._save()
                except OSError:
                    self.log('title-translate kind=unknown')
                counts = ' '.join(f'{key}={self.state[key]}' for key in ('total', 'created', 'skipped', 'failed'))
            self.log(f'title-translate {counts}')
