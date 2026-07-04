from __future__ import annotations


def workspace_creation_request(
    *,
    workspace_id: str = "pantry-rotation",
    display_name: str = "Pantry Rotation",
    authority_expanded: bool = False,
    include_summary: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_kind": "specspace_product_workspace_creation_request_state",
        "schema_version": 1,
        "state_owner": "SpecSpace",
        "canonical_mutations_allowed": False,
        "tracked_artifacts_written": False,
        "selected_workspace_id": workspace_id,
        "requests": [
            {
                "request_id": f"product-workspace-create.{workspace_id}",
                "workspace_id": workspace_id,
                "display_name": display_name,
                "route": f"/{workspace_id}",
                "operator_ref": "operator://specspace-local",
                "status": "requested",
                "created_at": "2026-07-04T00:00:00Z",
                "updated_at": "2026-07-04T00:00:00Z",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "consumer_boundary": {
                    "specspace_owned_state": True,
                    "may_execute_platform": authority_expanded,
                    "may_initialize_workspace": False,
                    "may_create_branch_or_commit": False,
                },
                "authority_boundary": {
                    "product_workspace_creation_request_state_is_authority": False,
                    "platform_execution_authority": False,
                    "workspace_catalog_authority": False,
                    "git_service_authority": False,
                    "canonical_mutations_allowed": False,
                },
            }
        ],
        "consumer_boundary": {
            "specspace_owned_state": True,
            "may_execute_platform": False,
            "may_initialize_workspace": False,
            "may_create_branch_or_commit": False,
        },
        "authority_boundary": {
            "product_workspace_creation_request_state_is_authority": False,
            "platform_execution_authority": False,
            "workspace_catalog_authority": False,
            "git_service_authority": False,
            "canonical_mutations_allowed": False,
        },
    }
    if include_summary:
        payload["summary"] = {
            "status": "workspace_creation_requested",
            "request_count": 1,
            "active_requested_count": 1,
            "next_gap": "run_platform_workspace_initialization",
        }
    return payload
