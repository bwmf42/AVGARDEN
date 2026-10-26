import contextlib
import io
import json
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

# Reuse the existing offline optional-dependency setup, not runtime config.
from test_translate_media_titles import titles
import queue_api
import title_translate_job as jobs


ORIGINAL = 'UNIQUE_ORIGINAL_K4zはじめてのデート'
TRANSLATED = 'UNIQUE_TRANSLATED_M7x 初次约会'
PRIVATE_MARKERS = ('UNIQUE_ORIGINAL_K4z', 'UNIQUE_TRANSLATED_M7x')
SHORT = 'NIMA-083 実写版！不器用な二人 美咲かんな'


class WireSocket:
    """Exercise the HTTP parser and dispatch without opening a socket."""
    def __init__(self, wire):
        self.input = io.BytesIO(wire)
        self.output = bytearray()

    def settimeout(self, timeout):
        self.timeout = timeout

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class TitleTranslateJobTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.media = self.root / 'media'
        self.media.mkdir()
        self.path = self.root / 'state.json'
        self.logs = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.logs))
        self.stack.enter_context(contextlib.redirect_stderr(self.logs))
        self.job = jobs.TitleTranslateJob(self.media, self.path, logger=lambda msg: print(msg))
        self.stack.enter_context(mock.patch.object(queue_api, '_title_translate_job', self.job))
        self.translate = self.stack.enter_context(mock.patch.object(titles, 'translate_title_once', return_value=TRANSLATED))
        self.sleep = self.stack.enter_context(mock.patch.object(jobs.time, 'sleep'))
        self.random = self.stack.enter_context(mock.patch.object(jobs.random, 'uniform', return_value=2.5))
        self.release = threading.Event()
        self.addCleanup(self.finish_thread)

    def finish_thread(self):
        self.release.set()
        if self.job.thread:
            self.job.thread.join(3)
            self.assertFalse(self.job.thread.is_alive(), 'background job did not finish')

    def folder(self, code):
        folder = self.media / code
        folder.mkdir()
        (folder / 'movie.mp4').write_bytes(b'unchanged-video')
        return folder

    def body(self, *codes):
        return {'items': [{'code': code, 'title': ORIGINAL} for code in codes]}

    def request(self, method='GET', body=None, path='/api/title-translate',
                content_type=None, length=None, transfer_encoding=None, slow=False):
        raw = body if isinstance(body, bytes) else (b'' if body is None else json.dumps(body).encode())
        headers = f'Content-Length: {len(raw) if length is None else length}\r\n'
        if content_type is not None:
            headers += f'Content-Type: {content_type}\r\n'
        if transfer_encoding is not None:
            headers += f'Transfer-Encoding: {transfer_encoding}\r\n'
        wire = (f'{method} {path} HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n').encode() + raw
        sock = WireSocket(wire)
        if slow:
            def read(size=-1):
                self.assertEqual(sock.timeout, 10)
                raise socket.timeout(ORIGINAL)
            sock.input.read = read
        queue_api.QueueHandler(sock, ('127.0.0.1', 12345), mock.Mock())
        head, payload = bytes(sock.output).split(b'\r\n\r\n', 1)
        decoded = payload.decode()
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker, decoded)
        return int(head.split()[1]), json.loads(payload)

    def post(self, body, **kwargs):
        return self.request('POST', body, content_type='application/json; charset=utf-8', **kwargs)

    def done(self):
        self.finish_thread()
        state = self.job.snapshot()
        self.assertEqual(state['state'], 'done')
        self.assertEqual(sum(state[key] for key in ('created', 'skipped', 'failed')), state['total'])
        self.assertGreaterEqual(state['finished_at'], state['started_at'])
        self.assertEqual(json.loads(self.path.read_text()), state)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        self.assertEqual(list(self.root.glob('.title_translate.*')), [])
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker, json.dumps(state, ensure_ascii=False) + self.logs.getvalue())
        return state

    def test_http_async_progress_counts_and_title_only_nfo(self):
        first, second = self.folder('ABC-123'), self.folder('ABC-124')
        before = {path: path.read_bytes() for path in self.media.rglob('*.mp4')}
        entered = threading.Event()

        def translate(*args, **kwargs):
            entered.set()
            self.release.wait(3)
            return TRANSLATED

        self.translate.side_effect = translate
        self.assertEqual(self.request()[1]['state'], 'idle')
        status, accepted = self.post(self.body('abc-123', 'ABC-124', 'ABC-125'))
        self.assertEqual((status, accepted['state'], accepted['total']), (202, 'running', 3))
        self.assertEqual(accepted['finished_at'], 0)
        self.assertTrue(entered.wait(3))
        status, running = self.request()
        self.assertEqual((status, running['state']), (200, 'running'))
        self.assertEqual(json.loads(self.path.read_text())['state'], 'running')
        self.release.set()
        state = self.done()
        self.assertEqual((state['created'], state['skipped'], state['failed']), (2, 1, 0))
        self.assertEqual(state['errors'], [{'code': 'ABC-125', 'kind': 'no_folder'}])
        self.assertEqual(self.request(), (200, state))
        self.assertEqual(self.translate.call_count, 2)
        self.sleep.assert_called_once_with(2.5)
        self.random.assert_called_once_with(2.0, 3.0)
        for folder in (first, second):
            nfo = folder / f'{folder.name}.nfo'
            root = ET.parse(nfo).getroot()
            self.assertEqual([node.tag for node in root], ['title', 'originaltitle', 'generator'])
            self.assertEqual(root.findtext('generator'), 'avgarden-title-only/1')
            self.assertEqual(root.findtext('originaltitle'), ORIGINAL)
            self.assertEqual(root.findtext('title'), f'{folder.name} {TRANSLATED}')
            self.assertEqual(stat.S_IMODE(nfo.stat().st_mode), 0o644)
            self.assertEqual({p.name for p in folder.iterdir()}, {'movie.mp4', nfo.name})
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_validation_is_atomic_and_does_not_echo_body(self):
        valid = self.body('ABC-123')
        invalid = [None, [], {}, {'items': []}, {'items': valid['items'] * 51},
                   {'items': [None]}, {'items': [{}]}, {'items': [{'code': 123, 'title': ORIGINAL}]},
                   self.body('../ABC-123'), self.body('A-1'), self.body('ABC-１２３'),
                   {'items': [valid['items'][0], {'code': 'BAD', 'title': ORIGINAL}]}]
        invalid += [{'items': [{'code': 'ABC-123', 'title': title}]}
                    for title in ('', '   ', ORIGINAL * 40, 1, None)]
        invalid += [{**valid, 'force': force} for force in ('ABC-123', None, [1], ['ABC-124'])]
        for body in invalid:
            with self.subTest(body_type=type(body).__name__):
                status, result = self.post(body)
                self.assertEqual(status, 400)
                self.assertEqual(set(result), {'error'})
        for raw in (b'not-json-UNIQUE_ORIGINAL_K4z', b'{', b'\xff'):
            self.assertEqual(self.post(raw)[0], 400)
        self.assertEqual(self.post(b'x' * (jobs.MAX_BODY + 1))[0], 413)
        self.assertEqual(self.post(valid, length=jobs.MAX_BODY + 1)[0], 413)
        for length in ('not-a-length', -1):
            self.assertEqual(self.post(valid, length=length)[0], 400)
        self.assertEqual(self.post(valid, transfer_encoding='chunked')[0], 400)
        self.assertEqual(self.post(valid, length=60000)[0], 400)
        self.assertEqual(self.post(valid, slow=True)[0], 408)
        self.assertEqual(self.job.snapshot()['state'], 'idle')
        self.assertFalse(self.path.exists())
        self.translate.assert_not_called()

    def test_validation_boundaries_and_case_normalization(self):
        body = {'items': [{'code': '123abc-123456a', 'title': ' ' + '字' * 500 + ' '}] * 50,
                'force': ['123AbC-123456A']}
        items, force = jobs.validate_payload(body)
        self.assertEqual(len(items), 50)
        self.assertEqual(items[0], {'code': '123ABC-123456A', 'title': '字' * 500})
        self.assertEqual(force, {'123ABC-123456A'})

    def test_exact_body_size_limit_is_accepted(self):
        raw = json.dumps(self.body('ABC-123')).encode()
        raw += b' ' * (jobs.MAX_BODY - len(raw))
        self.assertEqual(self.post(raw)[0], 202)
        self.assertEqual(self.done()['skipped'], 1)

    def test_http_exact_path_methods_and_content_type(self):
        for method in ('GET', 'POST', 'DELETE', 'PUT', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE'):
            for path in ('/api/title-translate/', '/api/title-translate/extra',
                         '/api/title-translate?x=1', '/api/title-translate?'):
                self.assertEqual(self.request(method, path=path)[0], 404)
            if method not in ('GET', 'POST'):
                self.assertEqual(self.request(method)[0], 405)
        for content_type in (None, 'text/plain', 'invalid'):
            self.assertEqual(self.request('POST', self.body('ABC-123'), content_type=content_type)[0], 415)
            self.assertEqual(self.request(content_type=content_type)[0], 200)

    def test_single_job_check_concurrent_409_and_snapshot_isolation(self):
        self.folder('ABC-123')
        entered = threading.Event()

        def translate(*args, **kwargs):
            entered.set()
            self.release.wait(3)
            return TRANSLATED

        self.translate.side_effect = translate
        self.assertEqual(self.post(self.body('ABC-123'))[0], 202)
        self.assertTrue(entered.wait(3))
        barrier = threading.Barrier(9)
        results = []

        def submit():
            barrier.wait(3)
            results.append(self.post(self.body('ABC-123')))

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait(3)
        for thread in threads:
            thread.join(3)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(status == 409 and state['state'] == 'running' for status, state in results))
        self.assertEqual(self.translate.call_count, 1)
        snapshot = self.job.snapshot()
        snapshot['errors'].append({'code': 'ABC-999', 'kind': 'unknown'})
        self.assertEqual(self.job.snapshot()['errors'], [])
        self.release.set()
        self.done()
        self.assertEqual(self.post(self.body('ABC-124'))[0], 202)
        self.assertEqual(self.done()['errors'], [{'code': 'ABC-124', 'kind': 'no_folder'}])

    def test_running_post_returns_409(self):
        self.folder('ABC-123')
        entered = threading.Event()

        def translate(*args, **kwargs):
            entered.set()
            self.release.wait(3)
            return TRANSLATED

        self.translate.side_effect = translate
        self.assertEqual(self.post(self.body('ABC-123'))[0], 202)
        first_thread = self.job.thread
        try:
            self.assertTrue(entered.wait(3))
            status, state = self.post(self.body('ABC-123'))
            self.assertEqual(status, 409)
            self.assertEqual(state['state'], 'running')
            self.assertEqual(self.translate.call_count, 1)
        finally:
            self.release.set()
            first_thread.join(3)
            self.job.thread.join(3)

    def test_simultaneous_initial_submissions_only_one_is_accepted(self):
        self.folder('ABC-123')
        self.translate.side_effect = lambda *args, **kwargs: (self.release.wait(3), TRANSLATED)[1]
        barrier = threading.Barrier(9)
        results = []

        def submit():
            barrier.wait(3)
            results.append(self.post(self.body('ABC-123'))[0])

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait(3)
        for thread in threads:
            thread.join(3)
        self.assertEqual(sorted(results), [202] + [409] * 7)
        self.release.set()
        self.done()

    def test_restart_marks_running_as_interrupted_once(self):
        saved = jobs.idle_state()
        saved.update(state='running', total=4, created=1, failed=1, started_at=1,
                     errors=[{'code': 'ABC-123', 'kind': 'network'}])
        self.path.write_text(json.dumps(saved))
        reloaded = jobs.TitleTranslateJob(self.media, self.path)
        state = reloaded.snapshot()
        self.assertEqual((state['state'], state['skipped'], state['created'], state['failed']), ('done', 2, 1, 1))
        self.assertEqual(state['errors'], saved['errors'] + [{'code': '', 'kind': 'interrupted'}])
        self.assertEqual(reloaded.snapshot(), state)
        self.assertEqual(reloaded.submit(self.body('ABC-999'))[0], 202)
        reloaded.thread.join(3)
        self.assertFalse(reloaded.thread.is_alive())
        self.assertEqual(jobs.TitleTranslateJob(self.media, self.path).snapshot(), reloaded.snapshot())

    def test_error_kinds_and_abort_stop_further_calls(self):
        cases = [
            ('auth', RuntimeError('invalid api key ' + ORIGINAL)),
            ('quota', RuntimeError('insufficient balance ' + ORIGINAL)),
            ('config', RuntimeError('translation API is not configured ' + ORIGINAL)),
            ('network', TimeoutError(ORIGINAL)),
            ('unknown', RuntimeError(ORIGINAL)),
            ('rejected', None),
            ('no_folder', None),
        ]
        for index, (kind, exception) in enumerate(cases):
            with self.subTest(kind=kind):
                codes = (f'TEST-{index}1', f'TEST-{index}2', f'TEST-{index}3')
                folders = [self.folder(code) for code in codes if kind != 'no_folder' or code != codes[0]]
                self.translate.reset_mock()
                self.translate.side_effect = ([TRANSLATED, TRANSLATED] if kind == 'no_folder'
                                              else [exception if exception else '', TRANSLATED, TRANSLATED])
                status, _ = self.post(self.body(*codes))
                self.assertEqual(status, 202)
                state = self.done()
                abort = kind in ('auth', 'quota', 'config')
                self.assertEqual(self.translate.call_count, 1 if abort else (2 if kind == 'no_folder' else 3))
                self.assertEqual(state['errors'][0], {'code': codes[0], 'kind': kind})
                if abort:
                    self.assertEqual((state['created'], state['skipped'], state['failed']), (0, 2, 1))
                    self.assertEqual(state['errors'][1:], [{'code': code, 'kind': 'aborted'} for code in codes[1:]])
                    self.assertFalse(any(list(folder.glob('*.nfo')) for folder in folders))
                elif kind != 'no_folder':
                    self.assertEqual((state['created'], state['skipped'], state['failed']), (2, 0, 1))
                else:
                    self.assertEqual((state['created'], state['skipped'], state['failed']), (2, 1, 0))

    def test_has_nfo_does_not_translate_or_overwrite_even_when_forced(self):
        folder = self.folder('ABC-123')
        nested = folder / 'nested'
        nested.mkdir()
        nfo = nested / 'metadata.NFO'
        nfo.write_bytes(b'existing metadata')
        for force in ([], ['ABC-123']):
            with self.subTest(force=force):
                self.assertEqual(self.post({**self.body('ABC-123'), 'force': force})[0], 202)
                state = self.done()
                self.assertEqual((state['created'], state['skipped'], state['failed']), (0, 1, 0))
                self.assertEqual(state['errors'], [{'code': 'ABC-123', 'kind': 'has_nfo'}])
                self.translate.assert_not_called()
                self.assertEqual(nfo.read_bytes(), b'existing metadata')
                self.assertEqual(list(folder.rglob('*.nfo')), [])
                self.assertEqual(jobs.TitleTranslateJob(self.media, self.path).snapshot(), state)

    def test_mixed_has_nfo_missing_and_creatable_folders(self):
        existing = self.folder('300MIUM-1395-C')
        nfo = existing / 'metadata.nfo'
        nfo.write_bytes(b'existing metadata')
        pending = self.folder('ABC-123')
        # Existing NFO first must not abort the later translation; both name
        # candidates should match, and all misses share one additional scan.
        with mock.patch.object(jobs, '_codes_with_nfo', wraps=jobs._codes_with_nfo) as scan:
            self.assertEqual(self.post(self.body('300MIUM-1395', 'ABC-124', 'MIUM-1395', 'ABC-123'))[0], 202)
            state = self.done()
        scan.assert_called_once_with(self.media)
        self.assertEqual((state['created'], state['skipped'], state['failed']), (1, 3, 0))
        self.assertEqual(state['errors'], [
            {'code': '300MIUM-1395', 'kind': 'has_nfo'},
            {'code': 'ABC-124', 'kind': 'no_folder'},
            {'code': 'MIUM-1395', 'kind': 'has_nfo'},
        ])
        self.translate.assert_called_once()
        self.assertEqual(nfo.read_bytes(), b'existing metadata')
        self.assertEqual(ET.parse(pending / 'ABC-123.nfo').findtext('title'), f'ABC-123 {TRANSLATED}')
        self.assertEqual(jobs.TitleTranslateJob(self.media, self.path).snapshot(), state)

    def test_missing_nfo_folder_takes_priority_and_avoids_extra_scan(self):
        existing = self.folder('ABC-123-C')
        (existing / 'metadata.nfo').write_bytes(b'existing metadata')
        pending = self.folder('ABC-123')
        with mock.patch.object(jobs, '_codes_with_nfo', wraps=jobs._codes_with_nfo) as scan:
            self.assertEqual(self.post(self.body('ABC-123'))[0], 202)
            state = self.done()
        scan.assert_not_called()
        self.assertEqual((state['created'], state['skipped'], state['failed']), (1, 0, 0))
        self.assertEqual(state['errors'], [])
        self.translate.assert_called_once()
        self.assertTrue((pending / 'ABC-123.nfo').is_file())

    def test_has_nfo_scan_uses_missing_folder_eligibility(self):
        for name in ('thumb', '_ABC-121', 'ABC-122', 'ABC-123', 'ABC-124'):
            folder = self.media / name
            folder.mkdir()
            (folder / 'metadata.nfo').write_bytes(b'existing metadata')
        for name in ('thumb', '_ABC-121'):
            (self.media / name / 'movie.mp4').write_bytes(b'video')
        # A regular file, a directory symlink, no video, and an AppleDouble
        # video entry must all remain no_folder rather than has_nfo.
        (self.media / 'ABC-120').write_bytes(b'not a directory')
        (self.media / 'ABC-123' / '._movie.mp4').write_bytes(b'not video')
        (self.media / 'ABC-124' / 'movie.mp4').mkdir()
        (self.media / 'ABC-125').symlink_to(self.media / 'thumb', target_is_directory=True)
        nested = self.media / 'ABC-126' / 'nested'
        nested.mkdir(parents=True)
        (nested / 'movie.MKV').write_bytes(b'video')
        (nested / '.metadata.NFO').write_bytes(b'existing metadata')
        codes = [f'ABC-{number}' for number in range(120, 127)]
        self.assertEqual(jobs._codes_with_nfo(self.media), {'ABC-126'})
        self.assertEqual(self.post(self.body(*codes))[0], 202)
        state = self.done()
        self.assertEqual((state['created'], state['skipped'], state['failed']), (0, 7, 0))
        self.assertEqual(state['errors'], [
            {'code': code, 'kind': 'has_nfo' if code == 'ABC-126' else 'no_folder'}
            for code in codes
        ])
        self.translate.assert_not_called()

    def test_force_short_title_and_original_unforced_behavior(self):
        for force in (False, True):
            with self.subTest(force=force):
                folder = self.folder('NIMA-083' if not force else 'NIMA-083-C')
                # Only the new folder is eligible in the second job.
                body = {'items': [{'code': 'NIMA-083', 'title': SHORT}]}
                if force:
                    body['force'] = ['nima-083']
                self.translate.reset_mock()
                self.assertEqual(self.post(body)[0], 202)
                self.assertEqual(self.done()['created'], 1)
                root = ET.parse(folder / 'NIMA-083.nfo').getroot()
                if force:
                    self.translate.assert_called_once()
                    self.assertEqual(root.findtext('title'), f'NIMA-083 {TRANSLATED}')
                    self.assertEqual(root.findtext('originaltitle'), SHORT)
                else:
                    self.translate.assert_not_called()
                    self.assertEqual(root.findtext('title'), SHORT)
                    self.assertIsNone(root.find('originaltitle'))

    def test_numeric_prefix_mapping_and_no_nfo_overwrite_race(self):
        folder = self.folder('300MIUM-1395-C')
        self.assertEqual(self.post(self.body('300MIUM-1395'))[0], 202)
        self.assertEqual(self.done()['created'], 1)
        self.assertTrue((folder / '300MIUM-1395.nfo').exists())
        folder = self.folder('ABC-123')
        def translate(*args, **kwargs):
            (folder / 'other.NFO').write_bytes(b'concurrent metadata')
            return TRANSLATED
        self.translate.side_effect = translate
        self.assertEqual(self.post(self.body('ABC-123'))[0], 202)
        state = self.done()
        self.assertEqual((state['created'], state['skipped'], state['failed']), (0, 1, 0))
        self.assertFalse((folder / 'ABC-123.nfo').exists())
        self.assertEqual((folder / 'other.NFO').read_bytes(), b'concurrent metadata')

    def test_classify_error_table(self):
        cases = [
            *[(HTTPError('https://example.test', code, ORIGINAL, {}, None), kind)
              for code, kind in ((401, 'auth'), (403, 'auth'), (402, 'quota'), (429, 'quota'),
                                 (500, 'network'), (503, 'network'))],
            (URLError(ORIGINAL), 'network'), (TimeoutError(ORIGINAL), 'network'),
            (ConnectionError(ORIGINAL), 'network'),
            *[(RuntimeError(message), kind) for message, kind in (
                ('HTTP Error 403', 'auth'), ('invalid api key', 'auth'), ('unauthorized', 'auth'),
                ('HTTP 429', 'quota'), ('insufficient', 'quota'), ('quota', 'quota'),
                ('rate limit', 'quota'), ('balance', 'quota'), ('HTTP 502', 'network'),
                ('connection refused', 'network'), ('DNS failure', 'network'),
                ('Name or service not known', 'network'), ('timed out', 'network'),
                ('translation API is not configured', 'config'), (ORIGINAL, 'unknown'))],
        ]
        for exception, kind in cases:
            with self.subTest(exception_type=type(exception).__name__, kind=kind):
                self.assertEqual(jobs.classify_error(exception), kind)

    def test_exceptions_never_leak_title_or_translation(self):
        self.folder('ABC-123')
        self.translate.side_effect = RuntimeError(ORIGINAL + TRANSLATED)
        self.post(self.body('ABC-123'))
        state = self.done()
        self.assertEqual(state['errors'], [{'code': 'ABC-123', 'kind': 'unknown'}])
        self.assertEqual(self.request(), (200, state))


if __name__ == '__main__':
    unittest.main()
