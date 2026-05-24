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
        self.assertEqual(payload["compose_files"], [str(compose)])

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

    def test_deploy_production_web_profile_adds_override_compose(self) -> None:
        result = self.run_cli(
            "deploy",
            "render",
            "--profile",
            "production-web",
            "--dry-run",
            "--format",
            "json",
            env_overrides={"COMPOSE_PROJECT_NAME": None},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["compose_files"][-1],
            str(REPO_ROOT / "docker-compose.production-web.example.yml"),
        )
        self.assertEqual(payload["command"].count("--file"), 2)

    def test_deploy_production_web_profile_dedupes_explicit_override(self) -> None:
        production_compose = REPO_ROOT / "docker-compose.production-web.example.yml"
        result = self.run_cli(
            "deploy",
            "render",
            "--profile",
            "production-web",
            "--compose-file",
            str(production_compose),
            "--dry-run",
            "--format",
            "json",
            env_overrides={"COMPOSE_PROJECT_NAME": None},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["compose_files"], [str(production_compose)])
        self.assertEqual(payload["command"].count("--file"), 1)

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

    def test_deploy_bundle_writes_production_web_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "bundle"
            result = self.run_cli(
                "deploy",
                "bundle",
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            manifest = json.loads(
                (output_dir / "platform-deploy-bundle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["output_dir"], str(output_dir))
            self.assertTrue((output_dir / "docker-compose.example.yml").is_file())
            self.assertTrue(
                (output_dir / "docker-compose.production-web.example.yml").is_file()
            )
            self.assertTrue((output_dir / ".env.example").is_file())
            self.assertTrue((output_dir / "README.md").is_file())
            self.assertEqual(manifest["profile"], "production-web")
            self.assertEqual(
                manifest["compose_files"],
                [
                    "docker-compose.example.yml",
                    "docker-compose.production-web.example.yml",
                ],
            )
            self.assertEqual(manifest["env_example"], ".env.example")
            self.assertEqual(manifest["env_file"], ".env")
            self.assertEqual(manifest["command"].count("--file"), 2)
            self.assertIn(".env", manifest["command"])

    def test_deploy_bundle_ignores_local_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            output_dir = root_path / "bundle"
            local_env = root_path / ".env"
            local_env.write_text("SECRET_TOKEN=do-not-copy\n", encoding="utf-8")
            result = self.run_cli(
                "deploy",
                "bundle",
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
                env_overrides={"PLATFORM_ENV_FILE": str(local_env)},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "platform-deploy-bundle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["env_example"], ".env.example")
            self.assertEqual(manifest["env_file"], ".env")
            self.assertNotIn("SECRET_TOKEN", (output_dir / ".env.example").read_text())
