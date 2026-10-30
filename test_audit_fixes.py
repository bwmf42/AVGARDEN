#!/usr/bin/env python3
"""Tests for the 20261031 audit fixes: cover refresh, worker magnet/backoff, build identity."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src.weekly import artwork

ROOT = os.path.dirname(os.path.abspath(__file__))


_WORKER = []


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def load_worker():
    """Import worker.py once without its container log sink, leaving sys.modules untouched."""
    if _WORKER:
        return _WORKER[0]
    before = set(sys.modules)
    module = None
    try:
        from loguru import logger
        with mock.patch.object(type(logger), "add", return_value=0):
            import worker as module
    except Exception:
        module = None
    for name in set(sys.modules) - before:
        path = getattr(sys.modules.get(name), "__file__", None) or ""
        if path.startswith(ROOT + os.sep):
            sys.modules.pop(name, None)
    _WORKER.append(module)
    return module


class CoverRefreshTest(unittest.TestCase):
    def test_local_cover_is_never_passed_to_download(self):
        artwork._NO_REMOTE_COVER_LOGGED.clear()
        item = {"id": "SILK-2071", "cover": "/file/__weekly__/SILK-2071/SILK-2071-cover.jpg"}
        with mock.patch.object(artwork, "prefer_urls", return_value=("", [], "")), \
                mock.patch.object(artwork.javbus, "cover_needs_refresh", return_value=True), \
                mock.patch.object(artwork.javbus, "download_cover") as dl:
            artwork.download_for_item(item, "/tmp/x", cover_only=True)
            artwork.download_for_item(item, "/tmp/x", cover_only=True)
        dl.assert_not_called()
        self.assertTrue(item["cover"].startswith("/file/"))
        self.assertEqual(artwork._NO_REMOTE_COVER_LOGGED, {"SILK-2071"})

    def test_remote_source_still_downloads(self):
        item = {"id": "SILK-2071", "cover": "/file/a.jpg"}
        with mock.patch.object(artwork, "prefer_urls", return_value=("https://x/c.jpg", [], "dmm")), \
                mock.patch.object(artwork.javbus, "cover_needs_refresh", return_value=True), \
                mock.patch.object(artwork.javbus, "download_cover", return_value="/file/new.jpg") as dl:
            artwork.download_for_item(item, "/tmp/x", cover_only=True)
        dl.assert_called_once()
        self.assertEqual(item["cover"], "/file/new.jpg")


@unittest.skipUnless(load_worker() is not None, "worker module cannot be imported here")
class WorkerAuditTest(unittest.TestCase):
    def setUp(self):
        self.worker = load_worker()
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "__weekly__"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_weekly(self, items):
        with open(os.path.join(self.tmp, "__weekly__", "weekly.json"), "w", encoding="utf-8") as f:
            json.dump(items, f)

    def run_get(self, avid):
        with mock.patch.object(self.worker, "save_path", self.tmp), mock.patch(
            "download_source.resolve_download_source",
            return_value={"magnet": "magnet:?xt=urn:btih:resolved", "source": "x"},
        ) as resolve:
            return self.worker.get_magnet_from_weekly(avid), resolve

    def test_weekly_magnet_skips_resolver(self):
        self.write_weekly([{"id": "abc-123", "magnet": " magnet:?xt=urn:btih:weekly "}])
        magnet, resolve = self.run_get("ABC-123")
        self.assertEqual(magnet, "magnet:?xt=urn:btih:weekly")
        resolve.assert_not_called()

    def test_no_magnet_or_missing_uses_resolver(self):
        self.write_weekly([{"id": "ABC-123", "magnet": ""}])
        for avid in ("ABC-123", "ZZZ-999"):
            magnet, resolve = self.run_get(avid)
            self.assertEqual(magnet, "magnet:?xt=urn:btih:resolved")
            resolve.assert_called_once()

    def test_missing_weekly_file_uses_resolver(self):
        magnet, resolve = self.run_get("ABC-123")
        resolve.assert_called_once()

    def test_loop_error_backoff(self):
        d = self.worker.next_loop_error_delay
        self.assertEqual([d(n) for n in (1, 2, 3, 4)], [30, 60, 120, 240])
        self.assertEqual(d(5), 480)
        self.assertEqual(d(6), 600)
        self.assertEqual(d(50), 600)


class BuildIdentityTest(unittest.TestCase):
    def make_tree(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "tools"))
        shutil.copy(os.path.join(ROOT, "tools", "build_identity.sh"), os.path.join(tmp, "tools"))
        for d in ("src", "backend", "frontend/src"):
            os.makedirs(os.path.join(tmp, d))
        open(os.path.join(tmp, "VERSION"), "w").write("1.0\n")
        open(os.path.join(tmp, "src", "a.py"), "w").write("x=1\n")
        open(os.path.join(tmp, "backend", "m.go"), "w").write("package main\n")
        return tmp

    def run_script(self, tmp):
        return subprocess.run(["bash", os.path.join(tmp, "tools", "build_identity.sh")],
                              capture_output=True, text=True)

    def test_readable_tree_succeeds(self):
        r = self.run_script(self.make_tree())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["tree_hash"])

    @unittest.skipIf(os.geteuid() == 0, "root ignores permissions")
    def test_unreadable_dir_fails_with_path(self):
        tmp = self.make_tree()
        bad = os.path.join(tmp, "frontend", "src")
        os.chmod(bad, 0)
        self.addCleanup(os.chmod, bad, stat.S_IRWXU)
        r = self.run_script(tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("frontend/src", r.stderr)
        self.assertEqual(r.stdout.strip(), "")


class DockerfileIdentityTest(unittest.TestCase):
    def test_server_image_bakes_build_info(self):
        text = read("Dockerfile.server")
        self.assertIn("COPY VERSION BUILD_INFO.jso[n] /app/", text)
        self.assertNotIn('"version":"dev"', text)
        ignore = read(".dockerignore")
        self.assertNotIn("BUILD_INFO.json", ignore.split())
        worker_ignore = read("Dockerfile.worker.dockerignore")
        self.assertIn("cfg/configs.json", worker_ignore)


if __name__ == "__main__":
    unittest.main()
