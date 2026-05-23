import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "platform.py"
FAKE_SUPERVISOR = REPO_ROOT / "tests" / "fixtures" / "fake_specgraph_supervisor.py"


@contextlib.contextmanager
def specgraph_home(outcome: str = "ready"):
    with tempfile.TemporaryDirectory() as base:
        home = Path(base) / "SpecGraph"
        (home / "tools").mkdir(parents=True)
        target = home / "tools" / "supervisor.py"
        target.write_bytes(FAKE_SUPERVISOR.read_bytes())
        target.chmod(0o755)

        argv_log = Path(base) / "argv.log"
        env = {
            "SPECGRAPH_HOME": str(home),
            "FAKE_SUPERVISOR_OUTCOME": outcome,
            "FAKE_SUPERVISOR_ARGV_LOG": str(argv_log),
        }
        yield env, argv_log


class PlatformInitTests(unittest.TestCase):
    def run_cli(
        self,
        *args: str,
        env_overrides: dict[str, str | None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PLATFORM_WORKSPACES_CATALOG", None)
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

    def _read_argv_log(self, log_path: Path) -> list[list[str]]:
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_init_happy_path_writes_catalog(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            workspace = f"${{ORG_ROOT}}/ProductOne"

            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "product-one",
                "--path",
                workspace,
                "--display-name",
                "Product One",
                "--catalog",
                str(catalog),
                "--format",
                "json",
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["catalog_written"])
            self.assertEqual(payload["report_status"], "initialized")
            self.assertEqual(payload["diagnostics"], [])

            import yaml

            data = yaml.safe_load(catalog.read_text())
            entries = data["workspaces"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["project_id"], "product-one")
            self.assertEqual(entries[0]["governance_profile"], "product_workspace")
            self.assertTrue(entries[0]["path"].startswith("${ORG_ROOT}/"))

    def test_init_passes_args_to_supervisor(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "with-spaces",
                "--path",
                "${ORG_ROOT}/WithSpaces",
                "--display-name",
                "Display With Spaces",
                "--root-intent",
                "intent with \"quotes\" and spaces",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            invocations = self._read_argv_log(argv_log)
            self.assertEqual(len(invocations), 1)
            argv = invocations[0]
            self.assertIn("--display-name", argv)
            self.assertEqual(argv[argv.index("--display-name") + 1], "Display With Spaces")
            self.assertIn("--root-intent", argv)
            self.assertEqual(
                argv[argv.index("--root-intent") + 1],
                'intent with "quotes" and spaces',
            )

    def test_init_defaults_display_name_to_project_id(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "no-display",
                "--path",
                "${ORG_ROOT}/NoDisplay",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            invocations = self._read_argv_log(argv_log)
            argv = invocations[0]
            self.assertEqual(argv[argv.index("--display-name") + 1], "no-display")

    def test_init_blocked_report_does_not_write_catalog(self) -> None:
        with specgraph_home("blocked") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "blocked-one",
                "--path",
                "${ORG_ROOT}/BlockedOne",
                "--catalog",
                str(catalog),
                "--format",
                "json",
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 1)
            self.assertFalse(catalog.exists())
            payload = json.loads(result.stdout)
            self.assertFalse(payload["catalog_written"])
            self.assertEqual(payload["report_status"], "blocked")
            codes = {d["code"] for d in payload["diagnostics"]}
            self.assertIn("fake_blocker", codes)

    def test_init_supervisor_nonzero_exit(self) -> None:
        with specgraph_home("crash") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "crash-one",
                "--path",
                "${ORG_ROOT}/CrashOne",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 1)
            self.assertFalse(catalog.exists())
            self.assertIn("simulated crash", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_init_missing_supervisor_reports_paths(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            empty_home = Path(base) / "EmptyHome"
            empty_home.mkdir()
            catalog = Path(base) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "no-spec",
                "--path",
                "${ORG_ROOT}/NoSpec",
                "--catalog",
                str(catalog),
                env_overrides={
                    "ORG_ROOT": base,
                    "SPECGRAPH_HOME": str(empty_home),
                },
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("SPECGRAPH_HOME is set but no supervisor", result.stderr)
            self.assertIn(str(empty_home), result.stderr)

    def test_init_duplicate_project_id_rejected(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            catalog.write_text(
                "schema_version: 1\n"
                "artifact_kind: platform_workspace_catalog\n"
                'organization_root: "${ORG_ROOT}"\n'
                "workspaces:\n"
                "  - project_id: duplicate\n"
                "    display_name: Duplicate\n"
                "    kind: product_workspace\n"
                "    status: active\n"
                '    path: "${ORG_ROOT}/Duplicate"\n'
                "    governance_profile: product_workspace\n"
                "    specgraph_config: specgraph.project.yaml\n"
                "    provider:\n"
                "      type: local_filesystem\n"
                "      specs_root: specs\n"
                "      runs_root: runs\n",
                encoding="utf-8",
            )
            before = catalog.read_text()

            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "duplicate",
                "--path",
                "${ORG_ROOT}/Different",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("already in catalog", result.stderr)
            self.assertEqual(catalog.read_text(), before)
            self.assertEqual(self._read_argv_log(argv_log), [])

    def test_init_invalid_project_id_rejected(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "Has Space",
                "--path",
                "${ORG_ROOT}/HasSpace",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid project_id", result.stderr)
            self.assertEqual(self._read_argv_log(argv_log), [])

    def test_init_refuses_non_empty_target_directory(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            target = Path(org) / "ExistingProduct"
            target.mkdir()
            (target / "junk.txt").write_text("not empty")

            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "existing-product",
                "--path",
                "${ORG_ROOT}/ExistingProduct",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("not empty", result.stderr)
            self.assertEqual(self._read_argv_log(argv_log), [])

    def test_init_dry_run_skips_subprocess_and_catalog(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "dry-run",
                "--path",
                "${ORG_ROOT}/DryRun",
                "--catalog",
                str(catalog),
                "--dry-run",
                "--format",
                "json",
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(catalog.exists())
            self.assertEqual(self._read_argv_log(argv_log), [])
            payload = json.loads(result.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["pending_entry"]["project_id"], "dry-run")
            self.assertIn("--project-id", payload["command"])

    def test_init_creates_catalog_from_example_when_absent(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.local.yaml"
            self.assertFalse(catalog.exists())

            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "fresh",
                "--path",
                "${ORG_ROOT}/Fresh",
                "--catalog",
                str(catalog),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(catalog.exists())
            import yaml

            data = yaml.safe_load(catalog.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertIn("registries", data)
            ids = [w["project_id"] for w in data["workspaces"]]
            self.assertEqual(ids, ["fresh"])

    def test_init_refuses_to_write_example_catalog(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            example = REPO_ROOT / "workspaces.example.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "bad-target",
                "--path",
                "${ORG_ROOT}/BadTarget",
                "--catalog",
                str(example),
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to write tracked example catalog", result.stderr)
            self.assertEqual(self._read_argv_log(argv_log), [])

    def test_init_json_output_stays_clean_when_supervisor_is_chatty(self) -> None:
        with specgraph_home("chatty") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "chatty-product",
                "--path",
                "${ORG_ROOT}/ChattyProduct",
                "--catalog",
                str(catalog),
                "--format",
                "json",
                env_overrides={**env, "ORG_ROOT": org},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["catalog_written"])
            self.assertIn("starting initialization", result.stderr)
            self.assertNotIn("starting initialization", result.stdout)

    def test_init_supervisor_timeout_exits_with_runtime_failure(self) -> None:
        with specgraph_home("hang") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            catalog = Path(org) / "workspaces.yaml"
            result = self.run_cli(
                "workspace",
                "init",
                "--project-id",
                "hang-product",
                "--path",
                "${ORG_ROOT}/HangProduct",
                "--catalog",
                str(catalog),
                env_overrides={
                    **env,
                    "ORG_ROOT": org,
                    "PLATFORM_INIT_TIMEOUT_SECONDS": "0.5",
                    "FAKE_SUPERVISOR_HANG_SECONDS": "5",
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("timed out", result.stderr)
            self.assertFalse(catalog.exists())

    def test_init_recovery_snippet_uses_correct_yaml_key(self) -> None:
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            readonly_dir = Path(org) / "ro"
            readonly_dir.mkdir()
            catalog = readonly_dir / "workspaces.yaml"
            readonly_dir.chmod(0o500)
            try:
                result = self.run_cli(
                    "workspace",
                    "init",
                    "--project-id",
                    "snippet-check",
                    "--path",
                    "${ORG_ROOT}/SnippetCheck",
                    "--catalog",
                    str(catalog),
                    env_overrides={**env, "ORG_ROOT": org},
                )
            finally:
                readonly_dir.chmod(0o700)

            self.assertEqual(result.returncode, 1)
            self.assertIn("under workspaces:\n", result.stderr)
            self.assertNotIn("under workspaces::", result.stderr)

    def test_init_recovery_snippet_on_catalog_write_failure(self) -> None:
        # Trigger an OSError during catalog write by pointing --catalog at a
        # path whose parent directory is read-only.
        with specgraph_home("ready") as (env, argv_log), tempfile.TemporaryDirectory() as org:
            readonly_dir = Path(org) / "readonly"
            readonly_dir.mkdir()
            catalog = readonly_dir / "workspaces.yaml"
            readonly_dir.chmod(0o500)
            try:
                result = self.run_cli(
                    "workspace",
                    "init",
                    "--project-id",
                    "recover-me",
                    "--path",
                    "${ORG_ROOT}/RecoverMe",
                    "--catalog",
                    str(catalog),
                    env_overrides={**env, "ORG_ROOT": org},
                )
            finally:
                readonly_dir.chmod(0o700)

            self.assertEqual(result.returncode, 1)
            self.assertIn("Add this entry manually", result.stderr)
            self.assertIn("recover-me", result.stderr)


if __name__ == "__main__":
    unittest.main()
