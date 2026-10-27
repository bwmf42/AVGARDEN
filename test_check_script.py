"""Offline check.sh contract tests in isolated fixture repositories."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class CheckScriptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="avgarden-check-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "backend").mkdir()
        (self.root / "frontend" / "node_modules").mkdir(parents=True)
        self.script = self.root / "scripts" / "check.sh"
        shutil.copyfile(ROOT / "scripts" / "check.sh", self.script)
        self.trace = self.root / "trace"
        self.env = dict(os.environ, PATH=str(self.bin), TRACE=str(self.trace),
                        TMPDIR=str(self.root), REAL_PYTHON=sys.executable,
                        PYTHONPYCACHEPREFIX=str(self.root / "pycache"),
                        GOCACHE=str(self.root / "gocache"))
        for key in list(self.env):
            if key.startswith("STUB_") or key == "AVGARDEN_URL":
                self.env.pop(key)
        # A closed PATH makes missing tools deterministic even on developer Macs.
        for name in ("dirname", "mktemp", "tail", "cat"):
            os.symlink(shutil.which(name), self.bin / name)
        self.stub("python3", '''
printf 'python %s\\n' "$*" >> "$TRACE"
if [ "$*" = "-m unittest discover -s . -p test_*.py" ]; then
    echo 'fixture unittest output'
    exit "${STUB_UNITTEST_STATUS:-0}"
fi
exec "$REAL_PYTHON" "$@"
''')
        self.stub("git", "printf 'sample.py\\0src/with space.py\\0frontend/bad.py\\0vendor/bad.py\\0src/third_party/bad.py\\0node_modules/bad.py\\0'")
        (self.root / "sample.py").write_text("value = 1\n")
        (self.root / "src").mkdir()
        (self.root / "src" / "with space.py").write_text("value = 2\n")
        for name in ("frontend", "vendor", "src/third_party", "node_modules"):
            directory = self.root / name
            directory.mkdir(exist_ok=True, parents=True)
            (directory / "bad.py").write_text("invalid syntax !!!\n")
        (self.root / "untracked.py").write_text("invalid syntax !!!\n")
        self.stub("go", '''
printf 'go %s\\n' "$*" >> "$TRACE"
echo 'fixture go output'
exit "${STUB_GO_STATUS:-0}"
''')
        self.stub("node", "exit 0")
        self.stub("npm", '''
printf 'npm %s\\n' "$*" >> "$TRACE"
echo 'fixture npm output'
exit "${STUB_NPM_STATUS:-0}"
''')
        # Configuration lives in check_version.sh; its execution delegates to PATH.
        (self.root / "check_version.sh").write_text('''#!/bin/bash
URL="${AVGARDEN_URL:-http://fixture-nas.invalid:1234}"
# ssh -o ConnectTimeout=6 -o BatchMode=yes fixture-host command
exec check_version.sh "$@"
''')
        (self.root / "check_version.sh").chmod(0o755)
        self.stub("check_version.sh", '''
echo version >> "$TRACE"
exit "${STUB_VERSION_STATUS:-0}"
''')
        self.stub("curl", '''
printf 'curl %s\\n' "$*" >> "$TRACE"
[ "${STUB_CURL_STATUS:-0}" -eq 0 ] || exit "$STUB_CURL_STATUS"
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then
        body='{}'
        printf '%s' "${STUB_BODY-$body}" > "$2"
        shift
    fi
    shift
done
printf '%s' "${STUB_HTTP_STATUS:-200}"
''')
        self.stub("ssh", '''
printf 'ssh %s\\n' "$*" >> "$TRACE"
printf '%s\\n' "${STUB_HEALTH-healthy|running}"
exit "${STUB_SSH_STATUS:-0}"
''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, *args, **env):
        return subprocess.run(["/bin/bash", str(self.script), *args],
                              cwd=self.root, env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=20)

    def events(self):
        return self.trace.read_text() if self.trace.exists() else ""

    def test_help_and_invalid_parameters(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        for text in ("第 1 层", "第 2 层", "第 3 层", "Exit: 0", "1 =", "2 ="):
            self.assertIn(text, result.stdout)
        self.assertEqual(self.events(), "")
        for args in (("--layer",), ("--layer", "3"), ("--unknown",)):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 1)

    def test_default_runs_only_local_checks(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SUMMARY PASS=4 FAIL=0 SKIP=0 exit=0", result.stdout.splitlines()[-1])
        self.assertIn("go vet ./...\ngo test ./...", self.events())
        self.assertIn("npm run build", self.events())
        self.assertNotIn("curl ", self.events())
        self.assertNotIn("ssh ", self.events())
        self.assertNotIn("=== 第 2 层", result.stdout)
        self.assertIn("第 3 层需人工或浏览器验收", result.stdout)
        self.assertNotIn("fixture go output", result.stdout)

    def test_quick_runs_only_python_even_with_layer_all(self):
        for args in (("--quick",), ("--layer", "all", "--quick")):
            with self.subTest(args=args):
                result = self.run_script(*args)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("SUMMARY PASS=2 FAIL=0 SKIP=0 exit=0", result.stdout)
                self.assertNotIn("go ", self.events())
                self.assertNotIn("npm ", self.events())
                self.assertNotIn("curl ", self.events())
                logs = list(self.root.glob("avgarden-check.*/1.log"))
                self.assertTrue(any("Tracked Python files: 2" in p.read_text() for p in logs))

    def test_missing_tools_are_skip(self):
        for name in ("go", "npm", "node"):
            (self.bin / name).unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKIP Go vet/test: 缺少 go", result.stdout)
        self.assertIn("SKIP Frontend build: 缺少 node 或 npm", result.stdout)
        self.assertIn("SUMMARY PASS=2 FAIL=0 SKIP=2 exit=0", result.stdout)

    def test_missing_python_and_node_modules_are_skip(self):
        (self.bin / "python3").unlink()
        (self.root / "frontend" / "node_modules").rmdir()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKIP Python syntax: 缺少 python3", result.stdout)
        self.assertIn("SKIP Python unittest: 缺少 python3", result.stdout)
        self.assertIn("缺少 frontend/node_modules", result.stdout)

    def test_missing_git_skips_syntax_but_runs_unittest(self):
        (self.bin / "git").unlink()
        result = self.run_script("--quick")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SKIP Python syntax: 缺少 git", result.stdout)
        self.assertIn("PASS Python unittest", result.stdout)

    def test_python_and_frontend_failures_are_reported(self):
        (self.root / "sample.py").write_text("invalid syntax !!!\n")
        result = self.run_script(STUB_UNITTEST_STATUS="1", STUB_NPM_STATUS="1")
        self.assertEqual(result.returncode, 1, result.stdout)
        for label in ("Python syntax", "Python unittest", "Frontend build"):
            self.assertIn("FAIL " + label, result.stdout)
        self.assertIn("SUMMARY PASS=1 FAIL=3 SKIP=0 exit=1", result.stdout)

    def test_failure_exit_and_last_twenty_log_lines(self):
        self.stub("go", "for ((i=1; i<=30; i++)); do echo line-$i; done; exit 1")
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL Go vet/test:", result.stdout)
        self.assertNotIn("\nline-10\n", result.stdout)
        self.assertIn("\nline-11\n", result.stdout)
        self.assertIn("\nline-30\n", result.stdout)
        logs = list(self.root.glob("avgarden-check.*/3.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("line-1\n", logs[0].read_text())
        self.assertIn("PASS Frontend build", result.stdout)

    def test_all_layers_reuse_config_and_read_only_commands(self):
        result = self.run_script("--layer", "all")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SUMMARY PASS=9 FAIL=0 SKIP=0 exit=0", result.stdout)
        self.assertIn("version\n", self.events())
        self.assertIn("http://fixture-nas.invalid:1234/api/version", self.events())
        self.assertIn("http://fixture-nas.invalid:1234/api/queue-status", self.events())
        ssh_events = [line for line in self.events().splitlines() if line.startswith("ssh ")]
        self.assertEqual(len(ssh_events), 2)
        for line, container in zip(ssh_events, ("avgarden-server", "avgarden-worker")):
            self.assertIn("fixture-host sudo -n docker inspect -f", line)
            self.assertTrue(line.endswith(container))
            self.assertIn("StrictHostKeyChecking=yes", line)

    def test_layer_two_url_override_and_no_healthcheck(self):
        result = self.run_script("--layer", "2", AVGARDEN_URL="http://override.invalid:4567/",
                                 STUB_HEALTH="|running", STUB_BODY='{"value": 1}')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("http://override.invalid:4567/api/version", self.events())
        self.assertNotIn("go ", self.events())
        self.assertNotIn("python -m unittest", self.events())

    def test_current_check_version_config_is_understood_without_execution(self):
        source = (ROOT / "check_version.sh").read_text()
        (self.root / "check_version.sh").write_text(
            '#!/bin/bash\nexec check_version.sh "$@"\n' + source)
        result = self.run_script("--layer", "2", AVGARDEN_URL="http://fixture.invalid")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("http://fixture.invalid/api/version", self.events())
        self.assertIn(" zspace sudo -n docker inspect", self.events())

    def test_nas_unreachable_exit_two(self):
        result = self.run_script("--layer", "2", STUB_VERSION_STATUS="2",
                                 STUB_CURL_STATUS="7", STUB_SSH_STATUS="255")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("SUMMARY PASS=0 FAIL=5 SKIP=0 exit=2", result.stdout)

    def test_partial_nas_outage_is_failure_not_unreachable(self):
        result = self.run_script("--layer", "2", STUB_VERSION_STATUS="2", STUB_CURL_STATUS="7")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("PASS Container avgarden-worker", result.stdout)

    def test_all_layers_nas_outage_takes_exit_two_even_with_local_failure(self):
        result = self.run_script("--layer", "all", STUB_UNITTEST_STATUS="1",
                                 STUB_VERSION_STATUS="2", STUB_CURL_STATUS="7",
                                 STUB_SSH_STATUS="255")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("FAIL Python unittest", result.stdout)
        self.assertIn("SUMMARY PASS=3 FAIL=6 SKIP=0 exit=2", result.stdout)

    def test_version_json_http_and_health_failures(self):
        for env, expected in (({"STUB_VERSION_STATUS": "1"}, "FAIL NAS version"),
                              ({"STUB_BODY": "private-invalid-body"}, "FAIL API /api/version"),
                              ({"STUB_HTTP_STATUS": "503"}, "FAIL API /api/queue-status"),
                              ({"STUB_HEALTH": "unhealthy|running"}, "FAIL Container avgarden-server"),
                              ({"STUB_HEALTH": "healthy|exited"}, "FAIL Container avgarden-worker")):
            with self.subTest(env=env):
                result = self.run_script("--layer", "2", **env)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("private-invalid-body", result.stdout)

    def test_missing_nas_tools_skip_without_connection(self):
        for name in ("curl", "ssh"):
            (self.bin / name).unlink()
        result = self.run_script("--layer", "2")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("SUMMARY PASS=0 FAIL=0 SKIP=5 exit=0", result.stdout)
        self.assertNotIn("version\n", self.events())

    def test_credential_url_is_rejected_before_commands(self):
        result = self.run_script("--layer", "2", AVGARDEN_URL="http://user:private-value@host/")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("private-value", result.stdout + result.stderr)
        self.assertNotIn("curl ", self.events())
        self.assertNotIn("ssh ", self.events())


if __name__ == "__main__":
    unittest.main()
