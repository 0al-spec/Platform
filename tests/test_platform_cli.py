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
        candidate_ready: bool = True,
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
                    "ready": candidate_ready,
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

    def build_graph_repository_execution_plan(
        self,
        tmp_root: Path,
        *,
        repair_ready: bool = True,
        context_required_count: int = 0,
    ) -> Path:
        runs_dir = tmp_root / "runs"
        runs_dir.mkdir()
        self.write_graph_repository_run_artifacts(
            runs_dir,
            repair_ready=repair_ready,
            context_required_count=context_required_count,
        )
        plan_path = tmp_root / "graph_repository_execution_plan.json"
        result = self.run_cli(
            "graph-repository",
            "plan",
            "--contract",
            "graph-repository-service.example.json",
            "--runs-dir",
            str(runs_dir),
            "--output",
            str(plan_path),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return plan_path

    def run_git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def create_graph_repository_checkout(self, tmp_root: Path) -> Path:
        source = tmp_root / "source"
        source.mkdir()
        self.run_git(source, "init")
        self.run_git(source, "config", "user.email", "test@example.com")
        self.run_git(source, "config", "user.name", "Platform Tests")
        (source / "README.md").write_text("# Test graph\n", encoding="utf-8")
        self.run_git(source, "add", "README.md")
        self.run_git(source, "commit", "-m", "Initial graph")
        self.run_git(source, "branch", "-M", "main")

        origin = tmp_root / "origin.git"
        subprocess.run(
            ["git", "clone", "--bare", str(source), str(origin)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        checkout = tmp_root / "checkout"
        subprocess.run(
            ["git", "clone", str(origin), str(checkout)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return checkout

    def prepare_graph_repository_worktree(self, tmp_root: Path) -> Path:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        repository_dir = self.create_graph_repository_checkout(tmp_root)
        workspace_dir = tmp_root / "candidate-worktree"
        result = self.run_cli(
            "graph-repository",
            "prepare-worktree",
            "--plan",
            str(plan_path),
            "--repository-dir",
            str(repository_dir),
            "--candidate-id",
            "idea-alpha",
            "--workspace-dir",
            str(workspace_dir),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return workspace_dir

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

    def test_graph_repository_plan_blocks_when_candidate_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                candidate_ready=False,
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

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        self.assertEqual(operations["prepare_branch"]["status"], "blocked")
        self.assertEqual(operations["prepare_branch"]["reason"], "candidate_not_ready")

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

    def test_graph_repository_prepare_local_writes_workspace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_local_prepare_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(payload["git_commands_executed"], [])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertTrue(
                (workspace_dir / "candidate_workspace_manifest.json").is_file()
            )
            self.assertTrue(
                (workspace_dir / "graph_repository_local_prepare_report.json").is_file()
            )
            manifest = json.loads(
                (workspace_dir / "candidate_workspace_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest["artifact_kind"],
                "platform_graph_repository_candidate_workspace_manifest",
            )
            self.assertFalse(
                manifest["authority_boundary"]["canonical_specs_mutated"]
            )
            self.assertFalse(
                manifest["authority_boundary"]["ontology_packages_written"]
            )

    def test_graph_repository_prepare_local_rejects_invalid_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea..alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_candidate_branch_invalid", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["local_files_written"], [])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_prepare_local_rejects_not_ready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )
            workspace_dir = tmp_root / "candidate-workspace"

            result = self.run_cli(
                "graph-repository",
                "prepare-local",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["local_files_written"], [])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_prepare_worktree_creates_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(repository_dir),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_worktree_prepare_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(len(payload["git_commands_executed"]), 2)
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertEqual(payload["commits_created"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertTrue((workspace_dir / ".git").exists())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )
            branch = self.run_git(
                workspace_dir,
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
            ).stdout.strip()
            self.assertEqual(branch, "graph-candidate/idea-alpha")

    def test_graph_repository_prepare_worktree_resolves_relative_workspace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "relative-candidate-worktree"
            relative_workspace = Path(os.path.relpath(workspace_dir, REPO_ROOT))

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(repository_dir),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(relative_workspace),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["workspace_dir"], str(workspace_dir.resolve()))
            self.assertEqual(
                payload["git_commands_executed"][1]["command"][5],
                str(workspace_dir.resolve()),
            )
            self.assertTrue((workspace_dir / ".git").exists())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )

    def test_graph_repository_prepare_worktree_rejects_missing_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "graph-repository",
                "prepare-worktree",
                "--plan",
                str(plan_path),
                "--repository-dir",
                str(tmp_root / "missing-repository"),
                "--candidate-id",
                "idea-alpha",
                "--workspace-dir",
                str(workspace_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_repository_missing", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(workspace_dir.exists())

    def test_graph_repository_commit_worktree_creates_candidate_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            spec_path = workspace_dir / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--message",
                "Add candidate spec",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_review_commit_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["candidate_tracked_artifacts_written"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(
                payload["committed_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertIsInstance(payload["commit_sha"], str)
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_commit_report.json"
                ).is_file()
            )
            subject = self.run_git(
                workspace_dir,
                "log",
                "--format=%s",
                "-1",
            ).stdout.strip()
            self.assertEqual(subject, "Add candidate spec")

    def test_graph_repository_commit_worktree_rejects_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir = self.prepare_graph_repository_worktree(tmp_root)
            prepare_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_worktree_prepare_report.json"
            )

            result = self.run_cli(
                "graph-repository",
                "commit-worktree",
                "--prepare-report",
                str(prepare_report),
                "--worktree-dir",
                str(workspace_dir),
                "--path",
                "../outside.yaml",
                "--message",
                "Attempt outside path",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_path_outside_worktree", codes)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["commit_sha"])


if __name__ == "__main__":
    unittest.main()
