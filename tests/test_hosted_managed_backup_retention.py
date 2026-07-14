from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts import validate_hosted_managed_backup_retention as retention


class HostedManagedBackupRetentionTests(unittest.TestCase):
    def policy(self) -> dict:
        return json.loads(retention.DEFAULT_POLICY.read_text(encoding="utf-8"))

    def test_tracked_policy_is_valid_and_disables_automatic_deletion(self) -> None:
        report = retention.load_and_validate(retention.DEFAULT_POLICY)
        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["summary"]["tier_count"], 3)
        self.assertFalse(report["summary"]["automatic_deletion"])

    def test_policy_rejects_short_retention_and_missing_restore_smoke(self) -> None:
        policy = copy.deepcopy(self.policy())
        policy["tiers"]["vps_private"]["minimum_successful_copies"] = 1
        policy["tiers"]["cloud_offsite_encrypted"][
            "requires_restore_smoke"
        ] = False
        report = retention.validate_policy(policy)
        self.assertFalse(report["ok"])
        self.assertIn("vps_private_minimum_invalid", report["findings"])
        self.assertIn(
            "cloud_offsite_encrypted_restore_smoke_missing", report["findings"]
        )

    def test_policy_rejects_automatic_deletion_and_authority_expansion(self) -> None:
        policy = copy.deepcopy(self.policy())
        policy["deletion"]["automatic"] = True
        policy["authority_boundary"]["may_delete_backups"] = True
        report = retention.validate_policy(policy)
        self.assertFalse(report["ok"])
        self.assertIn("deletion_policy_unsafe", report["findings"])
        self.assertIn("authority_boundary_expanded", report["findings"])

    def test_runbook_references_versioned_policy_and_prune_rule(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "hosted-managed-operations.md"
        ).read_text(encoding="utf-8")
        self.assertIn("backup-retention-policy.json", runbook)
        self.assertIn("`maximum_age_days` **and**", runbook)
        self.assertIn("`minimum_successful_copies`", runbook)
        self.assertIn("automatic deletion remains disabled", runbook)


if __name__ == "__main__":
    unittest.main()
