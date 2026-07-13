from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


class HostedManagedCheckoutContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.script_path = (
            root / "deploy" / "hosted-managed" / "hosted-managed-checkout.sh"
        )
        self.script = self.script_path.read_text(encoding="utf-8")
        self.cloud_init = (
            root / "deploy" / "hosted-managed" / "cloud-init.production.example.yaml"
        ).read_text(encoding="utf-8")
        self.runbook = (root / "docs" / "hosted-managed-operations.md").read_text(
            encoding="utf-8"
        )

    def test_script_has_valid_bash_syntax_and_disables_xtrace(self) -> None:
        subprocess.run(["bash", "-n", self.script_path], check=True)
        self.assertTrue(
            self.script.startswith("#!/usr/bin/env bash\nset +x\nset -euo pipefail\n")
        )

    def test_repository_roots_and_remotes_are_fixed(self) -> None:
        self.assertIn('REPOSITORY_ROOT="/srv/0al/platform"', self.script)
        self.assertIn('REPOSITORY_ROOT="/srv/0al/specgraph"', self.script)
        self.assertIn(
            'REPOSITORY_URL="https://github.com/0al-spec/Platform.git"', self.script
        )
        self.assertIn(
            'REPOSITORY_URL="https://github.com/0al-spec/SpecGraph.git"', self.script
        )
        self.assertNotIn("--repository-url", self.script)
        self.assertNotIn("--repository-root", self.script)

    def test_sync_uses_numeric_runtime_identity_and_clean_exact_commit(self) -> None:
        self.assertIn('setpriv --reuid="${RUNTIME_UID}"', self.script)
        self.assertIn('HOME="${RUNTIME_HOME}"', self.script)
        self.assertIn("GIT_CONFIG_NOSYSTEM=1", self.script)
        self.assertIn("repository worktree is not clean", self.script)
        self.assertIn("commit must be a full lowercase SHA-1", self.script)
        self.assertIn('fetch --no-tags origin main', self.script)
        self.assertIn('checkout --detach "${commit}"', self.script)
        self.assertNotIn("safe.directory", self.script)
        self.assertNotIn("reset --hard", self.script)
        self.assertNotIn("git clean", self.script)

    def test_first_clone_reaches_checkout_before_clean_status_is_required(self) -> None:
        clone_index = self.script.index('clone --no-checkout "${REPOSITORY_URL}"')
        fresh_clone_index = self.script.index('fresh_clone="true"', clone_index)
        conditional_guard_index = self.script.index(
            'if [[ "${fresh_clone}" != "true" ]]', fresh_clone_index
        )
        checkout_index = self.script.index('checkout --detach "${commit}"')
        final_status_index = self.script.index("checkout_status", checkout_index)
        self.assertLess(fresh_clone_index, conditional_guard_index)
        self.assertLess(conditional_guard_index, checkout_index)
        self.assertLess(checkout_index, final_status_index)

    def test_cloud_init_prepares_runtime_home_and_setpriv(self) -> None:
        self.assertIn("  - util-linux\n", self.cloud_init)
        self.assertIn("/srv/0al/.runtime-home", self.cloud_init)
        self.assertIn("chmod 0700 /srv/0al/.runtime-home", self.cloud_init)
        self.assertIn("chown 1000:1000 /srv/0al/.runtime-home", self.cloud_init)

    def test_runbook_uses_the_bounded_helper(self) -> None:
        self.assertIn("hosted-managed-checkout.sh install", self.runbook)
        self.assertIn("0al-hosted-managed-checkout status", self.runbook)
        self.assertIn("global `safe.directory`", self.runbook)


if __name__ == "__main__":
    unittest.main()
