import json
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
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            check=False,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

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


if __name__ == "__main__":
    unittest.main()
