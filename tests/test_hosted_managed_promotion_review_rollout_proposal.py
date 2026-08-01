from __future__ import annotations

from pathlib import Path
import unittest

from scripts import hosted_managed_operations as operations
from scripts import hosted_managed_production_profiles as profiles


REPO_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = (
    REPO_ROOT / "docs" / "hosted-managed-promotion-review-rollout-proposal.md"
)


class HostedManagedPromotionReviewRolloutProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = " ".join(PROPOSAL.read_text(encoding="utf-8").split())

    def test_proposal_matches_registered_irreversible_operation(self) -> None:
        definition = operations.operation_by_id("promotion_review_execute")

        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertTrue(definition.irreversible)
        self.assertTrue(definition.requires_explicit_confirmation)
        self.assertFalse(definition.dry_run_only)
        self.assertEqual(definition.side_effect_class, "git_review")
        self.assertEqual(definition.replay_policy, "reconcile_before_retry")
        self.assertEqual(definition.timeout_seconds, 240)
        for token in (
            *definition.platform_command,
            *definition.input_refs,
            *definition.output_reports,
            definition.side_effect_class,
            definition.replay_policy,
        ):
            self.assertIn(f"`{token}`", self.text)

    def test_proposal_changes_no_current_production_allowlist(self) -> None:
        for profile in profiles.PRODUCTION_DEPLOYMENT_PROFILES:
            self.assertNotIn(
                "promotion_review_execute",
                profile.enabled_operation_ids,
            )

        self.assertIn(
            "implementation and production enablement are not approved",
            self.text,
        )
        self.assertIn("does not approve production enablement", self.text)
        self.assertIn("change `PLATFORM_MANAGED_OPERATION_ALLOWLIST`", self.text)

        with self.assertRaises(ValueError):
            profiles.profile_by_operation_id("promotion_review_execute")
        self.assertFalse(
            (
                REPO_ROOT
                / "deploy"
                / "hosted-managed"
                / "promotion-review-worker-window-policy.json"
            ).exists()
        )
        compose = (
            REPO_ROOT / "docker-compose.hosted-managed-production.example.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("promotion-review-window-worker", compose)

    def test_proposal_requires_current_semantic_confirmation_and_dry_run(self) -> None:
        for phrase in (
            "Semantic confirmation",
            "Current request-scoped dry-run evidence",
            "`runs/managed-promotion-dry-runs/<request-id>.*`",
            "the current promotion request, approval decision, and execution plan digests",
            "one successful request-scoped promotion dry-run",
            "must quarantine the request before any Git command runs",
            "A queue success status without valid reports is not predecessor evidence",
        ):
            self.assertIn(phrase, self.text)

    def test_proposal_requires_repository_and_partial_success_hardening(self) -> None:
        for phrase in (
            "expected base commit",
            "repository identity plus candidate ref has an exclusive lock",
            "cross-workspace test",
            "`--contract`, `--deployment-profile`, and `--repo`",
            "Git hooks and ambient credential helpers are disabled",
            "request-scoped, immutable, and exclusively created",
            "fenced lease alive while the irreversible subprocess is running",
            "post-PR/pre-ack failure",
        ):
            self.assertIn(phrase, self.text)

    def test_proposal_requires_consumed_confirmation_and_rollout_authorization(self) -> None:
        for phrase in (
            "atomically transition it from `ready` to `consumed` with CAS",
            "The browser must not supply `operator_ref`",
            "non-enqueueing prepare/reservation flow",
            "must not create a queue job",
            "reserved request id, reservation digest",
            "consume the reservation and enqueue the exact reserved envelope",
            "`platform_hosted_promotion_review_rollout_authorization` v1 artifact",
            "Without it, do not enqueue the request or contact the provider",
            "Proposal merge, implementation merge, and clean-VM success are not substitutes",
            "detached signature verified against a public key/fingerprint pinned in root-owned host configuration",
            "The private signing key must not be present in the worker",
        ):
            self.assertIn(phrase, self.text)

    def test_proposal_defines_machine_checkable_acceptance_artifacts(self) -> None:
        for phrase in (
            "`platform_hosted_promotion_review_confirmation` v1",
            "`platform_hosted_promotion_review_request_reservation` v1",
            "`platform_hosted_promotion_review_rollout_authorization` v1",
            "`platform_hosted_promotion_review_reconciliation_report` v1",
            "`platform_hosted_managed_worker_window_report`",
            "The full release gate remains `make python-quality`",
            "The proposal PR itself intentionally contains no implementation",
        ):
            self.assertIn(phrase, self.text)

    def test_proposal_forbids_blind_retry_and_automatic_follow_on_authority(self) -> None:
        for phrase in (
            "must never become an automatic retry policy",
            "Duplicate review creation, attempt `2`, and blind retry are rollout failures",
            "no retry of irreversible operations",
            "Do not authorize continuous execution or read-model publication automatically",
            "Rollback must not delete a branch, force-push, close a PR, delete queue rows",
        ):
            self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
