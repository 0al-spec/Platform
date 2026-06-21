import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "platform.py"


CATALOG = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - project_id: specgraph-core
    display_name: SpecGraph Core
    kind: core_repository
    status: active
    path: "${ORG_ROOT}/SpecGraph"
    governance_profile: self_hosted_bootstrap
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: archived
    path: "${ORG_ROOT}/ProductA"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""


class PlatformCliTests(unittest.TestCase):
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

    def write_graph_repository_run_artifacts(
        self,
        runs_dir: Path,
        *,
        candidate_authority_expanded: bool = False,
        repair_ready: bool = True,
        context_required_count: int = 0,
    ) -> None:
        artifacts = {
            "idea_event_storming_intake.json": {
                "schema_version": 1,
                "artifact_kind": "idea_event_storming_intake",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "review_state": "review_ready",
            },
            "candidate_spec_graph.json": {
                "schema_version": 1,
                "artifact_kind": "candidate_spec_graph",
                "canonical_mutations_allowed": candidate_authority_expanded,
                "tracked_artifacts_written": False,
                "pre_sib_readiness": {
                    "ready": True,
                    "review_state": "ready",
                },
            },
            "pre_sib_coherence_report.json": {
                "schema_version": 1,
                "artifact_kind": "pre_sib_coherence_report",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": True,
                    "review_state": "ready",
                },
            },
            "candidate_repair_loop_report.json": {
                "schema_version": 1,
                "artifact_kind": "candidate_repair_loop_report",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": repair_ready,
                    "review_state": "ready" if repair_ready else "context_required",
                },
                "summary": {
                    "context_required_count": context_required_count,
                },
            },
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_workspace_list_json(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(CATALOG)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["workspaces"]), 2)
        self.assertEqual(payload["workspaces"][0]["project_id"], "specgraph-core")
        self.assertEqual(payload["workspaces"][1]["status"], "archived")

    def test_workspace_list_filters_kind_and_status(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(CATALOG)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
                "--kind",
                "product_workspace",
                "--status",
                "archived",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("product-a", result.stdout)
        self.assertNotIn("specgraph-core", result.stdout)

    def test_workspace_list_reports_malformed_yaml(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write("workspaces: [\n")
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "list",
                "--catalog",
                catalog.name,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("platform: error: cannot parse catalog", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_workspace_doctor_reports_malformed_yaml(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write("workspaces: [\n")
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("platform: error: cannot parse catalog", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_workspace_doctor_accepts_initialized_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "ProductA"
            (workspace / "specs").mkdir(parents=True)
            (workspace / "runs").mkdir()
            (workspace / "docs" / "proposals").mkdir(parents=True)
            (workspace / "specgraph.project.yaml").write_text("project: product-a\n")
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{workspace}"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])

    def test_workspace_doctor_reports_catalog_misconfigurations(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            missing_workspace = Path(root) / "MissingProduct"
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{missing_workspace}"
    governance_profile: self_hosted_bootstrap
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
    registry:
      registry_id: missing-registry
      import_policy: review_first
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("catalog_schema_invalid", codes)
        self.assertIn("workspace_profile_mismatch", codes)
        self.assertIn("unknown_registry_id", codes)
        self.assertIn("workspace_path_missing", codes)

    def test_workspace_doctor_reports_schema_errors_without_traceback(self) -> None:
        catalog_text = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - not-a-mapping
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(catalog_text)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("catalog_schema_invalid", codes)

    def test_workspace_doctor_sorts_multiple_schema_errors(self) -> None:
        catalog_text = """\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "${ORG_ROOT}"
workspaces:
  - project_id: "Has Space"
    display_name: ""
    kind: not_a_real_kind
    status: pending
    path: "relative/not/absolute"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
            catalog.write(catalog_text)
            catalog.flush()

            result = self.run_cli(
                "workspace",
                "doctor",
                "--catalog",
                catalog.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        schema_diagnostics = [
            d for d in payload["diagnostics"] if d["code"] == "catalog_schema_invalid"
        ]
        self.assertGreater(len(schema_diagnostics), 1)

    def test_workspace_doctor_reports_specgraph_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "ProductA"
            (workspace / "specs").mkdir(parents=True)
            (workspace / "runs").mkdir()
            (workspace / "docs" / "proposals").mkdir(parents=True)
            (workspace / "specgraph.project.yaml").mkdir()
            catalog_text = f"""\
schema_version: 1
artifact_kind: platform_workspace_catalog
organization_root: "{root}"
workspaces:
  - project_id: product-a
    display_name: Product A
    kind: product_workspace
    status: active
    path: "{workspace}"
    governance_profile: product_workspace
    specgraph_config: specgraph.project.yaml
    provider:
      type: local_filesystem
      specs_root: specs
      runs_root: runs
      proposals_root: docs/proposals
"""

            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as catalog:
                catalog.write(catalog_text)
                catalog.flush()

                result = self.run_cli(
                    "workspace",
                    "doctor",
                    "--catalog",
                    catalog.name,
                    "--format",
                    "json",
                )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("path_wrong_type", codes)

    def test_workspace_doctor_warns_when_org_root_is_unresolved(self) -> None:
        result = self.run_cli(
            "workspace",
            "doctor",
            "--format",
            "json",
            env_overrides={"ORG_ROOT": None, "PLATFORM_WORKSPACES_CATALOG": None},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("org_root_unresolved", codes)
        self.assertIn("workspace_path_unresolved", codes)

    def test_graph_repository_validate_accepts_example_contract(self) -> None:
        result = self.run_cli(
            "graph-repository",
            "validate",
            "--contract",
            "graph-repository-service.example.json",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["operation_count"], 6)

    def test_graph_repository_validate_rejects_auto_merge(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["promotion_policy"]["auto_merge_allowed"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_auto_merge_not_allowed", codes)

    def test_graph_repository_validate_rejects_non_commit_canonical_write(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["supported_operations"][0]["writes_canonical_store"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "graph_repository_operation_canonical_write_mismatch",
            codes,
        )

    def test_graph_repository_validate_rejects_empty_validation_gate(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["validation_gates"]["required_before_branch"] = []
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "graph-repository",
                "validate",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_contract_schema_invalid", codes)
        self.assertIn("graph_repository_validation_gate_empty", codes)

    def test_graph_repository_plan_builds_readonly_execution_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            output = runs_dir / "graph_repository_execution_plan.json"
            self.write_graph_repository_run_artifacts(runs_dir)

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_execution_plan",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["read_only"])
            self.assertTrue(payload["ready_for_branch"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(payload["write_actions_executed"], [])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            operations = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(operations["prepare_branch"], "ready")
            self.assertEqual(
                operations["create_commit"],
                "blocked_until_prepare_branch",
            )

    def test_graph_repository_plan_rejects_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            (runs_dir / "candidate_repair_loop_report.json").unlink()

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_artifact_missing", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_rejects_artifact_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_authority_expanded=True,
            )

            result = self.run_cli(
                "graph-repository",
                "plan",
                "--contract",
                "graph-repository-service.example.json",
                "--runs-dir",
                str(runs_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_artifact_authority_expanded", codes)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
