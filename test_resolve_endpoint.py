import http.client
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import download_source
import queue_api


REAL_RESOLVE = download_source.resolve_download_source


class ResolveEndpointTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.cache_path = os.path.join(root, "download_source_cache.json")
        self.before = {}
        for name, filename, content in (
            ("QUEUE_PATH", "download_queue.txt", b"SSIS-951\n"),
            ("STATE_PATH", "queue_state.json", b'[{"code":"SSIS-951","status":"queued"}]\n'),
            ("DOWNLOAD_TARGETS_PATH", "download_targets.json", b'{"SSIS-951":"115"}\n'),
        ):
            path = Path(root, filename)
            path.write_bytes(content)
            self.before[path] = content
            self.stack.enter_context(patch.object(queue_api, name, str(path)))
        self.stack.enter_context(patch.dict(os.environ, {"QUEUE_PATH": queue_api.QUEUE_PATH}))
        self.stack.enter_context(patch.object(queue_api, "ONLINE_PROXY", None))
        self.log = self.stack.enter_context(patch.object(queue_api, "log"))
        self.resolve = self.stack.enter_context(patch(
            "download_source.resolve_download_source",
            return_value={"kind": "stream", "source": "online_stream"},
        ))
        self.mutations = []
        for name in ("append_unique", "update_state", "request_cancel", "qb_api", "qb_request",
                     "qb_remove_code", "process_cloud_once"):
            self.mutations.append(self.stack.enter_context(patch.object(
                queue_api, name, side_effect=AssertionError(f"resolve must not call {name}"),
            )))

    def request(self, path):
        # 通过真实 HTTP 解析器执行处理器，不占用本地监听端口。
        connection = Mock()
        connection.makefile.return_value = io.BytesIO((
            f"GET {path} HTTP/1.1\r\nHost: localhost\r\n"
            "X-Request-ID: resolve-unit-1\r\nConnection: close\r\n\r\n"
        ).encode("ascii"))
        output = io.BytesIO()
        connection.sendall.side_effect = output.write
        queue_api.QueueHandler(connection, ("127.0.0.1", 0), None)
        response_socket = Mock()
        response_socket.makefile.return_value = io.BytesIO(output.getvalue())
        response = http.client.HTTPResponse(response_socket)
        response.begin()
        with response:
            status, payload = response.status, json.loads(response.read())
            self.assertEqual(response.headers["X-Request-ID"], "resolve-unit-1")
        for path, content in self.before.items():
            self.assertEqual(path.read_bytes(), content, f"modified {path.name}")
        for mutation in self.mutations:
            mutation.assert_not_called()
        return status, payload

    def test_magnet_returns_only_public_source_fields(self):
        self.resolve.return_value = {
            "kind": "magnet", "source": "plwt_chinese",
            "magnet": "magnet:?xt=urn:btih:TEST", "title": "START-653 中文字幕",
            "size_gib": 7.5, "published_at": "2026-10-23",
            "forum_url": "https://forum.test/thread-1-1-1.html", "resolved_at": 123,
        }
        status, payload = self.request("/api/resolve/START-653")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "code": "START-653", "kind": "magnet", "source": "plwt_chinese",
            "magnet": "magnet:?xt=urn:btih:TEST", "title": "START-653 中文字幕",
            "size_gib": 7.5, "published_at": "2026-10-23",
            "forum_url": "https://forum.test/thread-1-1-1.html",
        })
        self.resolve.assert_called_once_with("START-653", proxy=None)

    def test_stream_returns_empty_magnet_and_optional_defaults(self):
        status, payload = self.request("/api/resolve/START-653")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "code": "START-653", "kind": "stream", "source": "online_stream",
            "magnet": "", "title": "", "size_gib": 0,
            "published_at": "", "forum_url": "",
        })

    def test_url_decodes_and_normalizes_before_resolving(self):
        for raw, expected in (("start%36%35%33v", "START-653"), ("300mium1395", "300MIUM-1395")):
            with self.subTest(raw=raw):
                status, payload = self.request("/api/resolve/" + raw)
                self.assertEqual(status, 200)
                self.assertEqual(payload["code"], expected)
                self.resolve.assert_called_with(expected, proxy=None)

    def test_invalid_codes_do_not_resolve(self):
        for raw in ("", "not-a-code", "..%2FSTART-653", "START-653%2F", "START-653/", "START-653%3Fextra", "%00"):
            with self.subTest(raw=raw):
                self.assertEqual(self.request("/api/resolve/" + raw), (400, {"error": "invalid code"}))
        self.resolve.assert_not_called()

    def test_exception_returns_sanitized_gateway_error(self):
        self.resolve.side_effect = RuntimeError("private proxy/cookie detail")
        self.assertEqual(self.request("/api/resolve/START-653"), (502, {"error": "resolve failed"}))
        self.log.assert_called_once_with("Download source resolve failed for START-653")

    def test_existing_cached_result_never_searches(self):
        with patch.object(download_source, "SOURCE_CACHE_PATH", self.cache_path):
            download_source.save_cached_source("START-653", {"kind": "stream", "source": "online_stream"})
            # 使用真实缓存读取，但所有外部搜索仍被禁止。
            with patch("download_source.resolve_download_source", wraps=REAL_RESOLVE), patch(
                "download_source._plwt_search_slot", side_effect=AssertionError("cache hit must not search"),
            ) as slot:
                first = self.request("/api/resolve/START-653")
                second = self.request("/api/resolve/start653")
            self.assertEqual(first, second)
            self.assertEqual(first[0], 200)
            slot.assert_not_called()

    def test_resolve_actresses_route_is_unchanged(self):
        item = {"code": "START-653", "actresses": ["Test Actress"]}
        with patch.object(queue_api, "resolve_actresses_remote", return_value=(item, "")) as actresses:
            self.assertEqual(self.request("/api/resolve-actresses/START-653"), (200, item))
        actresses.assert_called_once_with("START-653")
        self.resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
