import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from scripts.validate_hosted_managed_runtime_compose import (
    _ports_publish_only_loopback,
)


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


def _specspace_smoke_workspace_payload(
    *,
    readiness_status: str = "read_only",
    readiness_mode: str = "read_only",
    enabled_operation_count: int | None = None,
) -> dict[str, object]:
    effective_enabled_count = (
        enabled_operation_count
        if enabled_operation_count is not None
        else (0 if readiness_status == "read_only" else 1)
    )
    hosted = readiness_status.startswith("hosted_managed")
    return {
        "workspace": {"id": "team-decision-log"},
        "source": {
            "provider": "http-product-workspace",
            "artifact_base_url": "https://specgraph.tech/workspaces/team-decision-log",
        },
        "managed_mode_readiness": {
            "status": readiness_status,
            "mode": readiness_mode,
            "executor": {
                "enabled": readiness_status != "read_only",
                "configured": readiness_status != "read_only",
                "transport": "hosted_queue"
                if hosted
                else "local_subprocess"
                if readiness_status != "read_only"
                else "none",
                "hosted_enabled": hosted,
                "hosted_service_configured": hosted,
                "hosted_service_reachable": hosted,
                "hosted_enabled_operation_ids": ["review_status_execute"]
                if hosted
                else None,
            },
            "operations": {
                "registered": 12,
                "enabled_count": effective_enabled_count,
                "disabled_count": 12 - effective_enabled_count,
            },
        },
        "managed_operations_observability": {
            "operations": [
                {
                    "operation_id": "product_workspace_initialization",
                    "status": "disabled_missing_inputs",
                    "authority_boundary": {
                        "may_execute_platform": False,
                        "may_create_branch_or_commit": False,
                    },
                }
            ]
        },
    }


class _SpecSpaceSmokeHandler(BaseHTTPRequestHandler):
    health_payload: dict[str, object] = {
        "api_version": "v1",
        "deployment": {"commit": "abc123"},
    }
    workspace_payload: dict[str, object] = _specspace_smoke_workspace_payload()
    transient_failures: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802
        remaining_failures = self.transient_failures.get(self.path, 0)
        if remaining_failures > 0:
            self.transient_failures[self.path] = remaining_failures - 1
            self.send_response(502)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"restart window")
            return
        if self.path == "/api/v1/health":
            self._write_json(self.health_payload)
            return
        if self.path.startswith("/api/v1/idea-to-spec-workspace?"):
            self._write_json(self.workspace_payload)
            return
        if self.path == "/team-decision-log":
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>SpecSpace</body></html>")
            return
        if self.path == "/team-decision-log?view=demo":
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>SpecSpace demo view</body></html>")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write_json(self, payload: dict[str, object]) -> None:
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


class _SmokeServer:
    def __init__(
        self,
        workspace_payload: dict[str, object],
        *,
        transient_failures: dict[str, int] | None = None,
    ) -> None:
        handler = type(
            "SpecSpaceSmokeHandler",
            (_SpecSpaceSmokeHandler,),
            {
                "workspace_payload": workspace_payload,
                "transient_failures": dict(transient_failures or {}),
            },
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


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

    def test_hosted_runtime_ports_require_only_loopback_bindings(self) -> None:
        self.assertTrue(
            _ports_publish_only_loopback(
                [{"host_ip": "127.0.0.1", "published": "8091", "target": 8091}]
            )
        )

    def test_hosted_runtime_ports_reject_additional_public_binding(self) -> None:
        self.assertFalse(
            _ports_publish_only_loopback(
                [
                    {"host_ip": "127.0.0.1", "published": "8091", "target": 8091},
                    {"host_ip": "0.0.0.0", "published": "9091", "target": 8091},
                ]
            )
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

    def test_specspace_product_smoke_cli_passes_read_only_workspace(self) -> None:
        with _SmokeServer(_specspace_smoke_workspace_payload()) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["summary"]["ok"])
        self.assertEqual(
            payload["artifact_kind"],
            "platform_specspace_product_workspace_production_smoke_report",
        )
        self.assertEqual(payload["summary"]["workspace"], "team-decision-log")
        self.assertIn("demo_view", payload["source_refs"])
        self.assertIn(
            "specspace_product_demo_view_route_available",
            {check["id"] for check in payload["checks"]},
        )

    def test_specspace_product_smoke_cli_parses_bound_artifact_base_env(self) -> None:
        with _SmokeServer(_specspace_smoke_workspace_payload()) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--format",
                "json",
                "--no-write-report",
                env_overrides={
                    "SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL": (
                        "team-decision-log="
                        "https://specgraph.tech/workspaces/team-decision-log"
                    ),
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["summary"]["ok"])

    def test_specspace_product_smoke_cli_blocks_backend_managed_mode(self) -> None:
        workspace_payload = _specspace_smoke_workspace_payload(
            readiness_status="backend_managed_ready",
            readiness_mode="backend_managed_ready",
        )
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["summary"]["ok"])
        self.assertIn(
            "specspace_managed_mode_status",
            {diagnostic["code"] for diagnostic in payload["diagnostics"]},
        )

    def test_specspace_product_smoke_cli_accepts_hosted_managed_profile(self) -> None:
        workspace_payload = _specspace_smoke_workspace_payload(
            readiness_status="hosted_managed_ready",
            readiness_mode="hosted_managed",
        )
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--expect-managed-mode",
                "hosted_managed_ready",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["summary"]["ok"])
        checks = {item["id"]: item for item in payload["checks"]}
        self.assertEqual(checks["specspace_managed_mode_status"]["status"], "passed")
        self.assertEqual(checks["specspace_managed_mode_mode"]["status"], "passed")

    def test_specspace_product_smoke_cli_accepts_selected_workspace_id(self) -> None:
        workspace_payload = _specspace_smoke_workspace_payload()
        workspace_payload.pop("workspace")
        workspace_payload["selected_workspace_id"] = "team-decision-log"
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["summary"]["ok"])

    def test_specspace_product_smoke_cli_rejects_spoofed_hosted_ready_label(
        self,
    ) -> None:
        workspace_payload = _specspace_smoke_workspace_payload(
            readiness_status="hosted_managed_ready",
            readiness_mode="hosted_managed",
        )
        workspace_payload["managed_mode_readiness"]["executor"].update(
            {
                "configured": False,
                "hosted_service_reachable": False,
                "hosted_enabled_operation_ids": [],
            }
        )
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--expect-managed-mode",
                "hosted_managed_ready",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        diagnostic_ids = {item["code"] for item in payload["diagnostics"]}
        self.assertIn("specspace_hosted_executor_ready", diagnostic_ids)
        self.assertIn("specspace_hosted_operation_allowlist_enabled", diagnostic_ids)

    def test_specspace_product_smoke_cli_blocks_enabled_operations_in_read_only(
        self,
    ) -> None:
        workspace_payload = _specspace_smoke_workspace_payload(
            readiness_status="read_only",
            readiness_mode="read_only",
            enabled_operation_count=1,
        )
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["summary"]["ok"])
        self.assertIn(
            "specspace_managed_operations_disabled",
            {diagnostic["code"] for diagnostic in payload["diagnostics"]},
        )

    def test_specspace_product_smoke_cli_blocks_unknown_may_authority(self) -> None:
        workspace_payload = _specspace_smoke_workspace_payload()
        operations = workspace_payload["managed_operations_observability"]["operations"]
        operations[0]["authority_boundary"]["may_execute_prompt_agent"] = True
        with _SmokeServer(workspace_payload) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["summary"]["ok"])
        self.assertIn(
            "specspace_product_smoke_write_authority_enabled",
            {diagnostic["code"] for diagnostic in payload["diagnostics"]},
        )

    def test_specspace_product_smoke_cli_retries_restart_window_502(self) -> None:
        with _SmokeServer(
            _specspace_smoke_workspace_payload(),
            transient_failures={
                "/api/v1/health": 1,
                "/api/v1/idea-to-spec-workspace?workspace=team-decision-log": 1,
                "/team-decision-log": 1,
                "/team-decision-log?view=demo": 1,
            },
        ) as base_url:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--attempts",
                "2",
                "--retry-delay",
                "0",
                "--format",
                "json",
                "--no-write-report",
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["attempts"]["health"], 2)
        self.assertEqual(payload["summary"]["attempts"]["workspace"], 2)
        self.assertEqual(payload["summary"]["attempts"]["route"], 2)
        self.assertEqual(payload["summary"]["attempts"]["demo_view"], 2)

    def test_specspace_product_smoke_cli_blocks_legacy_demo_view_shell(self) -> None:
        class LegacyDemoHandler(_SpecSpaceSmokeHandler):
            workspace_payload = _specspace_smoke_workspace_payload()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/team-decision-log?view=demo":
                    self.send_response(200)
                    self.send_header("content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<html><body>legacy ContextBuilder</body></html>")
                    return
                super().do_GET()

        server = ThreadingHTTPServer(("127.0.0.1", 0), LegacyDemoHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base_url = f"http://{host}:{port}"
        try:
            result = self.run_cli(
                "specspace",
                "product-smoke",
                "--base-url",
                base_url,
                "--workspace",
                "team-decision-log",
                "--artifact-base-url",
                "https://specgraph.tech/workspaces/team-decision-log",
                "--format",
                "json",
                "--no-write-report",
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn(
            "specspace_product_demo_view_no_contextbuilder_legacy_shell",
            {diagnostic["code"] for diagnostic in payload["diagnostics"]},
        )

    def test_specspace_product_smoke_cli_writes_durable_report(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "runs" / "product-smoke.json"
            with _SmokeServer(_specspace_smoke_workspace_payload()) as base_url:
                result = self.run_cli(
                    "specspace",
                    "product-smoke",
                    "--base-url",
                    base_url,
                    "--workspace",
                    "team-decision-log",
                    "--artifact-base-url",
                    "https://specgraph.tech/workspaces/team-decision-log",
                    "--output",
                    str(output),
                    "--format",
                    "json",
                )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["artifact_kind"],
                "platform_specspace_product_workspace_production_smoke_report",
            )
            self.assertTrue(payload["summary"]["ok"])

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

    def test_deploy_hosted_managed_profile_adds_web_and_queue_overlays(self) -> None:
        result = self.run_cli(
            "deploy",
            "render",
            "--profile",
            "hosted-managed",
            "--dry-run",
            "--format",
            "json",
            env_overrides={"COMPOSE_PROJECT_NAME": None},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["compose_files"][-2:],
            [
                str(REPO_ROOT / "docker-compose.production-web.example.yml"),
                str(REPO_ROOT / "docker-compose.hosted-managed.example.yml"),
            ],
        )
        self.assertEqual(payload["command"].count("--file"), 3)

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
            self.assertIn(
                '  app:\n    image: "' + UI_IMAGE + '"\n    ports:\n      - "8080:80"',
                compose,
            )
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
            self.assertIn(
                '"team-decision-log=https://specgraph.tech/workspaces/team-decision-log"',
                compose,
            )
            self.assertIn(
                '"hosted-operation-canary=https://specgraph.tech/workspaces/hosted-operation-canary"',
                compose,
            )
            self.assertEqual(manifest["artifact_kind"], "platform_timeweb_deploy_manifest")
            self.assertEqual(manifest["release_commit"], "abc123")
            self.assertEqual(
                manifest["product_workspace_artifact_base_urls"],
                {
                    "hosted-operation-canary": (
                        "https://specgraph.tech/workspaces/hosted-operation-canary"
                    ),
                    "team-decision-log": (
                        "https://specgraph.tech/workspaces/team-decision-log"
                    )
                },
            )
            self.assertTrue(manifest["hyperprompt_http_compile_enabled"])
            self.assertEqual(manifest["hyperprompt_work_dir"], "/tmp")
            self.assertEqual(manifest["hyperprompt_compile_timeout_seconds"], "60")
            self.assertEqual(
                manifest["specspace_state_profile"],
                "read_only_no_mutable_state",
            )
            self.assertIn(
                "SpecSpace mutable state profile: `read_only_no_mutable_state`",
                (output_dir / "README.md").read_text(encoding="utf-8"),
            )

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

    def test_timeweb_render_can_enable_hosted_managed_execution(self) -> None:
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
                "--enable-hosted-managed-execution",
                "--hosted-managed-executor-url",
                "https://managed.specgraph.tech",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-execution",
                "--hosted-managed-executor-url",
                "https://managed.specgraph.tech",
                "--format",
                "json",
            )
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertIn("--enable-hosted-managed-execution", compose)
        self.assertIn(
            "environment: SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN",
            compose,
        )
        self.assertIn(
            "specspace-hosted-managed-state:/data/specspace-hosted-managed-state",
            compose,
        )
        self.assertNotIn("hosted-token-", compose)
        self.assertTrue(manifest["hosted_managed_execution_enabled"])
        self.assertEqual(
            manifest["specspace_state_profile"],
            "persistent_local_volume",
        )
        self.assertEqual(
            manifest["hosted_managed_executor_url"],
            "https://managed.specgraph.tech",
        )

    def test_timeweb_validate_requires_matching_hosted_profile(self) -> None:
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
                "--enable-hosted-managed-execution",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--disable-hosted-managed-execution",
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        self.assertFalse(json.loads(validate.stdout)["valid"])

    def test_timeweb_read_only_rejects_compose_secrets(self) -> None:
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
            compose_path.write_text(
                compose_path.read_text(encoding="utf-8").replace(
                    "    expose:\n      - \"8001\"\n",
                    "    secrets:\n"
                    "      - stale-secret\n"
                    "    expose:\n"
                    "      - \"8001\"\n",
                )
                + "\nsecrets:\n  stale-secret:\n    file: /tmp/stale-secret\n",
                encoding="utf-8",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        self.assertIn(
            "docker-compose.yml must not declare secrets",
            json.loads(validate.stdout)["errors"],
        )

    def test_timeweb_render_bounded_canary_is_sanitizer_compatible(self) -> None:
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
                "--enable-hosted-managed-bounded-canary",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-bounded-canary",
                "--format",
                "json",
            )
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertNotIn("\nvolumes:", compose)
        self.assertNotIn("\nsecrets:", compose)
        self.assertNotIn("--hosted-managed-executor-token-file", compose)
        self.assertNotIn("SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN", compose)
        self.assertIn(
            'SPECSPACE_HOSTED_MANAGED_STATE_DURABILITY: "ephemeral"',
            compose,
        )
        self.assertIn(
            'SPECSPACE_HOSTED_MANAGED_OPERATION_ALLOWLIST: "review_status_execute"',
            compose,
        )
        self.assertIn("/tmp/specspace-hosted-managed-state", compose)
        self.assertEqual(
            manifest["hosted_managed_execution_profile"],
            "timeweb_bounded_canary",
        )
        self.assertEqual(manifest["hosted_managed_state_durability"], "ephemeral")
        self.assertEqual(manifest["specspace_state_profile"], "ephemeral_canary")
        self.assertEqual(
            manifest["hosted_managed_operation_allowlist"],
            ["review_status_execute"],
        )
        self.assertEqual(
            manifest["required_runtime_environment_variables"],
            ["SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN"],
        )

    def test_timeweb_render_external_state_is_persistent_and_sanitizer_compatible(
        self,
    ) -> None:
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
                "--enable-hosted-managed-external-state",
                "--hosted-managed-executor-url",
                "https://managed.specgraph.tech",
                "--external-state-url",
                "https://managed.specgraph.tech/specspace-state",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-external-state",
                "--hosted-managed-executor-url",
                "https://managed.specgraph.tech",
                "--external-state-url",
                "https://managed.specgraph.tech/specspace-state",
                "--format",
                "json",
            )
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertNotIn("\nvolumes:", compose)
        self.assertNotIn("\nsecrets:", compose)
        self.assertNotIn("--hosted-managed-executor-token-file", compose)
        self.assertNotIn("--external-state-token-file", compose)
        self.assertNotIn("SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN", compose)
        self.assertNotIn("SPECSPACE_EXTERNAL_STATE_TOKEN", compose)
        self.assertIn(
            'SPECSPACE_EXTERNAL_STATE_URL: '
            '"https://managed.specgraph.tech/specspace-state"',
            compose,
        )
        self.assertIn(
            'SPECSPACE_HOSTED_MANAGED_STATE_DURABILITY: "persistent"',
            compose,
        )
        self.assertIn(
            'SPECSPACE_HOSTED_MANAGED_OPERATION_ALLOWLIST: "review_status_execute"',
            compose,
        )
        self.assertIn("--enable-external-state", compose)
        self.assertIn("/tmp/specspace-external-state-cache", compose)
        self.assertEqual(
            manifest["hosted_managed_execution_profile"],
            "timeweb_external_state",
        )
        self.assertEqual(manifest["hosted_managed_state_durability"], "persistent")
        self.assertEqual(manifest["specspace_state_profile"], "external_postgresql")
        self.assertTrue(manifest["specspace_external_state_enabled"])
        self.assertEqual(
            manifest["specspace_external_state_url"],
            "https://managed.specgraph.tech/specspace-state",
        )
        self.assertEqual(
            manifest["hosted_managed_operation_allowlist"],
            ["review_status_execute"],
        )
        self.assertEqual(
            manifest["required_runtime_environment_variables"],
            [
                "SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN",
                "SPECSPACE_EXTERNAL_STATE_TOKEN",
            ],
        )

    def test_timeweb_external_state_rejects_compose_secret_interpolation(
        self,
    ) -> None:
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
                "--enable-hosted-managed-external-state",
            )
            compose_path = output_dir / "docker-compose.yml"
            compose_path.write_text(
                compose_path.read_text(encoding="utf-8").replace(
                    '      SPECSPACE_EXTERNAL_STATE_ENABLED: "true"\n',
                    '      SPECSPACE_EXTERNAL_STATE_ENABLED: "true"\n'
                    "      SPECSPACE_EXTERNAL_STATE_TOKEN: "
                    '"${SPECSPACE_EXTERNAL_STATE_TOKEN}"\n',
                ),
                encoding="utf-8",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-external-state",
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        errors = json.loads(validate.stdout)["errors"]
        self.assertIn(
            "docker-compose.yml Timeweb hosted profile must receive "
            "SPECSPACE_EXTERNAL_STATE_TOKEN from the App Platform runtime and "
            "must not declare it in Compose",
            errors,
        )
        self.assertIn(
            "docker-compose.yml Timeweb hosted profile must not interpolate "
            "SPECSPACE_EXTERNAL_STATE_TOKEN through Compose",
            errors,
        )

    def test_timeweb_bounded_canary_rejects_forbidden_volume(self) -> None:
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
                "--enable-hosted-managed-bounded-canary",
            )
            compose_path = output_dir / "docker-compose.yml"
            compose_path.write_text(
                compose_path.read_text(encoding="utf-8").replace(
                    "    expose:\n      - \"8001\"\n",
                    "    volumes:\n      - state:/tmp/state\n"
                    "    expose:\n      - \"8001\"\n",
                )
                + "\nvolumes:\n  state:\n",
                encoding="utf-8",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-bounded-canary",
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        errors = json.loads(validate.stdout)["errors"]
        self.assertTrue(any("must not declare volumes" in error for error in errors))

    def test_timeweb_bounded_canary_rejects_empty_forbidden_sections(self) -> None:
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
                "--enable-hosted-managed-bounded-canary",
            )
            compose_path = output_dir / "docker-compose.yml"
            compose_path.write_text(
                compose_path.read_text(encoding="utf-8")
                + "\nvolumes: []\nsecrets: {}\n",
                encoding="utf-8",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-bounded-canary",
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        errors = json.loads(validate.stdout)["errors"]
        self.assertTrue(
            any("must not declare top-level volumes" in error for error in errors)
        )
        self.assertTrue(
            any("must not declare top-level secrets" in error for error in errors)
        )

    def test_timeweb_bounded_canary_rolls_back_to_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "timeweb"
            bounded = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--enable-hosted-managed-bounded-canary",
            )
            read_only = self.run_cli(
                "deploy",
                "timeweb-render",
                "--output-dir",
                str(output_dir),
                "--specspace-api-image-ref",
                API_IMAGE,
                "--specspace-ui-image-ref",
                UI_IMAGE,
                "--disable-hosted-managed-execution",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--disable-hosted-managed-execution",
                "--format",
                "json",
            )
            compose = (output_dir / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertEqual(bounded.returncode, 0, bounded.stderr)
        self.assertEqual(read_only.returncode, 0, read_only.stderr)
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertNotIn("SPECSPACE_HOSTED_MANAGED_", compose)
        self.assertNotIn("--enable-hosted-managed-execution", compose)
        self.assertNotIn("review_status_execute", compose)
        self.assertNotIn("/tmp/specspace-hosted-managed-state", compose)

    def test_timeweb_rejects_durable_and_bounded_profiles_together(self) -> None:
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
                "--enable-hosted-managed-execution",
                "--enable-hosted-managed-bounded-canary",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("mutually exclusive", result.stderr)

    def test_timeweb_rejects_bounded_and_external_state_profiles_together(
        self,
    ) -> None:
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
                "--enable-hosted-managed-bounded-canary",
                "--enable-hosted-managed-external-state",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("mutually exclusive", result.stderr)

    def test_timeweb_validate_rejects_extra_hosted_bind_volume(self) -> None:
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
                "--enable-hosted-managed-execution",
            )
            compose_path = output_dir / "docker-compose.yml"
            compose = compose_path.read_text(encoding="utf-8")
            compose_path.write_text(
                compose.replace(
                    "    depends_on:\n      - specspace-api\n",
                    "    depends_on:\n      - specspace-api\n"
                    "    volumes:\n      - /etc:/host-etc\n",
                ),
                encoding="utf-8",
            )
            validate = self.run_cli(
                "deploy",
                "timeweb-validate",
                "--path",
                str(output_dir),
                "--enable-hosted-managed-execution",
                "--format",
                "json",
            )

        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertEqual(validate.returncode, 1, validate.stderr)
        payload = json.loads(validate.stdout)
        self.assertIn(
            "docker-compose.yml hosted app must not declare volumes",
            payload["errors"],
        )

    def test_timeweb_render_rejects_non_https_hosted_executor(self) -> None:
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
                "--enable-hosted-managed-execution",
                "--hosted-managed-executor-url",
                "http://managed.specgraph.tech",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be an HTTPS origin", result.stderr)

    def test_timeweb_render_treats_bare_root_product_base_as_default(self) -> None:
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
                "--artifact-base-url",
                "https://specgraph.tech",
                "--product-workspace-artifact-base-url",
                "https://specgraph.tech",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["product_workspace_artifact_base_urls"],
                {
                    "team-decision-log": (
                        "https://specgraph.tech/workspaces/team-decision-log"
                    )
                },
            )

    def test_timeweb_render_keeps_explicit_root_product_binding(self) -> None:
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
                "--artifact-base-url",
                "https://specgraph.tech",
                "--product-workspace-artifact-base-url",
                "team-decision-log=https://specgraph.tech",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "platform-timeweb-deploy.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["product_workspace_artifact_base_urls"],
                {"team-decision-log": "https://specgraph.tech"},
            )

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
            '"${{ inputs.product_workspace_artifact_base_url }}"',
            workflow,
        )
        self.assertIn(
            "TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL: "
            "${{ inputs.product_workspace_artifact_base_url }}",
            workflow,
        )
        self.assertIn(
            'raw_product_workspace_artifact_base_url="'
            '${TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL:-',
            publish_script,
        )
        self.assertIn(
            '"$raw_product_workspace_artifact_base_url" != *=*',
            publish_script,
        )
        self.assertIn(
            'default_team_decision_log_artifact_base_url="'
            '${artifact_base_url%/}/workspaces/team-decision-log"',
            publish_script,
        )
        self.assertIn(
            'default_hosted_operation_canary_artifact_base_url="'
            '${artifact_base_url%/}/workspaces/hosted-operation-canary"',
            publish_script,
        )
        self.assertIn(
            '"hosted-operation-canary=$default_hosted_operation_canary_artifact_base_url"',
            publish_script,
        )
        self.assertIn("hosted_managed_execution_enabled:", workflow)
        self.assertIn("hosted_managed_bounded_canary_enabled:", workflow)
        self.assertIn("hosted_managed_external_state_enabled:", workflow)
        self.assertIn("external_state_url:", workflow)
        self.assertIn("TIMEWEB_REQUIRED_HOSTED_MANAGED_EXECUTION_ENABLED", workflow)
        self.assertIn(
            "TIMEWEB_REQUIRED_HOSTED_MANAGED_BOUNDED_CANARY_ENABLED",
            workflow,
        )
        self.assertIn(
            "TIMEWEB_REQUIRED_HOSTED_MANAGED_EXTERNAL_STATE_ENABLED",
            workflow,
        )
        self.assertIn("TIMEWEB_REQUIRED_EXTERNAL_STATE_URL", workflow)
        self.assertIn("TIMEWEB_REQUIRED_HOSTED_MANAGED_EXECUTION_ENABLED", publish_script)
        self.assertIn(
            "TIMEWEB_REQUIRED_HOSTED_MANAGED_BOUNDED_CANARY_ENABLED",
            publish_script,
        )
        self.assertIn(
            "TIMEWEB_REQUIRED_HOSTED_MANAGED_EXTERNAL_STATE_ENABLED",
            publish_script,
        )
        self.assertIn("TIMEWEB_REQUIRED_EXTERNAL_STATE_URL", publish_script)

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

    def test_timeweb_validate_rejects_mutable_state_in_read_only_profile(self) -> None:
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
            compose_path.write_text(
                compose_path.read_text(encoding="utf-8").replace(
                    f'      SPECSPACE_API_IMAGE_REF: "{API_IMAGE}"\n',
                    f'      SPECSPACE_API_IMAGE_REF: "{API_IMAGE}"\n'
                    '      SPECSPACE_STATE_DIR: "/data/specspace-state"\n',
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
        self.assertEqual(result.returncode, 1, result.stderr)
        errors = json.loads(result.stdout)["errors"]
        self.assertTrue(
            any(
                "read-only profile must not configure persistent mutable state"
                in error
                and "SPECSPACE_STATE_DIR" in error
                for error in errors
            )
        )

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

    def test_timeweb_validate_rejects_old_app_host_port_binding(self) -> None:
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
                    '      - "8080:80"\n',
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
                "app must not publish old conflicting host port 5173" in error
                for error in payload["errors"]
            )
        )

    def test_timeweb_validate_rejects_env_default_old_app_host_port_binding(self) -> None:
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
                    '      - "8080:80"\n',
                    '      - "${SPECSPACE_UI_PORT:-127.0.0.1:5173}:80"\n',
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
                "app must not publish old conflicting host port 5173" in error
                for error in payload["errors"]
            )
        )

    def test_timeweb_validate_rejects_app_reserved_host_port_binding(self) -> None:
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
                compose.replace('      - "8080:80"\n', '      - "80:80"\n', 1),
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
                "app must not publish Timeweb-reserved host ports" in error
                for error in payload["errors"]
            )
        )

    def test_timeweb_validate_rejects_extra_app_host_port_binding(self) -> None:
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
                    '      - "8080:80"\n',
                    '      - "8080:80"\n      - "9090:80"\n',
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
                "app must publish exactly one Timeweb port binding 8080:80" in error
                for error in payload["errors"]
            )
        )
