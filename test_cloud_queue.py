import contextlib
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import queue_api as api
from queue_store import append_unique, pop_first_matching, read_json, read_queue, set_download_target, write_json, write_queue


class CloudQueueTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(tempfile.TemporaryDirectory())
        for name in ['QUEUE_PATH', 'STATE_PATH', 'DOWNLOAD_TARGETS_PATH', 'RETRY_PATH', 'FAILED_QUEUE_JSON_PATH', 'CURRENT_PATH', 'LOCK_PATH']:
            self.stack.enter_context(mock.patch.object(api, name, os.path.join(self.root, name)))
        self.stack.enter_context(mock.patch.dict(os.environ, {'QUEUE_PATH': api.QUEUE_PATH}))
        self.stack.enter_context(mock.patch.object(api, 'log_write'))
        self.stack.enter_context(mock.patch.object(api, 'qb_api', side_effect=AssertionError('cloud must not access qB')))
        self.stack.enter_context(mock.patch('src.p115_offline.load_config', return_value={'enabled': True}))
        self.stack.enter_context(mock.patch('src.p115_offline.probe_cached', return_value=(True, 'ok')))
        self.resolve = self.stack.enter_context(mock.patch('download_source.resolve_download_source', return_value={'magnet': 'magnet:?xt=urn:btih:TEST'}))
        self.submit = self.stack.enter_context(mock.patch('src.p115_offline.submit_magnet', return_value=(True, 'accepted', {})))
        write_queue(api.CURRENT_PATH, ['AAA-001'])
        with open(api.LOCK_PATH, 'w') as handle:
            handle.write('1')
        write_json(api.STATE_PATH, [{'code': 'BBB-002', 'target': '115', 'status': 'queued', 'added_at': 123}])
        set_download_target(api.DOWNLOAD_TARGETS_PATH, 'BBB-002', '115')
        write_queue(api.QUEUE_PATH, ['AAA-001', 'BBB-002', 'CCC-003'])

    def test_submits_cloud_while_local_download_remains_locked(self):
        self.assertTrue(api.process_cloud_once())
        self.submit.assert_called_once()
        self.assertEqual(read_queue(api.QUEUE_PATH), ['AAA-001', 'CCC-003'])
        self.assertEqual(read_queue(api.CURRENT_PATH), ['AAA-001'])
        with open(api.LOCK_PATH) as handle:
            self.assertEqual(handle.read(), '1')
        self.assertEqual(read_json(api.STATE_PATH, [])[0]['status'], 'submitted_to_115')

    def test_deleted_or_replaced_job_cannot_submit_or_resurrect(self):
        def replace(*args, **kwargs):
            write_json(api.STATE_PATH, [{'code': 'BBB-002', 'target': '115', 'status': 'queued', 'added_at': 456}])
            return {'magnet': 'magnet:?xt=urn:btih:TEST'}
        self.resolve.side_effect = replace
        self.assertTrue(api.process_cloud_once())
        self.submit.assert_not_called()
        self.assertEqual(read_json(api.STATE_PATH, [])[0]['added_at'], 456)
        self.assertNotIn('BBB-002', read_queue(api.QUEUE_PATH))

    def test_rejection_keeps_channel_for_retries_and_records_real_reason(self):
        self.submit.return_value = (False, '115 拒绝：空间不足', {})
        for _ in range(3):
            api.process_cloud_once()
        self.assertEqual(read_json(api.STATE_PATH, [])[0]['status'], 'failed')
        self.assertIn('空间不足', read_json(api.FAILED_QUEUE_JSON_PATH, [])[0]['reason'])
        self.assertNotIn('BBB-002', read_queue(api.QUEUE_PATH))

    def test_no_magnet_does_not_submit_online_stream_to_cloud(self):
        self.resolve.return_value = {'source': 'online_stream', 'magnet': ''}
        api.process_cloud_once()
        self.submit.assert_not_called()
        self.assertIn('无可用磁链', read_json(api.STATE_PATH, [])[0]['message'])

    def test_network_wait_does_not_hold_queue_state_lock(self):
        entered, release = threading.Event(), threading.Event()
        def blocked_submit(*args):
            entered.set()
            release.wait(3)
            return True, 'ok', {}
        self.submit.side_effect = blocked_submit
        thread = threading.Thread(target=api.process_cloud_once)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            with api.queue_state_critical('test.new.add'):
                append_unique(api.QUEUE_PATH, 'DDD-004')
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIn('DDD-004', read_queue(api.QUEUE_PATH))
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_two_consumers_preserve_other_lane_order(self):
        def pop_cloud():
            return pop_first_matching(api.QUEUE_PATH, lambda c: c == 'BBB-002')
        results = []
        threads = [threading.Thread(target=lambda: results.append(pop_cloud())) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertEqual(results.count('BBB-002'), 1)
        self.assertEqual(read_queue(api.QUEUE_PATH), ['AAA-001', 'CCC-003'])

    def test_growing_ts_duration_probe_is_bounded_and_cached(self):
        path = os.path.join(self.root, 'growing.ts')
        with mock.patch.object(api.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffprobe', 2)) as run:
            self.assertIsNone(api.get_ts_duration_seconds(path))
            self.assertIsNone(api.get_ts_duration_seconds(path))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs['timeout'], 2)
