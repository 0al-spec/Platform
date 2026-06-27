import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "platform.py"
API_IMAGE = (
    "ghcr.io/0al-spec/specspace-api@sha256:"
    "1111111111111111111111111111111111111111111111111111111111111111"
)
UI_IMAGE = (
    "ghcr.io/0al-spec/specspace-ui@sha256:"
    "2222222222222222222222222222222222222222222222222222222222222222"
)


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

    def test_timeweb_render_writes_manifest_only_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--release-commit",
                "abc123",
                "--release-created-at",
                "1970-01-01T00:00:00Z",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["output_dir"], str(output_dir))
            self.assertEqual(
                sorted(path.name for path in output_dir.iterdir()),
                ["README.md", "docker-compose.yml", "platform-timeweb-deploy.json"],
            )
            self.assertIn("services:\n  app:", compose)
            self.assertIn(f'image: "{UI_IMAGE}"', compose)
            self.assertIn(f'image: "{API_IMAGE}"', compose)
            self.assertNotIn("volumes:", compose)
            self.assertNotIn("build:", compose)
            self.assertNotIn("${ORG_ROOT", compose)
            self.assertNotIn("${SPECSPACE_API_PORT:-8001}:8001", compose)
            self.assertNotIn("${SPECSPACE_UI_PORT:-5173}:80", compose)
            self.assertIn('  app:\n    image: "' + UI_IMAGE + '"\n    ports:\n      - "80"', compose)
            self.assertIn("    expose:\n      - \"8001\"\n", compose)
            self.assertIn(
                'SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED: "true"',
                compose,
            )
            self.assertIn('SPECSPACE_HYPERPROMPT_WORK_DIR: "/tmp"', compose)
            self.assertIn(
                'SPECSPACE_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS: "60"',
                compose,
            )
            self.assertIn('SPECSPACE_HYPERPROMPT_MAX_INPUT_BYTES: "1048576"', compose)
            self.assertIn('SPECSPACE_HYPERPROMPT_MAX_OUTPUT_BYTES: "2097152"', compose)
            self.assertIn(
                'SPECSPACE_HYPERPROMPT_BUNDLE_RETENTION_COUNT: "20"',
                compose,
            )
            self.assertIn("--product-workspace-artifact-base-url", compose)
            self.assertEqual(manifest["artifact_kind"], "platform_timeweb_deploy_manifest")
            self.assertEqual(manifest["release_commit"], "abc123")
            self.assertEqual(
                manifest["product_workspace_artifact_base_urls"],
                {"team-decision-log": "https://specgraph.tech"},
            )
            self.assertTrue(manifest["hyperprompt_http_compile_enabled"])
            self.assertEqual(manifest["hyperprompt_work_dir"], "/tmp")
            self.assertEqual(manifest["hyperprompt_compile_timeout_seconds"], "60")

    def test_timeweb_render_can_set_product_workspace_artifact_base_urls(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--artifact-base-url",
                "https://specgraph.tech",
                "--product-workspace-artifact-base-url",
                "analytics=https://artifacts.example/analytics",
                "--product-workspace-artifact-base-url",
                "support-triage-log=https://artifacts.example/support-triage-log",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--product-workspace-artifact-base-url",
                "analytics=https://artifacts.example/analytics",
                "--product-workspace-artifact-base-url",
                "support-triage-log=https://artifacts.example/support-triage-log",
                "--format",
                "json",
            )

            self.assertEqual(render.returncode, 0, render.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                '      - --product-workspace-artifact-base-url\n'
                '      - "analytics=https://artifacts.example/analytics"',
                compose,
            )
            self.assertIn(
                '      - --product-workspace-artifact-base-url\n'
                '      - "support-triage-log=https://artifacts.example/support-triage-log"',
                compose,
            )
            self.assertEqual(
                manifest["product_workspace_artifact_base_urls"],
                {
                    "analytics": "https://artifacts.example/analytics",
                    "support-triage-log": "https://artifacts.example/support-triage-log",
                },
            )
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_timeweb_publish_threads_product_workspace_artifact_base_url(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "timeweb-publish.yml"
        ).read_text(encoding="utf-8")
        publish_script = (
            REPO_ROOT / "scripts" / "publish-timeweb-deploy-branch.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("product_workspace_artifact_base_url:", workflow)
        self.assertIn(
            "--product-workspace-artifact-base-url "
            '"${{ inputs.product_workspace_artifact_base_url || inputs.artifact_base_url }}"',
            workflow,
        )
        self.assertIn(
            "TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL: "
            "${{ inputs.product_workspace_artifact_base_url || inputs.artifact_base_url }}",
            workflow,
        )
        self.assertIn(
            'product_workspace_artifact_base_url="'
            '${TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL:-',
            publish_script,
        )
        self.assertEqual(
            publish_script.count("--product-workspace-artifact-base-url"),
            2,
        )

    def test_timeweb_render_rejects_mutable_image_ref(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(Path(root) / "timeweb"),
                "--specspace-api-image-ref",
                "ghcr.io/0al-spec/specspace-api:latest",
                "--specspace-ui-image-ref",
                UI_IMAGE,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must not use the mutable latest tag", result.stderr)

    def test_timeweb_render_reads_service_image_lock(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            output_dir = root_path / "timeweb"
            image_lock = root_path / "platform-service-images.json"
            image_lock.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_service_image_lock",
                        "schema_version": 1,
                        "services": {
                            "specspace_api": {"image_ref": API_IMAGE},
                            "specspace_ui": {"image_ref": UI_IMAGE},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--image-lock",
                str(image_lock),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(f'image: "{UI_IMAGE}"', compose)
            self.assertIn(f'image: "{API_IMAGE}"', compose)
            self.assertEqual(manifest["image_lock"], str(image_lock))
            self.assertEqual(manifest["specspace_api_image_ref"], API_IMAGE)
            self.assertEqual(manifest["specspace_ui_image_ref"], UI_IMAGE)

    def test_timeweb_render_can_disable_hyperprompt_http_compile(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--disable-hyperprompt-http-compile",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--disable-hyperprompt-http-compile",
                "--format",
                "json",
            )

            self.assertEqual(render.returncode, 0, render.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(
                'SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED: "false"',
                compose,
            )
            self.assertNotIn("SPECSPACE_HYPERPROMPT_WORK_DIR", compose)
            self.assertFalse(manifest["hyperprompt_http_compile_enabled"])
            self.assertIsNone(manifest["hyperprompt_work_dir"])
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_timeweb_render_rejects_invalid_hyperprompt_limit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(Path(root) / "timeweb"),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--hyperprompt-max-output-bytes",
                "0",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Hyperprompt max output bytes must be a positive integer", result.stderr)

    def test_timeweb_render_validates_image_lock_refs(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            image_lock = root_path / "platform-service-images.json"
            image_lock.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_service_image_lock",
                        "schema_version": 1,
                        "services": {
                            "specspace_api": {
                                "image_ref": "ghcr.io/0al-spec/specspace-api:latest"
                            },
                            "specspace_ui": {"image_ref": UI_IMAGE},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(root_path / "timeweb"),
                "--image-lock",
                str(image_lock),
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must not use the mutable latest tag", result.stderr)

    def test_timeweb_render_rejects_unsupported_image_lock_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            image_lock = root_path / "platform-service-images.json"
            image_lock.write_text(
                json.dumps(
                    {
                        "artifact_kind": "platform_service_image_lock",
                        "schema_version": 2,
                        "services": {
                            "specspace_api": {"image_ref": API_IMAGE},
                            "specspace_ui": {"image_ref": UI_IMAGE},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(root_path / "timeweb"),
                "--image-lock",
                str(image_lock),
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("schema_version must be 1", result.stderr)

    def test_timeweb_validate_accepts_generated_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_timeweb_validate_rejects_non_manifest_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "docker-compose.yml").write_text(
                "services:\n"
                "  specspace-api:\n"
                f"    image: \"{API_IMAGE}\"\n"
                "    volumes:\n"
                "      - ./data:/data\n",
                encoding="utf-8",
            )
            (root_path / "source.py").write_text("print('no')\n", encoding="utf-8")
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(root_path),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any("unexpected top-level entries" in error for error in payload["errors"])
        )
        self.assertTrue(any("must not declare volumes" in error for error in payload["errors"]))

    def test_timeweb_validate_rejects_api_host_port_binding(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
            )
            compose_path = output_dir / "docker-compose.yml"
            compose = compose_path.read_text(encoding="utf-8")
            compose_path.write_text(
                compose.replace(
                    "    expose:\n      - \"8001\"\n",
                    "    ports:\n      - \"${SPECSPACE_API_PORT:-8001}:8001\"\n",
                ),
                encoding="utf-8",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any(
                "specspace-api must not publish host ports" in error
                for error in payload["errors"]
            )
        )

    def test_timeweb_validate_rejects_inline_api_host_port_binding(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
            )
            compose_path = output_dir / "docker-compose.yml"
            compose = compose_path.read_text(encoding="utf-8")
            compose_path.write_text(
                compose.replace(
                    "    expose:\n      - \"8001\"\n",
                    '    expose: ["8001"]\n'
                    '    ports: ["${SPECSPACE_API_PORT:-8001}:8001"]\n',
                ),
                encoding="utf-8",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any(
                "specspace-api must not publish host ports" in error
                for error in payload["errors"]
            )
        )

    def test_timeweb_validate_rejects_app_fixed_host_port_binding(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            render = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
            )
            compose_path = output_dir / "docker-compose.yml"
            compose = compose_path.read_text(encoding="utf-8")
            compose_path.write_text(
                compose.replace(
                    '      - "80"\n',
                    '      - "${SPECSPACE_UI_PORT:-5173}:80"\n',
                    1,
                ),
                encoding="utf-8",
            )
            result = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(
            any(
                "app must not publish fixed host ports" in error
                for error in payload["errors"]
            )
        )
