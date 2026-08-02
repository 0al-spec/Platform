import argparse
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import mac_product_workspace


class MacProductWorkspaceTests(unittest.TestCase):
    def _config(self, root: Path) -> mac_product_workspace.MacProductConfig:
        platform_dir = root / "Platform"
        specgraph_dir = root / "SpecGraph"
        specspace_dir = root / "SpecSpace"
        dialog_dir = root / "ChatGPTDialogs" / "canonical_json"
        for path in (
            platform_dir / ".venv" / "bin",
            specgraph_dir / "specs" / "nodes",
            specspace_dir / "scripts",
            specspace_dir / "graphspace" / "node_modules",
            dialog_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        (platform_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (specspace_dir / "viewer").mkdir(parents=True, exist_ok=True)
        (specspace_dir / "viewer" / "server.py").write_text("", encoding="utf-8")
        return mac_product_workspace.MacProductConfig(
            org_root=root,
            platform_dir=platform_dir,
            specgraph_dir=specgraph_dir,
            specgraph_runs_dir=specgraph_dir / "runs",
            specspace_dir=specspace_dir,
            dialog_dir=dialog_dir,
            state_dir=root / "persistent" / "state",
            product_workspace_root_dir=root / "persistent" / "workspaces",
            product_workspace_catalog=root / "persistent" / "workspaces.local.yaml",
            runtime_dir=root / "runtime",
            api_port=8001,
            ui_port=5175,
            operator_username="operator",
            keychain_service="0AL SpecSpace local operator",
        )

    def test_runtime_environment_enables_local_managed_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            env = mac_product_workspace._runtime_environment(config)

        self.assertEqual(env["SPECSPACE_PLATFORM_EXECUTION_ENABLED"], "true")
        self.assertEqual(env["SPECSPACE_HOSTED_MANAGED_EXECUTION_ENABLED"], "false")
        self.assertEqual(env["SPECSPACE_PLATFORM_DIR"], str(config.platform_dir))
        self.assertEqual(env["SPECSPACE_STATE_DIR"], str(config.state_dir))
        self.assertEqual(env["SPECGRAPH_RUNS_DIR"], str(config.specgraph_runs_dir))
        self.assertEqual(
            env["SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR"],
            str(config.product_workspace_root_dir),
        )
        self.assertEqual(
            env["SPECSPACE_PRODUCT_WORKSPACE_CATALOG"],
            str(config.product_workspace_catalog),
        )
        self.assertNotIn("SPECSPACE_OPERATOR_AUTH_PASSWORD", env)
        self.assertNotIn("SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN", env)

    @mock.patch.object(mac_product_workspace, "readiness_checks")
    @mock.patch.object(mac_product_workspace, "_already_running_payload", return_value=None)
    @mock.patch.object(mac_product_workspace, "_wait_for_profile", return_value=True)
    @mock.patch.object(
        mac_product_workspace.platform_cli,
        "specspace_product_smoke_password_from_keychain",
        return_value="x" * 64,
    )
    @mock.patch.object(mac_product_workspace, "_start_process")
    def test_start_reads_keychain_and_removes_materialized_password(
        self,
        start_process: mock.Mock,
        password_from_keychain: mock.Mock,
        _wait: mock.Mock,
        _already_running: mock.Mock,
        readiness: mock.Mock,
    ) -> None:
        start_process.side_effect = [
            mac_product_workspace.OwnedProcess(
                "backend",
                101,
                ("viewer/server.py", "8001"),
                "/tmp/backend.log",
            ),
            mac_product_workspace.OwnedProcess(
                "ui",
                102,
                ("npm", "run", "dev", "5175"),
                "/tmp/ui.log",
            ),
        ]
        readiness.return_value = [
            mac_product_workspace.ReadinessCheck("ready", True, "ready")
        ]
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            with mock.patch.object(mac_product_workspace, "_emit", return_value=0):
                result = mac_product_workspace.start(config, output_format="json")
            password_files = list(config.runtime_dir.glob("operator-auth-*"))
            catalog_exists = config.product_workspace_catalog.is_file()
            catalog_text = config.product_workspace_catalog.read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        password_from_keychain.assert_called_once_with(
            service=config.keychain_service,
            account=config.operator_username,
        )
        self.assertEqual(password_files, [])
        backend_command = start_process.call_args_list[0].kwargs["command"]
        password_arg = Path(
            backend_command[backend_command.index("--operator-auth-password-file") + 1]
        )
        self.assertFalse(password_arg.exists())
        self.assertEqual(
            backend_command[backend_command.index("--runs-dir") + 1],
            str(config.specgraph_runs_dir),
        )
        self.assertEqual(
            backend_command[
                backend_command.index("--product-workspace-root-dir") + 1
            ],
            str(config.product_workspace_root_dir),
        )
        self.assertEqual(
            backend_command[backend_command.index("--product-workspace-catalog") + 1],
            str(config.product_workspace_catalog),
        )
        self.assertTrue(catalog_exists)
        self.assertIn(
            "artifact_kind: platform_workspace_catalog",
            catalog_text,
        )
        self.assertEqual(
            start_process.call_args_list[1].kwargs["env"]["SPECSPACE_API_PORT"],
            "8001",
        )
        self.assertEqual(start_process.call_count, 2)

    @mock.patch.object(mac_product_workspace.os, "killpg")
    @mock.patch.object(mac_product_workspace, "_running_command")
    @mock.patch.object(mac_product_workspace, "_load_process_manifest")
    def test_stop_refuses_command_ownership_mismatch(
        self,
        load_manifest: mock.Mock,
        running_command: mock.Mock,
        killpg: mock.Mock,
    ) -> None:
        process = mac_product_workspace.OwnedProcess(
            "backend",
            999,
            ("viewer/server.py", "8001"),
            "/tmp/backend.log",
        )
        load_manifest.return_value = [process]
        running_command.return_value = "python unrelated-server.py"
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            ok, errors = mac_product_workspace._stop_owned_processes(config)

        self.assertFalse(ok)
        self.assertIn("ownership mismatch", errors[0])
        killpg.assert_not_called()

    def test_configuration_defaults_to_sibling_checkouts_and_persistent_mac_state(self) -> None:
        args = argparse.Namespace(
            api_port=8001,
            ui_port=5175,
            operator_auth_username="operator",
            operator_auth_keychain_service="0AL SpecSpace local operator",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            config = mac_product_workspace.config_from_environment(args)

        self.assertEqual(config.platform_dir, mac_product_workspace.REPO_ROOT)
        self.assertEqual(config.specgraph_dir, mac_product_workspace.REPO_ROOT.parent / "SpecGraph")
        self.assertEqual(config.specgraph_runs_dir, config.specgraph_dir / "runs")
        self.assertEqual(config.specspace_dir, mac_product_workspace.REPO_ROOT.parent / "SpecSpace")
        self.assertIn("Application Support/0AL/SpecSpace/state", str(config.state_dir))
        self.assertIn(
            "Application Support/0AL/SpecSpace/workspaces",
            str(config.product_workspace_root_dir),
        )
        self.assertIn(
            "Application Support/0AL/SpecSpace/workspaces.local.yaml",
            str(config.product_workspace_catalog),
        )

    def test_configuration_accepts_isolated_specgraph_runs_directory(self) -> None:
        args = argparse.Namespace(
            api_port=8001,
            ui_port=5175,
            operator_auth_username="operator",
            operator_auth_keychain_service="0AL SpecSpace local operator",
        )
        with tempfile.TemporaryDirectory() as tmp:
            isolated_runs = Path(tmp) / "isolated" / "runs"
            with mock.patch.dict(
                os.environ,
                {"SPECGRAPH_RUNS_DIR": str(isolated_runs)},
                clear=True,
            ):
                config = mac_product_workspace.config_from_environment(args)

        self.assertEqual(config.specgraph_runs_dir, isolated_runs.resolve())

    def test_workspace_catalog_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            target = Path(tmp) / "foreign.yaml"
            target.write_text("foreign\n", encoding="utf-8")
            config.product_workspace_catalog.parent.mkdir(parents=True, exist_ok=True)
            config.product_workspace_catalog.symlink_to(target)

            with self.assertRaisesRegex(
                mac_product_workspace.platform_cli.PlatformError,
                "not a regular file",
            ):
                mac_product_workspace._ensure_local_workspace_catalog(config)
            self.assertEqual(target.read_text(encoding="utf-8"), "foreign\n")


if __name__ == "__main__":
    unittest.main()
