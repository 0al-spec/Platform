"""Fixed production profiles for bounded hosted managed operations."""

from __future__ import annotations

from dataclasses import dataclass
import re

try:
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operations as contracts


REVIEW_STATUS_PROFILE_ID = "review-status"
PROMOTION_DRY_RUN_PROFILE_ID = "promotion-dry-run"
BOUNDED_PRODUCT_DRY_RUN_PROFILE_ID = "bounded-product-dry-run"


@dataclass(frozen=True)
class ProductionOperationProfile:
    profile_id: str
    operation_id: str
    policy_filename: str
    compose_profile: str
    worker_service: str
    expected_output_reports: tuple[str, ...]
    allow_continuous_worker: bool


@dataclass(frozen=True)
class ProductionDeploymentProfile:
    profile_id: str
    enabled_operation_ids: tuple[str, ...]
    allow_continuous_worker: bool

    @property
    def allowlist(self) -> str:
        return ",".join(self.enabled_operation_ids)


PRODUCTION_OPERATION_PROFILES = (
    ProductionOperationProfile(
        profile_id=REVIEW_STATUS_PROFILE_ID,
        operation_id="review_status_execute",
        policy_filename="worker-window-policy.json",
        compose_profile="bounded-worker",
        worker_service="managed-operation-window-worker",
        expected_output_reports=(
            "runs/product_candidate_promotion_review_status_report.json",
        ),
        allow_continuous_worker=True,
    ),
    ProductionOperationProfile(
        profile_id=PROMOTION_DRY_RUN_PROFILE_ID,
        operation_id="promotion_execute_dry_run",
        policy_filename="promotion-dry-run-worker-window-policy.json",
        compose_profile="promotion-dry-run-window",
        worker_service="managed-operation-promotion-dry-run-window-worker",
        expected_output_reports=(
            contracts.PROMOTION_DRY_RUN_EXECUTION_OUTPUT_REF,
            contracts.PROMOTION_DRY_RUN_GIT_SERVICE_OUTPUT_REF,
        ),
        allow_continuous_worker=False,
    ),
)


def concrete_output_reports(
    profile: ProductionOperationProfile,
    *,
    request_id: str,
) -> tuple[str, ...]:
    request_fragment = request_id.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{24}", request_fragment):
        raise ValueError("managed operation request id has an invalid digest fragment")
    return tuple(
        ref.replace("<request-id>", request_fragment)
        for ref in profile.expected_output_reports
    )

PRODUCTION_DEPLOYMENT_PROFILES = (
    ProductionDeploymentProfile(
        profile_id=REVIEW_STATUS_PROFILE_ID,
        enabled_operation_ids=("review_status_execute",),
        allow_continuous_worker=True,
    ),
    ProductionDeploymentProfile(
        profile_id=PROMOTION_DRY_RUN_PROFILE_ID,
        enabled_operation_ids=("promotion_execute_dry_run",),
        allow_continuous_worker=False,
    ),
    ProductionDeploymentProfile(
        profile_id=BOUNDED_PRODUCT_DRY_RUN_PROFILE_ID,
        enabled_operation_ids=(
            "promotion_execute_dry_run",
            "review_status_execute",
        ),
        allow_continuous_worker=False,
    ),
)


def profile_by_id(profile_id: str) -> ProductionOperationProfile:
    for profile in PRODUCTION_OPERATION_PROFILES:
        if profile.profile_id == profile_id:
            return profile
    raise ValueError("unknown production operation profile")


def profile_by_operation_id(operation_id: str) -> ProductionOperationProfile:
    for profile in PRODUCTION_OPERATION_PROFILES:
        if profile.operation_id == operation_id:
            return profile
    raise ValueError("operation is not approved for a production profile")


def profile_ids() -> tuple[str, ...]:
    return tuple(profile.profile_id for profile in PRODUCTION_OPERATION_PROFILES)


def deployment_profile_by_id(profile_id: str) -> ProductionDeploymentProfile:
    for profile in PRODUCTION_DEPLOYMENT_PROFILES:
        if profile.profile_id == profile_id:
            return profile
    raise ValueError("unknown production deployment profile")


def deployment_profile_by_operation_ids(
    operation_ids: tuple[str, ...],
) -> ProductionDeploymentProfile:
    normalized = tuple(sorted(operation_ids))
    for profile in PRODUCTION_DEPLOYMENT_PROFILES:
        if profile.enabled_operation_ids == normalized:
            return profile
    raise ValueError("operation allowlist is not an approved deployment profile")


def deployment_profile_ids() -> tuple[str, ...]:
    return tuple(profile.profile_id for profile in PRODUCTION_DEPLOYMENT_PROFILES)
