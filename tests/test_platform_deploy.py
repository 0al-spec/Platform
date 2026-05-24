import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "platform.py"


class PlatformDeployTests(unittest.TestCase):
    def run_cli(
        self,
        *args: str,
        env_overrides: dict[str, str | None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=False,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_deploy_render_dry_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            compose = Path(root) / "compose.yml"
            env_file = Path(root) / ".env"
            compose.write_text("services: {}\n", encoding="utf-8")
            env_file.write_text("ORG_ROOT=/tmp/0AL\n", encoding="utf-8")

            result = self.run_cli(
                "deploy",
                "render",
                "--compose-file",
                str(compose),
                "--env-file",
                str(env_file),
                "--project-name",
                "test-platform",
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "render")
        self.assertEqual(payload["project_name"], "test-platform")
        self.assertEqual(payload["command"][-1], "config")
        self.assertIn("--env-file", payload["command"])

    def test_deploy_status_invokes_docker_compose(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            compose = root_path / "compose.yml"
            env_file = root_path / ".env"
            docker = root_path / "fake-docker.py"
            argv_log = root_path / "argv.json"
            compose.write_text("services: {}\n", encoding="utf-8")
            env_file.write_text("ORG_ROOT=/tmp/0AL\n", encoding="utf-8")
            docker.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "with open(os.environ['ARGV_LOG'], 'w', encoding='utf-8') as handle:\n"
                "    json.dump(sys.argv[1:], handle)\n"
                "print('compose status')\n",
                encoding="utf-8",
            )
            docker.chmod(0o755)

            result = self.run_cli(
                "deploy",
                "status",
                "--compose-file",
                str(compose),
                "--env-file",
                str(env_file),
                "--project-name",
                "test-platform",
                "--docker",
                str(docker),
                env_overrides={"ARGV_LOG": str(argv_log)},
            )

            argv = json.loads(argv_log.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compose status", result.stdout)
        self.assertEqual(argv[0], "compose")
        self.assertIn("--project-name", argv)
        self.assertEqual(argv[-1], "ps")

    def test_deploy_dry_run_uses_compose_project_default_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            compose = Path(root) / "compose.yml"
            compose.write_text("name: test-platform\nservices: {}\n", encoding="utf-8")

            result = self.run_cli(
                "deploy",
                "status",
                "--compose-file",
                str(compose),
                "--dry-run",
                "--format",
                "json",
                env_overrides={"COMPOSE_PROJECT_NAME": None},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload["project_name"])
        self.assertNotIn("--project-name", payload["command"])

    def test_deploy_missing_compose_file_is_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = self.run_cli(
                "deploy",
                "status",
                "--compose-file",
                str(Path(root) / "missing.yml"),
                "--dry-run",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("compose file does not exist", result.stderr)
