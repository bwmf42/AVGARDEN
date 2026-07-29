import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy.sh"


def plan_for(*paths: str) -> dict[str, str]:
    result = subprocess.run(
        [str(DEPLOY), "--plan-paths", *paths],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class DeployPlanTest(unittest.TestCase):
    def test_worker_inputs_only_rebuild_worker(self):
        self.assertEqual(
            plan_for("worker.py", "src/weekly/artwork.py"),
            {"build": "worker", "recreate": "worker"},
        )

    def test_server_inputs_only_rebuild_server(self):
        self.assertEqual(
            plan_for("backend/handlers.go", "frontend/src/App.vue"),
            {"build": "server", "recreate": "server"},
        )

    def test_runtime_config_recreates_without_building(self):
        self.assertEqual(
            plan_for("cfg/runtime.yaml"),
            {"build": "none", "recreate": "server worker"},
        )

    def test_config_example_does_not_restart_services(self):
        self.assertEqual(
            plan_for("cfg/configs.json.example"),
            {"build": "none", "recreate": "none"},
        )

    def test_docs_do_not_restart_services(self):
        self.assertEqual(
            plan_for("CHANGELOG.md", "docs/code-audit.md"),
            {"build": "none", "recreate": "none"},
        )

    def test_unknown_paths_use_safe_full_rebuild(self):
        self.assertEqual(
            plan_for("unexpected.runtime"),
            {
                "build": "server worker",
                "recreate": "server worker",
                "unknown": "unexpected.runtime",
            },
        )


if __name__ == "__main__":
    unittest.main()
