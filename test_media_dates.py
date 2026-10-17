import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import media_dates
from tools.maintenance.media_dates import plan, apply, rollback


class MediaDatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.directory = Path(self.root, 'ABC-123')
        self.directory.mkdir()
        self.video = self.directory / 'ABC-123.mp4'
        self.video.write_bytes(b'unchanged video')
        self.env = patch.dict(os.environ, {'MEDIA_DATES_PATH': self.root + '/state/dates.json'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_download_anchor_is_immutable_and_video_is_untouched(self):
        original = self.video.stat()
        media_dates.register_download(self.root, 'ABC-123', 'ABC-123', 1_600_000_000_000_000_000)
        media_dates.register_download(self.root, 'ABC-123', 'ABC-123', 1_700_000_000_000_000_000)
        (self.directory / 'new.nfo').write_text('metadata')
        media_dates.restore_registered(self.root)
        self.assertEqual(self.directory.stat().st_mtime_ns, 1_600_000_000_000_000_000)
        self.assertEqual(self.video.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(self.video.read_bytes(), b'unchanged video')

    def test_scrape_failure_restores_unregistered_directory(self):
        before = self.directory.stat()
        with self.assertRaises(RuntimeError):
            with media_dates.preserve_directory(self.directory):
                (self.directory / 'poster.jpg').write_bytes(b'image')
                raise RuntimeError('network failure')
        self.assertEqual(self.directory.stat().st_mtime_ns, before.st_mtime_ns)

    def test_symlink_and_replaced_inode_are_skipped(self):
        media_dates.register_download(self.root, 'ABC-123', 'ABC-123', 1_600_000_000_000_000_000)
        self.directory.rename(Path(self.root, 'old'))
        self.directory.symlink_to(Path(self.root, 'old'), target_is_directory=True)
        self.assertEqual(media_dates.restore_registered(self.root), [])
        self.directory.unlink()
        self.directory.mkdir()
        self.assertEqual(media_dates.restore_registered(self.root), [])

    def proposal(self):
        return [{'folder': 'ABC-123', 'code': 'ABC-123', 'date': '2020-06-15T12:00:00+08:00',
                 'basis': 'release_date', 'source': 'https://example.com/exact-product'}]

    def test_apply_and_rollback_preserve_files_and_unrelated_anchors(self):
        before = self.directory.stat()
        manifest = plan(self.root, self.proposal())
        result_path = self.root + '/result.json'
        apply(manifest, result_path)
        self.assertNotEqual(self.directory.stat().st_mtime_ns, before.st_mtime_ns)
        Path(self.root, 'DEF-456').mkdir()
        media_dates.register_download(self.root, 'DEF-456', 'DEF-456')
        rollback(result_path)
        self.assertEqual(self.directory.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(list(media_dates._load()['entries']), ['DEF-456'])
        self.assertEqual(self.video.read_bytes(), b'unchanged video')

    def test_manifest_tampering_and_changed_contents_fail_before_writes(self):
        manifest = plan(self.root, self.proposal())
        altered = json.loads(json.dumps(manifest))
        altered['entries'][0]['timestamp_ns'] += 1
        with self.assertRaises(ValueError):
            apply(altered, self.root + '/result.json')
        (self.directory / 'new.nfo').write_text('changed')
        with self.assertRaises(ValueError):
            apply(manifest, self.root + '/result.json')
        self.assertFalse(Path(media_dates.registry_path()).exists())

    def test_reserved_and_traversal_directories_are_rejected(self):
        for folder in ['../outside', '__weekly__', '.hidden', '']:
            self.assertIsNone(media_dates._directory(self.root, folder))

    def test_merge_failure_still_restores_anchor(self):
        media_dates.register_download(self.root, 'ABC-123', 'ABC-123', 1_600_000_000_000_000_000)
        with patch.dict(globals(), {'SAVE_PATH': self.root}):
            @media_dates.preserve_library_dates
            def merge():
                (self.directory / 'chinese.mp4').write_bytes(b'new video')
                raise RuntimeError('merge failed')
            with self.assertRaises(RuntimeError):
                merge()
        self.assertEqual(self.directory.stat().st_mtime_ns, 1_600_000_000_000_000_000)

    def test_reads_do_not_trigger_writes_and_reapply_keeps_backup(self):
        manifest = plan(self.root, self.proposal())
        result_path = self.root + '/result.json'
        apply(manifest, result_path)
        backup = Path(result_path).read_bytes()
        stamp = self.directory.stat().st_mtime_ns
        os.utime(self.directory, ns=(stamp + 10_000_000_000, stamp))
        self.assertEqual(media_dates.restore_registered(self.root), [])
        with self.assertRaises(ValueError):
            apply(manifest, result_path)
        self.assertEqual(Path(result_path).read_bytes(), backup)


if __name__ == '__main__':
    unittest.main()
