import contextlib
import fnmatch
import io
import json
import os
import re
import socket
from pathlib import Path
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

import heal_runner
import queue_api
import translate_settings as settings
import weekly_backfill_details as backfill
import weekly_updater as weekly


SECRET = "fake-relay-unique-Q8z7"
DEEP_SECRET = "fake-deepseek-unique-K6x5"


class Response:
    def __init__(self, reason="stop", content="这是完整的中文故事标题"):
        choice = {"message": {"content": content}}
        if reason != "missing":
            choice["finish_reason"] = reason
        self.body = json.dumps({"choices": [choice]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class WireSocket:
    """Run the actual HTTP parser/dispatch without opening a network socket."""
    def __init__(self, wire):
        self.input = io.BytesIO(wire)
        self.output = bytearray()

    def settimeout(self, timeout):
        self.timeout = timeout

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class TranslateSettingsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(tmp) / "settings.json"
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "TRANSLATE_SETTINGS_PATH": str(self.path),
            "TRANSLATE_API_BASE": "https://env.example/v1",
            "TRANSLATE_API_KEY": SECRET,
            "TRANSLATE_MODEL": "env-model",
            "DEEPSEEK_API_KEY": DEEP_SECRET,
            "TRANSLATE_ALLOW_PRIVATE_BASE": "",
        }))
        for module in (weekly, heal_runner):
            for name, value in (("TRANSLATE_API_BASE", "https://env.example/v1"),
                                ("TRANSLATE_API_KEY", SECRET),
                                ("TRANSLATE_MODEL", "env-model"), ("DS_API_KEY", "")):
                self.stack.enter_context(mock.patch.object(module, name, value))
        self.logs = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.logs))
        self.stack.enter_context(contextlib.redirect_stderr(self.logs))

    def request(self, method="GET", body=None, content_type="application/json", length=None, slow=False, transfer_encoding=None):
        raw = body if isinstance(body, bytes) else (b"" if body is None else json.dumps(body).encode())
        headers = f"Content-Length: {len(raw) if length is None else length}\r\n"
        if content_type is not None:
            headers += f"Content-Type: {content_type}\r\n"
        if transfer_encoding is not None:
            headers += f"Transfer-Encoding: {transfer_encoding}\r\n"
        wire = (f"{method} /api/translate-settings HTTP/1.1\r\nHost: localhost\r\n"
                f"{headers}\r\n").encode() + raw
        sock = WireSocket(wire)
        if slow:
            def read(size=-1):
                self.assertEqual(sock.timeout, 10)
                raise socket.timeout("fake slow body")
            sock.input.read = read
        queue_api.QueueHandler(sock, ("127.0.0.1", 12345), mock.Mock())
        head, payload = bytes(sock.output).split(b"\r\n\r\n", 1)
        return int(head.split()[1]), json.loads(payload), payload.decode()

    def seed(self):
        settings.save_settings({"base": "https://file.example/v1/", "key": SECRET, "model": "file-model"})

    def test_public_view_never_exposes_secrets(self):
        for file_exists in (False, True):
            if file_exists:
                self.seed()
            status, data, raw = self.request()
            self.assertEqual(status, 200)
            fields = {"base", "model", "key_set", "source", "deepseek_set", "complete", "mode", "relay_enabled"}
            self.assertEqual(set(data), fields if file_exists else fields | {"hint"})
            self.assertEqual(data["complete"], file_exists)
            self.assertTrue(data["key_set"])
            self.assertTrue(data["deepseek_set"])
            self.assertEqual(data["source"], "file" if file_exists else "env")
            for secret in (SECRET, SECRET[-4:], DEEP_SECRET, DEEP_SECRET[-4:]):
                self.assertNotIn(secret, raw)

    def test_no_environment_config(self):
        with mock.patch.dict(os.environ, {"TRANSLATE_API_BASE": "", "TRANSLATE_API_KEY": "", "DEEPSEEK_API_KEY": ""}):
            data = self.request()[1]
            self.assertEqual(data["source"], "none")
            self.assertFalse(data["key_set"])
            self.assertFalse(data["deepseek_set"])
            # Legacy key-only drafts remain visible but do not become effective.
            self.path.write_text(json.dumps({"key": SECRET}))
            self.assertTrue(self.request()[1]["key_set"])
            self.assertFalse(self.request()[1]["complete"])
            self.assertTrue(self.request()[1]["hint"])
            self.assertFalse(settings.effective_relay()[0])

    def test_candidates_file_fallback_and_permissions(self):
        self.assertEqual(weekly.translation_provider_candidates()[0][1:],
                         ("https://env.example/v1", SECRET, "env-model"))
        self.seed()
        expected = ("https://file.example/v1", SECRET, "file-model")
        self.assertEqual(settings.effective_relay(), expected)
        self.assertEqual(weekly.translation_provider_candidates()[0][1:], expected)
        self.assertEqual(weekly.translation_provider(), ("relay", "file-model"))
        self.assertEqual(heal_runner._translation_probe_candidates()[0][1:], expected)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        settings.save_settings({"key": ""})
        self.assertEqual(weekly.translation_provider_candidates()[0][1], "https://env.example/v1")
        self.path.write_text('{"base":"https://partial.example"}')
        self.assertEqual(settings.effective_relay()[0], "https://env.example/v1")
        self.path.write_text('{broken')
        self.assertEqual(settings.effective_relay()[0], "https://env.example/v1")

    def test_base_change_clears_key(self):
        # Also test an environment-only starting point.
        for saved in (False, True):
            if saved:
                self.seed()
            status, data, _ = self.request("POST", {"base": "https://new.example/v1"})
            self.assertEqual(status, 200)
            self.assertFalse(data["key_set"])
            self.assertEqual(json.loads(self.path.read_text())["key"], "")
            self.assertEqual(data["base"], "https://new.example/v1")
            # Incomplete file falls back to the old env address, never new+old key.
            self.assertEqual(settings.effective_relay()[0], "https://env.example/v1")

    def test_partial_updates_and_clear(self):
        self.seed()
        for changes in ({"model": "new-model"}, {"base": "https://file.example/v1/"}):
            self.assertTrue(self.request("POST", changes)[1]["key_set"])
            self.assertEqual(settings.effective_relay()[1], SECRET)
        new_key = "replacement-fake-secret"
        self.assertTrue(self.request("POST", {"base": "https://new.example", "key": new_key})[1]["key_set"])
        self.assertEqual(settings.effective_relay()[1], new_key)
        self.assertFalse(self.request("POST", {"key": ""})[1]["key_set"])

    def test_key_requires_base_in_same_request(self):
        self.assertEqual(self.request("POST", {"base": "https://evil.example"})[0], 200)
        before = self.path.read_bytes()
        status, data, raw = self.request("POST", {"key": "adminkey-REAL1234"})
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "保存 API Key 时必须同时提交 Base URL，确保密钥发往你看到的地址")
        self.assertNotIn("adminkey-REAL1234", raw)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(settings.effective_relay(), ("https://env.example/v1", SECRET, "env-model"))

    def test_public_fields_are_not_a_secret_suffix_oracle(self):
        base = "https://a.example/" + DEEP_SECRET[-4:]
        model = "model-" + SECRET[-4:]
        status, data, raw = self.request("POST", {"base": base, "model": model})
        self.assertEqual(status, 200)
        self.assertEqual(data["base"], base)
        self.assertEqual(data["model"], model)
        self.assertEqual(self.request()[1]["base"], base)
        for secret in (SECRET, DEEP_SECRET):
            self.assertNotIn(secret, raw)
        self.assertEqual(settings.redact_credentials(base, [DEEP_SECRET]), base)
        self.assertEqual(settings.redact_credentials("Bearer " + SECRET, [SECRET]), "Bearer [已隐藏]")

    def test_model_only_does_not_persist_environment_credentials(self):
        status, data, _ = self.request("POST", {"model": "x"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.path.read_text()), {"model": "x"})
        self.assertNotIn(SECRET, self.path.read_text())
        self.assertFalse(data["complete"])
        with mock.patch.dict(os.environ, {"TRANSLATE_API_KEY": "rotated-fake-key"}):
            self.assertEqual(settings.effective_relay()[1], "rotated-fake-key")

    def test_complete_and_hint_follow_saved_draft(self):
        for method, body in (("POST", {"base": "https://draft.example"}), ("GET", None)):
            data = self.request(method, body)[1]
            self.assertFalse(data["complete"])
            self.assertTrue(data["hint"])
            self.assertEqual(settings.effective_relay()[0], "https://env.example/v1")
        status, data, raw = self.request("POST", {"base": "https://draft.example", "key": SECRET})
        self.assertEqual(status, 200)
        self.assertTrue(data["complete"])
        self.assertNotIn("hint", data)
        self.assertNotIn(SECRET, raw)
        self.assertTrue(self.request()[1]["complete"])
        self.assertEqual(settings.effective_relay()[:2], ("https://draft.example", SECRET))
        self.assertFalse(self.request("POST", {"key": ""})[1]["complete"])
        self.assertFalse(self.request()[1]["complete"])

    def test_base_validation_without_dns(self):
        rejected = ("https://x?", "https://x?q=1", "https://x#", "https://x#part",
                    "http://localhost", "http://LOCALHOST.", "http://127.0.0.1:31473/x",
                    "http://169.254.169.254", "http://10.0.0.5", "http://192.168.5.17",
                    "http://172.16.0.1", "http://0.0.0.0", "http://[::]", "http://[::1]",
                    "http://[fe80::1]", "http://[fc00::1]", "http://[::ffff:127.0.0.1]")
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")) as dns:
            for base in rejected:
                with self.subTest(base=base):
                    self.assertEqual(self.request("POST", {"base": base})[0], 400)
            self.assertEqual(self.request("POST", {"base": "https://code.77code.fun/v1"})[0], 200)
            for allow in ("1", "true"):
                with mock.patch.dict(os.environ, {"TRANSLATE_ALLOW_PRIVATE_BASE": allow}):
                    self.assertEqual(self.request("POST", {"base": "http://192.168.5.17"})[0], 200)
                    self.assertEqual(self.request("POST", {"base": "http://localhost"})[0], 200)
                    self.assertEqual(self.request("POST", {"base": "http://localhost?q=1"})[0], 400)
            dns.assert_not_called()

    def test_body_read_timeout(self):
        status, data, _ = self.request("POST", {"model": "x"}, slow=True)
        self.assertEqual(status, 408)
        self.assertIn("超时", data["error"])
        self.assertFalse(self.path.exists())

    def test_redirects_never_forward_authorization(self):
        handler = settings.NoRedirectHandler()
        for method in ("GET", "POST"):
            request = urllib.request.Request("https://relay.example/v1", method=method,
                                             headers={"Authorization": "Bearer " + SECRET})
            for code in (301, 302, 303, 307, 308):
                with self.subTest(method=method, code=code):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        handler.redirect_request(request, None, code, "redirect", {}, "https://evil.example")
                    self.assertEqual(raised.exception.code, code)
                    self.assertNotIn(SECRET, str(raised.exception))

    def test_translation_call_sites_use_no_redirect_opener(self):
        with mock.patch.object(settings.urllib.request, "build_opener") as build:
            opener = build.return_value
            opener.open.return_value = Response()
            weekly._chat_completion("https://relay.example/v1", SECRET, "model", [])
            self.assertTrue(heal_runner.probe_translation()[0])
            with mock.patch.object(backfill, "DS_API_KEY", ""):
                self.assertTrue(backfill.translate_title({"id": "TEST-001", "title": "日本語の物語タイトル"}))
            self.assertEqual(build.call_count, 3)
            for call in build.call_args_list:
                self.assertIsInstance(call.args[0], settings.NoRedirectHandler)
            self.assertEqual(opener.open.call_count, 3)
            for call in opener.open.call_args_list:
                self.assertEqual(call.args[0].get_header("Authorization"), "Bearer " + SECRET)
            # DeepSeek fixed endpoints use the same protected transport.
            with mock.patch.object(weekly, "DS_API_KEY", DEEP_SECRET):
                weekly._deepseek_chat([])
            self.assertEqual(opener.open.call_args.args[0].full_url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"), "Bearer " + DEEP_SECRET)
            with mock.patch.object(heal_runner, "TRANSLATE_API_KEY", ""), \
                 mock.patch.object(heal_runner, "DS_API_KEY", DEEP_SECRET):
                self.assertTrue(heal_runner.probe_translation()[0])
            self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"), "Bearer " + DEEP_SECRET)

    def test_redirect_status_is_a_failure_at_call_sites(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), \
                 mock.patch.object(settings.urllib.request.OpenerDirector, "open",
                                   side_effect=urllib.error.HTTPError("", code, "redirect refused", None, None)), \
                 mock.patch.object(backfill, "DS_API_KEY", ""), mock.patch.object(backfill, "log"):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    weekly._chat_completion("https://relay.example/v1", SECRET, "model", [])
                self.assertEqual(raised.exception.code, code)
                self.assertFalse(heal_runner.probe_translation()[0])
                self.assertFalse(backfill.translate_title({"id": "TEST-001", "title": "日本語の物語タイトル"}))

    def test_worker_manifests_reference_existing_python_files(self):
        root = Path(__file__).resolve().parent
        ignore_lines = (root / "Dockerfile.worker.dockerignore").read_text().splitlines()
        self.assertIn("!translate_settings.py", ignore_lines)
        self.assertIn("!weekly_backfill_details.py", ignore_lines)
        included = False
        for line in ignore_lines:
            if fnmatch.fnmatchcase("translate_settings.py", line.lstrip("!")):
                included = line.startswith("!")
        self.assertTrue(included)
        lists = [[line[1:] for line in ignore_lines if line.startswith("!") and line.endswith(".py")]]
        for script in ("deploy.sh", "deploy_local.sh"):
            block = re.search(r"for rel in \\\n(.*?)\n\s*(?:; )?do\b", (root / script).read_text(), re.S)
            self.assertIsNotNone(block, script)
            files = re.findall(r"[\w/]+\.py\b", block.group(1))
            self.assertIn("translate_settings.py", files, script)
            self.assertIn("weekly_backfill_details.py", files, script)
            lists.append(files)
        blocks = re.findall(r"roots=\((.*?)\)", (root / "tools/build_identity.sh").read_text(), re.S)
        worker_blocks = [b for b in blocks if "heal_runner.py" in b]
        self.assertEqual(len(worker_blocks), 2)
        for block in worker_blocks:
            files = re.findall(r"[\w/]+\.py\b", block)
            self.assertIn("translate_settings.py", files)
            lists.append(files)
        for files in lists:
            for name in files:
                self.assertTrue((root / name).is_file(), name)

    def test_invalid_inputs(self):
        cases = [{"base": v} for v in ("file:///tmp/test", "https://user:pass@host", "https://host/a b", "https://host/\n", "https://" + "x" * 301, "https://", "https://host:bad", "https://host/\x7f")]
        cases += [{"key": v} for v in ("short", "a" * 301, "fake key", "abcdefgh\x00")]
        cases += [{"model": v} for v in ("", "a" * 101, "with space", "模型", "bad@model")]
        cases += [{"key": 123}, {"base": None}, [], {"unexpected": SECRET}]
        for body in cases:
            with self.subTest(body=body):
                status, data, _ = self.request("POST", body)
                self.assertEqual(status, 400)
                self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in data["error"]))
        self.assertFalse(self.path.exists())

    def test_get_ignores_content_type(self):
        for content_type in (None, "text/plain", "application/json", "invalid"):
            with self.subTest(content_type=content_type):
                status, data, _ = self.request("GET", content_type=content_type, length=1, slow=True)
                self.assertEqual(status, 200)
                self.assertEqual(data, settings.public_settings())

    def test_post_requires_json_content_type(self):
        for content_type in (None, "text/plain", "invalid"):
            with self.subTest(content_type=content_type):
                self.assertEqual(self.request("POST", {}, content_type=content_type)[0], 415)
        self.assertFalse(self.path.exists())

    def test_http_contract(self):
        for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CUSTOM"):
            self.assertEqual(self.request(method)[0], 405)
        for method in ("GET", "POST"):
            content_type = None if method == "GET" else "application/json"
            self.assertEqual(self.request(method, content_type=content_type, length=4097)[0], 413)
            self.assertEqual(self.request(method, content_type=content_type, length=-1)[0], 400)
            self.assertEqual(self.request(method, content_type=content_type, length="bad")[0], 400)
            self.assertEqual(self.request(method, content_type=content_type, transfer_encoding="chunked")[0], 400)
        self.assertEqual(self.request("POST", b'{broken')[0], 400)
        self.assertEqual(self.request("POST", b'\xff')[0], 400)
        self.assertEqual(self.request("POST", {})[0], 200)

    def test_completion_finish_reason(self):
        for reason in ("stop", "missing"):
            with mock.patch.object(settings.urllib.request.OpenerDirector, "open", return_value=Response(reason)) as call:
                self.assertEqual(weekly._chat_completion("https://example/v1", SECRET, "model", []), "这是完整的中文故事标题")
                self.assertEqual(json.loads(call.call_args.args[0].data)["max_tokens"], 2048)
        for reason in ("length", "content_filter", "tool_calls", None):
            with mock.patch.object(settings.urllib.request.OpenerDirector, "open", return_value=Response(reason, "甚至愿意让你")):
                with self.assertRaisesRegex(RuntimeError, "finish_reason="):
                    weekly._chat_completion("https://example/v1", SECRET, "model", [])

    def test_truncated_title_is_not_accepted(self):
        with mock.patch.object(settings.urllib.request.OpenerDirector, "open", return_value=Response("length", "甚至愿意让你")):
            with self.assertRaisesRegex(RuntimeError, "finish_reason=length"):
                weekly.translate_title_once("TEST-001", "日本語の物語タイトル")

    def test_next_translation_reads_new_settings(self):
        with mock.patch.object(settings.urllib.request.OpenerDirector, "open", return_value=Response()) as call:
            weekly.translate_title_once("TEST-001", "日本語の物語タイトル")
            self.seed()
            weekly.translate_title_once("TEST-001", "日本語の物語タイトル")
        requests = [entry.args[0] for entry in call.call_args_list]
        self.assertEqual([r.full_url for r in requests], ["https://env.example/v1/chat/completions", "https://file.example/v1/chat/completions"])
        self.assertEqual(json.loads(requests[1].data)["model"], "file-model")
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer " + SECRET)

    def test_backfill_uses_runtime_settings_and_rejects_truncation(self):
        self.seed()
        with mock.patch.object(backfill, "DS_API_KEY", ""), mock.patch.object(backfill, "log"), \
             mock.patch.object(settings.urllib.request.OpenerDirector, "open", return_value=Response("length", "甚至愿意让你")) as call:
            item = {"id": "TEST-001", "title": "日本語の物語タイトル"}
            self.assertFalse(backfill.translate_title(item))
            self.assertFalse(item.get("titleZh"))
            self.assertEqual(call.call_args.args[0].full_url, "https://file.example/v1/chat/completions")
            self.assertEqual(json.loads(call.call_args.args[0].data)["max_tokens"], 2048)

    def test_failures_do_not_leak_credentials(self):
        self.seed()
        responses = []
        for body in ({"key": SECRET + " "}, {"model": SECRET + "@"}, {"base": "file://" + SECRET}):
            responses.append(self.request("POST", body)[2])
        for exc in (OSError(SECRET), ValueError(SECRET)):
            with mock.patch.object(settings, "atomic_write_json", side_effect=exc):
                status, _, raw = self.request("POST", {"model": "new-model"})
                self.assertEqual(status, 500)
                responses.append(raw)
        settings.save_settings({"model": SECRET})
        for exc in (RuntimeError("Authorization: Bearer " + SECRET),
                    urllib.error.HTTPError("https://example/" + SECRET, 401, SECRET, {"Authorization": SECRET}, io.BytesIO(SECRET.encode()))):
            with mock.patch.object(settings.urllib.request.OpenerDirector, "open", side_effect=exc), \
                 mock.patch.object(weekly.time, "sleep"), mock.patch.object(weekly, "DS_TRANSLATE_RETRIES", 2):
                with self.assertRaises(Exception) as raised:
                    weekly.translate_title_with_retry("TEST-001", "日本語の物語タイトル")
                responses.append(str(raised.exception))
                ok, msg = heal_runner.probe_translation()
                self.assertFalse(ok)
                responses.append(msg)
        combined = "".join(responses) + self.logs.getvalue()
        for secret in (SECRET, SECRET[-4:], DEEP_SECRET, DEEP_SECRET[-4:]):
            self.assertNotIn(secret, combined)


    def test_missing_mode_defaults_to_auto_and_preserves_relay_fallback(self):
        fallback = ("https://fallback.example/v1", SECRET, "fallback-model")
        for draft in (None, {"base": "https://draft.example/v1"},
                      {"base": "https://file.example/v1", "key": SECRET, "model": "file-model"}):
            with self.subTest(draft=draft):
                if draft is not None:
                    self.path.write_text(json.dumps(draft))
                status, data, _ = self.request()
                self.assertEqual(status, 200)
                self.assertEqual(data["mode"], "auto")
                self.assertTrue(data["relay_enabled"])
                expected = ((draft["base"], SECRET, "file-model")
                            if draft and draft.get("key") else fallback)
                self.assertEqual(settings.effective_relay(fallback), expected)
                if not data["complete"]:
                    self.assertEqual(data["hint"], "尚未生效：需要同时保存 Base URL 和 API Key，当前仍在使用环境变量里的配置")

    def test_mode_only_post_preserves_relay_and_auto_restores_it(self):
        self.seed()
        original = json.loads(self.path.read_text())
        for mode in ("deepseek", "auto"):
            with self.subTest(mode=mode):
                status, data, raw = self.request("POST", {"mode": mode})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(self.path.read_text()), {**original, "mode": mode})
                self.assertTrue(data["key_set"])
                self.assertTrue(data["complete"])
                self.assertEqual(data["mode"], mode)
                self.assertEqual(data["relay_enabled"], mode == "auto")
                self.assertEqual(self.request()[1], data)
                if mode == "deepseek":
                    self.assertEqual(settings.effective_relay(), ("", "", "file-model"))
                    self.assertEqual(data["hint"], "当前只使用 DeepSeek，中继已停用")
                else:
                    self.assertEqual(settings.effective_relay(), (original["base"], SECRET, "file-model"))
                    self.assertNotIn("hint", data)
                for secret in (SECRET, DEEP_SECRET):
                    self.assertNotIn(secret, raw + self.logs.getvalue())

    def test_deepseek_incomplete_settings_never_consult_relay_fallback(self):
        for draft in ({}, {"base": "https://draft.example/v1"}, {"key": SECRET}):
            with self.subTest(draft=draft):
                self.path.write_text(json.dumps(draft))
                status, data, raw = self.request("POST", {"mode": "deepseek"})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(self.path.read_text()), {**draft, "mode": "deepseek"})
                self.assertFalse(data["complete"])
                self.assertEqual(data["key_set"], bool(draft.get("key")))
                self.assertEqual(data["hint"], "当前只使用 DeepSeek，中继已停用")
                self.assertNotIn(SECRET, raw)
                with mock.patch.object(settings, "_env_relay", side_effect=AssertionError("relay fallback forbidden")):
                    self.assertEqual(settings.effective_relay(), ("", "", "gpt-5.4"))
                    self.assertEqual(settings.effective_relay(("https://old.example", SECRET, "old-model")),
                                     ("", "", "gpt-5.4"))

    def test_invalid_mode_post_returns_400_without_changing_file(self):
        self.seed()
        before = self.path.read_bytes()
        for mode in ("x", 1, "", None, True, [], {}, "AUTO", "deepseek "):
            with self.subTest(mode=mode):
                status, data, raw = self.request("POST", {"mode": mode})
                self.assertEqual(status, 400)
                self.assertEqual(data["error"], "翻译源模式只能是 auto 或 deepseek")
                self.assertEqual(self.path.read_bytes(), before)
                self.assertNotIn(SECRET, raw)

    def test_invalid_saved_mode_is_ignored_without_discarding_relay(self):
        self.seed()
        original = json.loads(self.path.read_text())
        for mode in ("x", 1, "", None, True, [], {}):
            with self.subTest(mode=mode):
                self.path.write_text(json.dumps({**original, "mode": mode}))
                status, data, _ = self.request()
                self.assertEqual(status, 200)
                self.assertEqual(data["mode"], "auto")
                self.assertTrue(data["relay_enabled"])
                self.assertTrue(data["complete"])
                self.assertEqual(settings.effective_relay(), (original["base"], SECRET, "file-model"))
                self.assertEqual(settings._validate({"mode": mode}, saved=True), {})

    def test_deepseek_same_base_update_keeps_key(self):
        self.seed()
        self.assertEqual(self.request("POST", {"mode": "deepseek"})[0], 200)
        status, data, _ = self.request("POST", {"base": "https://file.example/v1/"})
        self.assertEqual(status, 200)
        self.assertTrue(data["key_set"], "unchanged relay base must preserve its saved key")
        self.assertEqual(json.loads(self.path.read_text())["key"], SECRET)
        # Nonempty key updates must still include base even while relay is disabled.
        self.assertEqual(self.request("POST", {"key": SECRET})[0], 400)

    def test_deepseek_changed_base_update_clears_key(self):
        self.seed()
        self.assertEqual(self.request("POST", {"mode": "deepseek"})[0], 200)
        status, data, _ = self.request("POST", {"base": "https://changed.example/v1"})
        self.assertEqual(status, 200)
        self.assertFalse(data["key_set"])
        self.assertFalse(data["complete"])
        self.assertEqual(json.loads(self.path.read_text())["key"], "")
        self.assertEqual(data["mode"], "deepseek")
        self.assertEqual(settings.effective_relay()[:2], ("", ""))

    def test_deepseek_weekly_candidates_exclude_saved_and_environment_relay(self):
        with mock.patch.object(weekly, "DS_API_KEY", DEEP_SECRET):
            for complete in (False, True):
                with self.subTest(complete=complete):
                    if complete:
                        self.seed()
                    self.assertEqual(self.request("POST", {"mode": "deepseek"})[0], 200)
                    self.assertEqual(weekly.translation_provider_candidates(),
                                     [("deepseek", "https://api.deepseek.com", DEEP_SECRET, weekly.DS_MODEL)])
                    self.assertEqual(weekly.translation_provider(), ("deepseek", weekly.DS_MODEL))

    def test_deepseek_heal_candidates_exclude_saved_and_environment_relay(self):
        with mock.patch.object(heal_runner, "DS_API_KEY", DEEP_SECRET):
            for complete in (False, True):
                with self.subTest(complete=complete):
                    if complete:
                        self.seed()
                    self.assertEqual(self.request("POST", {"mode": "deepseek"})[0], 200)
                    self.assertEqual(heal_runner._translation_probe_candidates(),
                                     [("DeepSeek", "https://api.deepseek.com", DEEP_SECRET, heal_runner.DS_MODEL)])

    def test_deepseek_backfill_candidates_exclude_saved_and_environment_relay(self):
        with mock.patch.object(backfill, "DS_API_KEY", DEEP_SECRET), mock.patch.object(backfill, "log"):
            for complete in (False, True):
                with self.subTest(complete=complete):
                    if complete:
                        self.seed()
                    self.assertEqual(self.request("POST", {"mode": "deepseek"})[0], 200)
                    # Exhaust candidates, so even a relay after DeepSeek would be detected.
                    with mock.patch.object(backfill, "_chat_completion", side_effect=RuntimeError("offline")) as call:
                        self.assertFalse(backfill.translate_title({"id": "TEST-001", "title": "日本語の物語タイトル"}))
                    self.assertEqual([c.args[:3] for c in call.call_args_list],
                                     [("https://api.deepseek.com", DEEP_SECRET, backfill.DS_MODEL)])


if __name__ == "__main__":
    unittest.main()
