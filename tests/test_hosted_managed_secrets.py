from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


class HostedManagedSecretsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.script_path = (
            root / "deploy" / "hosted-managed" / "hosted-managed-secrets.sh"
        )
        self.script = self.script_path.read_text(encoding="utf-8")
        self.runbook = (root / "docs" / "hosted-managed-operations.md").read_text(
            encoding="utf-8"
        )

    def test_script_has_valid_bash_syntax(self) -> None:
        subprocess.run(["bash", "-n", self.script_path], check=True)

    def test_provisioning_uses_hidden_tty_input_and_bounded_paths(self) -> None:
        self.assertTrue(
            self.script.startswith("#!/usr/bin/env bash\nset +x\nset -euo pipefail\n")
        )
        self.assertIn('readonly SECRET_ROOT="/srv/0al/secrets"', self.script)
        self.assertIn('[[ -t 0 && -t 1 ]]', self.script)
        self.assertIn("IFS= read -r -s -p", self.script)
        self.assertNotIn("--service-token", self.script)
        self.assertNotIn("--database-password", self.script)
        self.assertNotIn("--github-token", self.script)

    def test_xtrace_is_disabled_before_any_secret_state_is_declared(self) -> None:
        self.assertLess(self.script.index("set +x"), self.script.index("SECRET_ROOT"))
        self.assertLess(self.script.index("set +x"), self.script.index("read_hidden"))

    def test_provisioning_is_fail_closed_and_derives_database_url(self) -> None:
        self.assertIn("refusing to overwrite existing", self.script)
        self.assertIn("^[0-9a-f]{64}$", self.script)
        self.assertIn("^github_pat_[A-Za-z0-9_]{20,}$", self.script)
        self.assertIn(
            "postgresql://managed_operations:%s@managed-operation-postgres:5432/managed_operations",
            self.script,
        )
        self.assertIn('chown 0:1000 "${service_temp}"', self.script)
        self.assertIn('chmod 0440 "${service_temp}"', self.script)

    def test_status_checks_shape_without_printing_values(self) -> None:
        self.assertIn("database URL does not match", self.script)
        self.assertIn('echo "service-token=ready"', self.script)
        self.assertNotIn('echo "${service_token}"', self.script)
        self.assertNotIn('echo "${database_password}"', self.script)
        self.assertNotIn('echo "${github_token}"', self.script)
        self.assertIn("never prints credential values", self.runbook)

    def test_state_provisioning_uses_independent_fixed_credentials(self) -> None:
        self.assertIn("provision-state", self.script)
        self.assertIn(
            'readonly SPECSPACE_STATE_TOKEN_FILE="${SECRET_ROOT}/'
            'specspace-state-token"',
            self.script,
        )
        self.assertIn(
            "postgresql://specspace_state:%s@specspace-state-postgres:"
            "5432/specspace_state",
            self.script,
        )
        self.assertIn(
            "SpecSpace state and managed-operation database credentials "
            "must differ",
            self.script,
        )
        self.assertIn(
            "SpecSpace state and managed-operation bearer tokens must differ",
            self.script,
        )
        self.assertIn('echo "specspace-state-token=ready"', self.script)
        self.assertNotIn('echo "${state_service_token}"', self.script)
        self.assertNotIn('echo "${state_database_password}"', self.script)


if __name__ == "__main__":
    unittest.main()
