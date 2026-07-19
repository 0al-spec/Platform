from __future__ import annotations

from pathlib import Path
import unittest

from scripts import hosted_managed_production_profiles as profiles


REPO_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = REPO_ROOT / "docs" / "hosted-managed-bounded-product-rollout-proposal.md"


class HostedManagedBoundedProductRolloutProposalTests(unittest.TestCase):
    def test_profile_exposes_only_reviewed_replay_safe_operations(self) -> None:
        profile = profiles.deployment_profile_by_id(
            profiles.BOUNDED_PRODUCT_DRY_RUN_PROFILE_ID
        )

        self.assertEqual(
            profile.enabled_operation_ids,
            ("promotion_execute_dry_run", "review_status_execute"),
        )
        self.assertFalse(profile.allow_continuous_worker)
        self.assertNotIn("promotion_review_execute", profile.enabled_operation_ids)
        self.assertNotIn(
            "read_model_publication_execute",
            profile.enabled_operation_ids,
        )

    def test_proposal_keeps_workers_operation_specific_and_stopped(self) -> None:
        text = " ".join(PROPOSAL.read_text(encoding="utf-8").split())

        self.assertIn("production rollout accepted", text)
        self.assertIn("promotion-dry-run-20260719t232321z", text)
        self.assertIn("review-status-20260719t232834z", text)
        self.assertIn("production-20260719t234024z", text)
        self.assertIn("The production worker remains stopped by default", text)
        self.assertIn(
            "every worker window narrows its container allowlist to exactly one operation",
            text,
        )
        self.assertIn(
            "`promotion_review_execute`, read-model publication, consume-on-attempt operations, and arbitrary commands remain disabled",
            text,
        )
        self.assertIn(
            "operators must not enqueue review status and promotion dry-run simultaneously",
            text,
        )


if __name__ == "__main__":
    unittest.main()
