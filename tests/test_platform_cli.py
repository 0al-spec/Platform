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
        cwd: Path | None = None,
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
            cwd=cwd or REPO_ROOT,
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

    def build_graph_repository_promotion_request(self, tmp_root: Path) -> Path:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        output = tmp_root / "graph_repository_promotion_request.json"
        result = self.run_cli(
            "graph-repository",
            "promotion-request",
            "--plan",
            str(plan_path),
            "--candidate-id",
            "idea-alpha",
            "--path",
            "specs/nodes/SG-SPEC-CANDIDATE.yaml",
            "--title",
            "Add candidate spec graph",
            "--body",
            "Review materialized candidate graph from the idea-to-spec flow.",
            "--output",
            str(output),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def git_service_request(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": "platform_git_service_operation_request",
            "operation": "prepare_worktree",
            "request_id": "req-001",
            "correlation_id": "corr-001",
            "idempotency_key": "prepare:idea-alpha:graph-candidate/idea-alpha",
            "actor_ref": "specspace:user/operator",
            "repository_ref": "git@github.com:0al-spec/SpecGraph.git",
            "candidate_id": "idea-alpha",
            "candidate_ref": "graph-candidate/idea-alpha",
            "base_ref": "main",
            "requested_at": "2026-06-21T00:00:00Z",
            "dry_run": True,
            "inputs": {
                "promotion_request": "runs/graph_repository_promotion_request.json",
                "execution_plan": "runs/graph_repository_execution_plan.json",
            },
            "authority_boundary": {
                "specspace_direct_git_write": False,
                "canonical_spec_mutation_without_review": False,
                "ontology_package_write": False,
                "auto_merge": False,
                "private_artifact_publication": False,
            },
        }

    def git_service_response(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": "platform_git_service_operation_response",
            "operation": "prepare_worktree",
            "request_id": "req-001",
            "response_id": "resp-001",
            "correlation_id": "corr-001",
            "idempotency_key": "prepare:idea-alpha:graph-candidate/idea-alpha",
            "status": "dry_run",
            "started_at": "2026-06-21T00:00:00Z",
            "completed_at": "2026-06-21T00:00:01Z",
            "outputs": {
                "candidate_ref": "graph-candidate/idea-alpha",
                "report": ".platform/graph_repository_worktree_prepare_report.json",
            },
            "audit_events": [
                {
                    "artifact_kind": "platform_git_service_audit_event",
                    "event_id": "audit-001",
                    "operation": "prepare_worktree",
                    "created_at": "2026-06-21T00:00:01Z",
                    "summary": "prepared candidate worktree in dry-run mode",
                }
            ],
            "writes": {
                "canonical_specs": False,
                "ontology_packages": False,
                "candidate_ref": True,
                "review": False,
                "read_model": False,
                "private_artifacts": False,
            },
        }

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

    def commit_graph_repository_candidate(self, tmp_root: Path) -> tuple[Path, Path]:
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
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_review_commit_report.json",
        )

    def write_fake_gh(self, tmp_root: Path) -> Path:
        fake_gh = tmp_root / "fake-gh"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            "printf '%s\\n' 'https://github.com/example/repo/pull/123'\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def write_failing_fake_gh(self, tmp_root: Path) -> Path:
        fake_gh = tmp_root / "fake-gh-fail"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            "printf '%s\\n' 'simulated gh failure' >&2\n"
            "exit 1\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def write_fake_gh_view(self, tmp_root: Path, payload: dict[str, object]) -> Path:
        fake_gh = tmp_root / "fake-gh-view"
        fake_gh.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' {json.dumps(json.dumps(payload))}\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        return fake_gh

    def open_graph_repository_review(self, tmp_root: Path) -> tuple[Path, Path]:
        workspace_dir, commit_report = self.commit_graph_repository_candidate(tmp_root)
        fake_gh = self.write_fake_gh(tmp_root)
        result = self.run_cli(
            "graph-repository",
            "open-review",
            "--commit-report",
            str(commit_report),
            "--worktree-dir",
            str(workspace_dir),
            "--base",
            "main",
            "--title",
            "Add candidate spec",
            "--body",
            "Review candidate spec graph.",
            "--gh-bin",
            str(fake_gh),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_open_review_report.json",
        )

    def merged_graph_repository_review_status(self, tmp_root: Path) -> tuple[Path, Path]:
        workspace_dir, open_review_report = self.open_graph_repository_review(tmp_root)
        fake_gh = self.write_fake_gh_view(
            tmp_root,
            {
                "number": 123,
                "url": "https://github.com/example/repo/pull/123",
                "state": "MERGED",
                "isDraft": False,
                "mergedAt": "2026-06-21T16:00:00Z",
                "mergeCommit": {"oid": "abc123"},
                "headRefName": "graph-candidate/idea-alpha",
                "baseRefName": "main",
                "reviewDecision": "APPROVED",
            },
        )
        result = self.run_cli(
            "graph-repository",
            "review-status",
            "--open-review-report",
            str(open_review_report),
            "--worktree-dir",
            str(workspace_dir),
            "--gh-bin",
            str(fake_gh),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (
            workspace_dir,
            workspace_dir / ".platform" / "graph_repository_review_status_report.json",
        )

    def write_public_read_model_bundle(self, tmp_root: Path) -> Path:
        bundle_dir = tmp_root / "public-bundle"
        bundle_dir.mkdir()
        (bundle_dir / "artifact_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_kind": "specgraph_public_artifact_manifest",
                    "files": ["runs/candidate_spec_graph.json"],
                }
            ),
            encoding="utf-8",
        )
        (bundle_dir / "runs").mkdir()
        (bundle_dir / "runs" / "candidate_spec_graph.json").write_text(
            json.dumps({"artifact_kind": "candidate_spec_graph"}),
            encoding="utf-8",
        )
        return bundle_dir

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

    def test_git_service_validate_accepts_example_contract(self) -> None:
        result = self.run_cli(
            "git-service",
            "validate-contract",
            "--contract",
            "git-service-operation-contract.example.json",
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["operation_count"], 5)

    def test_deployment_profile_validate_accepts_example_profiles(self) -> None:
        for profile, mode in (
            (
                "deployment-profile.product-idea-to-spec.example.json",
                "controlled_promotion",
            ),
            (
                "deployment-profile.specgraph-bootstrap-internal.example.json",
                "dry_run_only",
            ),
        ):
            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                profile,
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["diagnostics"], [])
            self.assertEqual(payload["summary"]["git_service_mode"], mode)

    def test_deployment_profile_validate_rejects_product_bootstrap_leak(
        self,
    ) -> None:
        profile = json.loads(
            (
                REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
            ).read_text(encoding="utf-8")
        )
        profile["hides"].remove("specgraph_bootstrap")
        profile["authority_boundary"]["exposes_bootstrap_surfaces"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(profile, handle)
            handle.flush()

            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_product_surface_leaks_bootstrap", codes)
        self.assertIn("deployment_profile_product_exposes_bootstrap", codes)

    def test_deployment_profile_validate_rejects_extra_product_repository_role(
        self,
    ) -> None:
        profile = json.loads(
            (
                REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
            ).read_text(encoding="utf-8")
        )
        profile["git_service"]["allowed_target_repository_roles"].append(
            "specgraph_bootstrap"
        )
        profile["git_service"]["denied_target_repository_roles"] = []
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(profile, handle)
            handle.flush()

            result = self.run_cli(
                "deployment-profile",
                "validate",
                "--profile",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_product_repository_role_expanded", codes)

    def test_git_service_validate_rejects_missing_operation(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"] = [
            operation
            for operation in contract["operations"]
            if operation["name"] != "publish_read_model"
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-contract",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_operation_missing", codes)

    def test_git_service_validate_rejects_lock_scope_mismatch(self) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"][0]["lock_scopes"] = ["review_ref"]
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(contract, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-contract",
                "--contract",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_lock_scope_missing", codes)

    def test_git_service_validate_accepts_request_and_response(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as request_handle:
            json.dump(self.git_service_request(), request_handle)
            request_handle.flush()

            request_result = self.run_cli(
                "git-service",
                "validate-request",
                "--request",
                request_handle.name,
                "--format",
                "json",
            )

        with tempfile.NamedTemporaryFile("w", suffix=".json") as response_handle:
            json.dump(self.git_service_response(), response_handle)
            response_handle.flush()

            response_result = self.run_cli(
                "git-service",
                "validate-response",
                "--response",
                response_handle.name,
                "--format",
                "json",
            )

        self.assertEqual(request_result.returncode, 0, request_result.stderr)
        self.assertEqual(response_result.returncode, 0, response_result.stderr)
        request_payload = json.loads(request_result.stdout)
        response_payload = json.loads(response_result.stdout)
        self.assertTrue(request_payload["ok"])
        self.assertTrue(response_payload["ok"])
        self.assertEqual(request_payload["summary"]["operation"], "prepare_worktree")
        self.assertEqual(response_payload["summary"]["operation"], "prepare_worktree")

    def test_git_service_validate_rejects_authority_expansion_request(self) -> None:
        request = self.git_service_request()
        request["authority_boundary"]["auto_merge"] = True
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(request, handle)
            handle.flush()

            result = self.run_cli(
                "git-service",
                "validate-request",
                "--request",
                handle.name,
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_operation_request_schema_invalid", codes)

    def test_git_service_execute_promotion_dry_run_plans_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "git_service_promotion_execution_report.json"

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_git_service_promotion_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(
                payload["deployment_profile"]["profile_id"],
                "product_idea_to_spec_workbench",
            )
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["operation_count"], 3)
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "dry_run")
            self.assertEqual(statuses["commit_candidate"], "skipped_dry_run")
            self.assertEqual(statuses["open_review"], "skipped_dry_run")
            self.assertFalse(workspace_dir.exists())
            self.assertTrue(output.is_file())

    def test_git_service_execute_promotion_runs_local_adapter_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            materialized_source = tmp_root / "materialized"
            spec_path = materialized_source / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--materialized-source-dir",
                str(materialized_source),
                "--open-review-dry-run",
                "--repo",
                "0al-spec/SpecGraph",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertFalse(payload["dry_run"])
            self.assertTrue(payload["open_review_dry_run"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "succeeded")
            self.assertEqual(statuses["commit_candidate"], "succeeded")
            self.assertEqual(statuses["open_review"], "dry_run")
            self.assertEqual(len(payload["copied_materialized_files"]), 1)
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_execution_report.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_worktree_prepare_report.json"
                ).is_file()
            )
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_commit_report.json"
                ).is_file()
            )
            self.assertTrue((workspace_dir / "specs/nodes/SG-SPEC-CANDIDATE.yaml").is_file())
            subject = self.run_git(
                workspace_dir,
                "log",
                "-1",
                "--pretty=%s",
            ).stdout.strip()
            self.assertEqual(subject, "Add candidate spec graph")

    def test_git_service_execute_promotion_rejects_not_ok_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["ok"] = False
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("git_service_promotion_request_not_ok", codes)

    def test_git_service_execute_promotion_rejects_bootstrap_target_under_product_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["workflow_lane"] = "specgraph_bootstrap"
            promotion_request["target_repository_role"] = "specgraph_bootstrap"
            promotion_request["authority_profile"] = "maintainer_bootstrap_controlled"
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_workflow_lane_denied", codes)
        self.assertIn("deployment_profile_target_repository_role_denied", codes)
        self.assertIn("deployment_profile_authority_profile_denied", codes)

    def test_git_service_execute_promotion_rejects_bootstrap_internal_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            promotion_request = json.loads(
                promotion_request_path.read_text(encoding="utf-8")
            )
            promotion_request["workflow_lane"] = "specgraph_bootstrap"
            promotion_request["deployment_profile_id"] = "specgraph_bootstrap_internal"
            promotion_request["target_repository_role"] = "specgraph_bootstrap"
            promotion_request["authority_profile"] = "maintainer_bootstrap_controlled"
            promotion_request_path.write_text(
                json.dumps(promotion_request),
                encoding="utf-8",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request_path),
                "--deployment-profile",
                "deployment-profile.specgraph-bootstrap-internal.example.json",
                "--repository-dir",
                str(tmp_root / "missing"),
                "--workspace-dir",
                str(tmp_root / "candidate-worktree"),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("deployment_profile_git_service_dry_run_only", codes)

    def test_git_service_finalize_promotion_publishes_read_model_after_merge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_git_service_promotion_finalization_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["review_state"], "merged")
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["review_status"], "succeeded")
            self.assertEqual(statuses["publish_read_model"], "succeeded")
            self.assertTrue(payload["summary"]["read_model_published"])
            self.assertTrue((output_dir / "artifact_manifest.json").is_file())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_finalization_report.json"
                ).is_file()
            )

    def test_git_service_finalize_promotion_resolves_relative_review_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, _open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                str(REPO_ROOT / "git-service-operation-contract.example.json"),
                "--open-review-report",
                ".platform/graph_repository_open_review_report.json",
                "--worktree-dir",
                ".",
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
                cwd=workspace_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertEqual(payload["review_state"], "merged")
            self.assertTrue(output_dir.joinpath("artifact_manifest.json").is_file())

    def test_git_service_finalize_promotion_rejects_unmerged_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "git-service",
                "finalize-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["review_state"], "open")
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("git_service_review_not_merged", codes)
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["publish_read_model"], "skipped_review_not_merged")
            self.assertFalse(output_dir.exists())

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

    def test_graph_repository_promotion_request_writes_review_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph from the idea-to-spec flow.",
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
                "platform_graph_repository_promotion_request",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(
                payload["deployment_profile_id"],
                "product_idea_to_spec_workbench",
            )
            self.assertEqual(payload["target_repository_role"], "product_spec_workspace")
            self.assertEqual(payload["authority_profile"], "workspace_owner_controlled")
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(
                payload["commit_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertEqual(
                payload["requested_operations"],
                ["prepare_branch", "create_commit", "open_review"],
            )
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(payload["write_actions_executed"], [])
            self.assertEqual(payload["git_commands_executed"], [])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["creates_commits"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertEqual(payload["summary"]["commit_path_count"], 1)
            self.assertTrue(payload["summary"]["promotion_ready"])

    def test_graph_repository_promotion_request_rejects_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "../outside.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--output",
                str(output),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_path_outside_worktree", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])
        self.assertFalse(output.exists())

    def test_graph_repository_promotion_request_rejects_unsupported_path_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "README.md",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_promotion_path_not_allowed", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_promotion_request_rejects_not_ready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )

            result = self.run_cli(
                "graph-repository",
                "promotion-request",
                "--plan",
                str(plan_path),
                "--candidate-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--title",
                "Add candidate spec graph",
                "--body",
                "Review materialized candidate graph.",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])

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

    def test_graph_repository_open_review_pushes_branch_and_invokes_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            fake_gh = self.write_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--base",
                "main",
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_open_review_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["candidate_branch_pushed"])
            self.assertEqual(
                payload["review_url"],
                "https://github.com/example/repo/pull/123",
            )
            self.assertEqual(
                payload["pull_requests_opened"],
                ["https://github.com/example/repo/pull/123"],
            )
            self.assertEqual(payload["commits_created"], [])
            self.assertEqual(payload["merges_performed"], [])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertEqual(len(payload["commands_executed"]), 2)
            self.assertEqual(payload["commands_executed"][1]["cwd"], str(workspace_dir))
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_open_review_report.json"
                ).is_file()
            )
            remote_heads = self.run_git(
                workspace_dir,
                "ls-remote",
                "--heads",
                "origin",
                "graph-candidate/idea-alpha",
            ).stdout
            self.assertIn("refs/heads/graph-candidate/idea-alpha", remote_heads)

    def test_graph_repository_open_review_preserves_push_status_on_gh_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            fake_gh = self.write_failing_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--base",
                "main",
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["candidate_branch_pushed"])
            self.assertEqual(payload["pull_requests_opened"], [])
            self.assertIsNone(payload["review_url"])
            self.assertEqual(len(payload["commands_executed"]), 2)
            self.assertEqual(payload["commands_executed"][1]["cwd"], str(workspace_dir))
            remote_heads = self.run_git(
                workspace_dir,
                "ls-remote",
                "--heads",
                "origin",
                "graph-candidate/idea-alpha",
            ).stdout
            self.assertIn("refs/heads/graph-candidate/idea-alpha", remote_heads)

    def test_graph_repository_open_review_rejects_failed_commit_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, commit_report = self.commit_graph_repository_candidate(
                tmp_root
            )
            payload = json.loads(commit_report.read_text(encoding="utf-8"))
            payload["ok"] = False
            commit_report.write_text(json.dumps(payload), encoding="utf-8")
            fake_gh = self.write_fake_gh(tmp_root)

            result = self.run_cli(
                "graph-repository",
                "open-review",
                "--commit-report",
                str(commit_report),
                "--worktree-dir",
                str(workspace_dir),
                "--title",
                "Add candidate spec",
                "--body",
                "Review candidate spec graph.",
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_commit_report_not_ok", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pull_requests_opened"], [])

    def test_graph_repository_review_status_reads_open_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_review_status_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["review_state"], "open")
            self.assertEqual(payload["review_decision"], "APPROVED")
            self.assertFalse(payload["summary"]["review_merged"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(payload["read_models_published"], [])
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "graph_repository_review_status_report.json"
                ).is_file()
            )

    def test_graph_repository_review_status_marks_merged_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": "2026-06-21T16:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["review_state"], "merged")
        self.assertTrue(payload["summary"]["review_merged"])
        self.assertEqual(payload["merges_performed"], [])
        self.assertEqual(payload["read_models_published"], [])

    def test_graph_repository_review_status_marks_merged_state_without_timestamp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "MERGED",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )

            result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["review_state"], "merged")
        self.assertTrue(payload["summary"]["review_merged"])

    def test_graph_repository_publish_read_model_copies_public_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            _workspace_dir, review_status_report = (
                self.merged_graph_repository_review_status(tmp_root)
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "graph-repository",
                "publish-read-model",
                "--review-status-report",
                str(review_status_report),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_graph_repository_publish_read_model_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["review_state"], "merged")
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["canonical_tracked_artifacts_written"])
            self.assertFalse(payload["ontology_packages_written"])
            self.assertEqual(payload["merges_performed"], [])
            self.assertEqual(
                payload["read_models_published"],
                [str(output_dir / "artifact_manifest.json")],
            )
            self.assertTrue((output_dir / "artifact_manifest.json").is_file())
            self.assertTrue(
                (output_dir / "runs" / "candidate_spec_graph.json").is_file()
            )
            self.assertTrue(
                (
                    output_dir
                    / ".platform"
                    / "graph_repository_publish_read_model_report.json"
                ).is_file()
            )

    def test_graph_repository_publish_read_model_rejects_unmerged_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            workspace_dir, open_review_report = self.open_graph_repository_review(
                tmp_root
            )
            fake_gh = self.write_fake_gh_view(
                tmp_root,
                {
                    "number": 123,
                    "url": "https://github.com/example/repo/pull/123",
                    "state": "OPEN",
                    "isDraft": False,
                    "mergedAt": None,
                    "mergeCommit": None,
                    "headRefName": "graph-candidate/idea-alpha",
                    "baseRefName": "main",
                    "reviewDecision": "APPROVED",
                },
            )
            status_result = self.run_cli(
                "graph-repository",
                "review-status",
                "--open-review-report",
                str(open_review_report),
                "--worktree-dir",
                str(workspace_dir),
                "--gh-bin",
                str(fake_gh),
                "--format",
                "json",
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            review_status_report = (
                workspace_dir
                / ".platform"
                / "graph_repository_review_status_report.json"
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            output_dir = tmp_root / "published-read-model"

            result = self.run_cli(
                "graph-repository",
                "publish-read-model",
                "--review-status-report",
                str(review_status_report),
                "--bundle-dir",
                str(bundle_dir),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_review_not_merged", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["read_models_published"], [])
        self.assertFalse(output_dir.exists())

    def test_graph_repository_publish_read_model_rejects_escaped_manifest_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            _workspace_dir, review_status_report = (
                self.merged_graph_repository_review_status(tmp_root)
            )
            bundle_dir = self.write_public_read_model_bundle(tmp_root)
            external_manifest = tmp_root / "external_manifest.json"
            external_manifest.write_text(
                json.dumps({"artifact_kind": "external_manifest"}),
                encoding="utf-8",
            )

            for index, manifest_name in enumerate(
                ["../external_manifest.json", str(external_manifest)]
            ):
                with self.subTest(manifest_name=manifest_name):
                    output_dir = tmp_root / f"published-read-model-{index}"
                    result = self.run_cli(
                        "graph-repository",
                        "publish-read-model",
                        "--review-status-report",
                        str(review_status_report),
                        "--bundle-dir",
                        str(bundle_dir),
                        "--output-dir",
                        str(output_dir),
                        "--manifest-name",
                        manifest_name,
                        "--format",
                        "json",
                    )

                    self.assertEqual(result.returncode, 1)
                    payload = json.loads(result.stdout)
                    codes = {
                        diagnostic["code"] for diagnostic in payload["diagnostics"]
                    }
                    self.assertIn(
                        "graph_repository_read_model_manifest_name_invalid",
                        codes,
                    )
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["read_models_published"], [])
                    self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
