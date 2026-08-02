import argparse
from dataclasses import replace
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
        self.assertNotIn("SPECSPACE_E2E_OPERATOR_USERNAME", env)
        self.assertNotIn("SPECSPACE_E2E_OPERATOR_PASSWORD", env)

    def test_ui_environment_does_not_inherit_e2e_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            with mock.patch.dict(
                os.environ,
                {
                    "DATABASE_PASSWORD": "database-secret",
                    "GITHUB_TOKEN": "github-secret",
                    "SPECSPACE_E2E_OPERATOR_USERNAME": "operator",
                    "SPECSPACE_E2E_OPERATOR_PASSWORD": "secret",
                },
            ):
                env = mac_product_workspace._ui_environment(config)

        self.assertEqual(env["SPECSPACE_API_PORT"], "8001")
        self.assertNotIn("SPECSPACE_E2E_OPERATOR_USERNAME", env)
        self.assertNotIn("SPECSPACE_E2E_OPERATOR_PASSWORD", env)
        self.assertNotIn("DATABASE_PASSWORD", env)
        self.assertNotIn("GITHUB_TOKEN", env)

    def test_managed_profile_readiness_requires_authenticated_ready_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            health = {
                "operator_access_control": {
                    "enabled": True,
                    "operator_authenticated": True,
                    "private_state_requires_operator": True,
                    "managed_operations_require_operator": True,
                }
            }
            with mock.patch.object(
                mac_product_workspace,
                "_authenticated_json",
                side_effect=[health, {"managed_mode_readiness": {"status": "backend_managed_ready"}}],
            ):
                self.assertTrue(
                    mac_product_workspace._managed_profile_ready(
                        config,
                        operator_password="secret",
                    )
                )
            with mock.patch.object(
                mac_product_workspace,
                "_authenticated_json",
                side_effect=[health, {"managed_mode_readiness": {"status": "backend_managed_misconfigured"}}],
            ):
                self.assertFalse(
                    mac_product_workspace._managed_profile_ready(
                        config,
                        operator_password="secret",
                    )
                )

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

    @mock.patch.object(mac_product_workspace.os, "killpg")
    @mock.patch.object(mac_product_workspace, "_process_is_owned")
    @mock.patch.object(
        mac_product_workspace,
        "_running_command",
        return_value="python owned-or-foreign",
    )
    @mock.patch.object(mac_product_workspace, "_load_process_manifest")
    def test_stop_preflights_every_process_before_signaling(
        self,
        load_manifest: mock.Mock,
        _running_command: mock.Mock,
        process_is_owned: mock.Mock,
        killpg: mock.Mock,
    ) -> None:
        load_manifest.return_value = [
            mac_product_workspace.OwnedProcess(
                "backend", 101, ("viewer/server.py",), "/tmp/backend.log"
            ),
            mac_product_workspace.OwnedProcess(
                "ui", 102, ("npm", "run", "dev"), "/tmp/ui.log"
            ),
        ]
        process_is_owned.side_effect = [True, False]
        with tempfile.TemporaryDirectory() as tmp:
            ok, errors = mac_product_workspace._stop_owned_processes(
                self._config(Path(tmp))
            )

        self.assertFalse(ok)
        self.assertEqual(len(errors), 1)
        killpg.assert_not_called()

    @mock.patch.object(mac_product_workspace.os, "killpg")
    @mock.patch.object(mac_product_workspace, "_process_is_zombie", return_value=True)
    @mock.patch.object(mac_product_workspace, "_process_is_owned", return_value=True)
    @mock.patch.object(
        mac_product_workspace,
        "_running_command",
        return_value="python viewer/server.py --port 8001",
    )
    @mock.patch.object(mac_product_workspace, "_load_process_manifest")
    def test_stop_treats_signaled_zombie_as_stopped(
        self,
        load_manifest: mock.Mock,
        _running_command: mock.Mock,
        _process_is_owned: mock.Mock,
        _process_is_zombie: mock.Mock,
        killpg: mock.Mock,
    ) -> None:
        process = mac_product_workspace.OwnedProcess(
            "backend",
            999,
            ("viewer/server.py", "8001"),
            "/tmp/backend.log",
        )
        load_manifest.return_value = [process]
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            config.runtime_dir.mkdir(parents=True)
            mac_product_workspace._write_process_manifest(config, [process])
            ok, errors = mac_product_workspace._stop_owned_processes(config)
            manifest_exists = mac_product_workspace._process_manifest_path(
                config
            ).exists()

        self.assertTrue(ok)
        self.assertEqual(errors, [])
        killpg.assert_called_once_with(999, mac_product_workspace.signal.SIGTERM)
        self.assertFalse(manifest_exists)

    @mock.patch.object(mac_product_workspace, "_emit", return_value=0)
    @mock.patch.object(
        mac_product_workspace,
        "_service_healthy",
        side_effect=[True, True, False, False, False, False],
    )
    @mock.patch.object(
        mac_product_workspace,
        "_stop_owned_processes",
        return_value=(True, []),
    )
    def test_stop_waits_for_profile_health_to_clear(
        self,
        stop_owned: mock.Mock,
        service_healthy: mock.Mock,
        emit: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            result = mac_product_workspace.control(
                config,
                command="stop",
                output_format="json",
            )

        self.assertEqual(result, 0)
        stop_owned.assert_called_once_with(config)
        self.assertEqual(service_healthy.call_count, 6)
        self.assertTrue(emit.call_args.args[0]["ok"])
        self.assertEqual(
            emit.call_args.args[0]["runtime_dir"],
            str(config.runtime_dir),
        )

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

    def test_readiness_rejects_existing_non_directory_runs_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            config.specgraph_runs_dir.parent.mkdir(parents=True, exist_ok=True)
            config.specgraph_runs_dir.write_text("not a directory", encoding="utf-8")
            checks = {
                check.check_id: check
                for check in mac_product_workspace.readiness_checks(config)
            }

        self.assertFalse(checks["specgraph_runs_destination_writable"].ok)

    def test_local_empty_workspace_catalog_is_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            mac_product_workspace._ensure_local_workspace_catalog(config)

            self.assertIsNone(
                mac_product_workspace._workspace_catalog_contract_error(
                    config.product_workspace_catalog
                )
            )

    def test_readiness_rejects_malformed_existing_workspace_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            config.product_workspace_catalog.parent.mkdir(parents=True)
            config.product_workspace_catalog.write_text("workspaces: [", encoding="utf-8")
            checks = {
                check.check_id: check
                for check in mac_product_workspace.readiness_checks(config)
            }

        self.assertFalse(checks["product_workspace_catalog_valid"].ok)

    def test_manifest_binds_active_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            config.runtime_dir.mkdir(parents=True)
            processes = [
                mac_product_workspace.OwnedProcess(
                    "backend", 101, ("viewer/server.py",), "/tmp/backend.log"
                ),
                mac_product_workspace.OwnedProcess(
                    "ui", 102, ("npm",), "/tmp/ui.log"
                ),
            ]
            mac_product_workspace._write_process_manifest(config, processes)
            changed = replace(
                config,
                specgraph_runs_dir=config.specgraph_dir / "other-runs",
            )

            self.assertTrue(
                mac_product_workspace._manifest_configuration_matches(config)
            )
            self.assertFalse(
                mac_product_workspace._manifest_configuration_matches(changed)
            )

    @mock.patch.object(mac_product_workspace, "_emit", return_value=1)
    @mock.patch.object(
        mac_product_workspace,
        "_service_healthy",
        side_effect=[True, False],
    )
    @mock.patch.object(
        mac_product_workspace,
        "_all_manifest_processes_owned",
        return_value=True,
    )
    def test_status_reports_partial_profile_as_not_stopped(
        self,
        _owned: mock.Mock,
        _service_healthy: mock.Mock,
        emit: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mac_product_workspace.control(
                self._config(Path(tmp)),
                command="status",
                output_format="json",
            )

        payload = emit.call_args.args[0]
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "partial_profile")

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

    @mock.patch.object(mac_product_workspace, "control", return_value=0)
    @mock.patch.object(mac_product_workspace, "start", return_value=0)
    @mock.patch.object(mac_product_workspace.subprocess, "run")
    @mock.patch.object(
        mac_product_workspace.platform_cli,
        "specspace_product_smoke_password_from_keychain",
        return_value="keychain-secret",
    )
    def test_restart_e2e_passes_keychain_password_only_to_playwright(
        self,
        password_from_keychain: mock.Mock,
        run: mock.Mock,
        start: mock.Mock,
        control: mock.Mock,
    ) -> None:
        captured_child_env: dict[str, str] = {}

        def capture_run(*_args: object, **kwargs: object) -> mock.Mock:
            captured_child_env.update(dict(kwargs["env"]))
            return mock.Mock(returncode=0)

        run.side_effect = capture_run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            artifact_dir = root / "SpecSpace" / "graphspace" / "test-results" / "e2e"
            with mock.patch.dict(
                os.environ,
                {"SPECSPACE_MAC_E2E_ARTIFACT_DIR": str(artifact_dir)},
                clear=True,
            ):
                result = mac_product_workspace.run_restart_e2e(
                    config,
                    output_format="json",
                )

        self.assertEqual(result, 0)
        password_from_keychain.assert_called_once_with(
            service=config.keychain_service,
            account=config.operator_username,
        )
        e2e_config = start.call_args.args[0]
        self.assertNotIn(
            "SPECSPACE_E2E_OPERATOR_PASSWORD",
            mac_product_workspace._runtime_environment(e2e_config),
        )
        self.assertEqual(
            captured_child_env["SPECSPACE_E2E_OPERATOR_PASSWORD"],
            "keychain-secret",
        )
        self.assertEqual(
            captured_child_env["SPECSPACE_STATE_DIR"],
            str(e2e_config.state_dir),
        )
        self.assertEqual(
            captured_child_env["SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR"],
            str(e2e_config.product_workspace_root_dir),
        )
        self.assertEqual(
            captured_child_env["SPECSPACE_PRODUCT_WORKSPACE_CATALOG"],
            str(e2e_config.product_workspace_catalog),
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["SPECSPACE_E2E_OPERATOR_PASSWORD"],
            "",
        )
        self.assertNotIn("keychain-secret", repr(run.call_args.args[0]))
        self.assertNotIn("keychain-secret", repr(run.call_args.kwargs["cwd"]))
        control.assert_called_once_with(
            e2e_config,
            command="stop",
            output_format="json",
        )

    @mock.patch.object(mac_product_workspace, "control", return_value=1)
    @mock.patch.object(mac_product_workspace, "start", return_value=0)
    @mock.patch.object(
        mac_product_workspace.subprocess,
        "run",
        return_value=mock.Mock(returncode=0),
    )
    @mock.patch.object(
        mac_product_workspace.platform_cli,
        "specspace_product_smoke_password_from_keychain",
        return_value="keychain-secret",
    )
    def test_restart_e2e_fails_when_profile_cleanup_fails(
        self,
        _password_from_keychain: mock.Mock,
        _run: mock.Mock,
        _start: mock.Mock,
        _control: mock.Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            artifact_dir = root / "SpecSpace" / "graphspace" / "test-results" / "e2e"
            with mock.patch.dict(
                os.environ,
                {"SPECSPACE_MAC_E2E_ARTIFACT_DIR": str(artifact_dir)},
                clear=True,
            ):
                result = mac_product_workspace.run_restart_e2e(
                    config,
                    output_format="json",
                )

        self.assertEqual(result, 1)

    def test_e2e_config_preserves_configured_runs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            isolated_runs = Path(tmp) / "isolated-runs"
            config = replace(config, specgraph_runs_dir=isolated_runs)
            e2e_config, _artifact_dir = mac_product_workspace._e2e_config(config)

        self.assertEqual(e2e_config.specgraph_runs_dir, isolated_runs)

    def test_e2e_config_rejects_broad_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            trusted_root = config.specspace_dir / "graphspace" / "test-results"
            with mock.patch.dict(
                os.environ,
                {"SPECSPACE_MAC_E2E_ARTIFACT_DIR": str(trusted_root)},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    mac_product_workspace.platform_cli.PlatformError,
                    "one dedicated child",
                ):
                    mac_product_workspace._e2e_config(config)

    def test_e2e_config_rejects_symlinked_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(Path(tmp))
            trusted_root = config.specspace_dir / "graphspace" / "test-results"
            trusted_root.mkdir(parents=True)
            foreign = Path(tmp) / "foreign"
            foreign.mkdir()
            artifact_dir = trusted_root / "linked-run"
            artifact_dir.symlink_to(foreign, target_is_directory=True)
            with mock.patch.dict(
                os.environ,
                {"SPECSPACE_MAC_E2E_ARTIFACT_DIR": str(artifact_dir)},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    mac_product_workspace.platform_cli.PlatformError,
                    "symlinked E2E artifact directory",
                ):
                    mac_product_workspace._e2e_config(config)

    def test_remove_e2e_tree_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent"
            parent.mkdir()
            foreign = root / "foreign"
            foreign.mkdir()
            target = parent / "workspace"
            target.symlink_to(foreign, target_is_directory=True)

            with self.assertRaisesRegex(
                mac_product_workspace.platform_cli.PlatformError,
                "symlinked E2E path",
            ):
                mac_product_workspace._remove_e2e_tree(target, parent=parent)


if __name__ == "__main__":
    unittest.main()
