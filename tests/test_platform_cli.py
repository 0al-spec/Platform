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
        clarification_answers_ready: bool = True,
        ontology_decisions_ready: bool = True,
        rerun_input_ready: bool = True,
        rerun_preview_ready: bool = True,
        rerun_materialization_ready: bool = True,
        repair_session_ready: bool = True,
        repair_session_intermediate_ready: bool | None = None,
        repair_session_ready_for_candidate_approval: bool | None = None,
        repair_session_authority_expanded: bool = False,
        repair_session_privacy_expanded: bool = False,
        repair_session_stale_source_ref: bool = False,
        unresolved_ontology_gap_count: object = 0,
        include_unresolved_ontology_gap_count: bool = True,
    ) -> None:
        unresolved_count_is_clear = (
            include_unresolved_ontology_gap_count
            and isinstance(unresolved_ontology_gap_count, int)
            and unresolved_ontology_gap_count == 0
        )
        if repair_session_intermediate_ready is None:
            repair_session_intermediate_ready = all(
                (
                    clarification_answers_ready,
                    ontology_decisions_ready,
                    rerun_input_ready,
                    rerun_preview_ready,
                    rerun_materialization_ready,
                )
            )
        if repair_session_ready_for_candidate_approval is None:
            repair_session_ready_for_candidate_approval = all(
                (
                    candidate_ready,
                    repair_ready,
                    context_required_count == 0,
                    repair_session_intermediate_ready,
                    unresolved_count_is_clear,
                )
            )
        repair_session_blockers: list[str] = []
        if not candidate_ready:
            repair_session_blockers.append("candidate_not_ready")
        if not repair_ready:
            repair_session_blockers.append("repair_loop_not_ready")
        if context_required_count:
            repair_session_blockers.append("repair_context_required")
        if not clarification_answers_ready:
            repair_session_blockers.append("clarification_answers_not_ready")
        if not ontology_decisions_ready:
            repair_session_blockers.append("ontology_gap_decisions_not_ready")
        if not rerun_input_ready:
            repair_session_blockers.append("rerun_input_not_ready")
        if not rerun_preview_ready:
            repair_session_blockers.append("rerun_preview_not_ready")
        if not rerun_materialization_ready:
            repair_session_blockers.append("rerun_materialization_not_ready")
        if not unresolved_count_is_clear:
            repair_session_blockers.append("unresolved_ontology_gaps")
        if (
            not repair_session_ready_for_candidate_approval
            and not repair_session_blockers
        ):
            repair_session_blockers.append(
                "repair_session_not_ready_for_candidate_approval"
            )
        rerun_preview_summary: dict[str, object] = {
            "resolved_ontology_gap_count": 1,
        }
        rerun_materialization_summary: dict[str, object] = {
            "removed_gap_count": 1,
            "resolved_ontology_gap_count": 1,
        }
        if include_unresolved_ontology_gap_count:
            rerun_preview_summary["unresolved_ontology_gap_count"] = (
                unresolved_ontology_gap_count
            )
            rerun_materialization_summary["unresolved_ontology_gap_count"] = (
                unresolved_ontology_gap_count
            )
        repair_session_source_refs = {
            "active_candidate": "runs/active_idea_to_spec_candidate.json",
            "clarification_requests": "runs/idea_to_spec_clarification_requests.json",
            "clarification_answers": "runs/idea_to_spec_clarification_answers.json",
            "ontology_decisions": "runs/product_ontology_gap_review_decisions.json",
            "rerun_input": "runs/idea_to_spec_answer_rerun_input.json",
            "rerun_preview": "runs/idea_to_spec_rerun_preview.json",
            "rerun_materialization": "runs/idea_to_spec_rerun_materialization.json",
            "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
        }
        if repair_session_stale_source_ref:
            repair_session_source_refs["rerun_preview"] = "runs/stale_preview.json"
        repair_session_source_artifacts = {
            key: {
                "artifact_key": key,
                "source_ref": source_ref,
                "artifact_kind": key,
                "readiness": {
                    "ready": True,
                    "review_state": "ready",
                },
            }
            for key, source_ref in repair_session_source_refs.items()
        }
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
            "idea_to_spec_clarification_requests.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_clarification_requests",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": False,
                    "review_state": "clarification_required",
                },
                "summary": {
                    "request_count": 1,
                    "blocking_request_count": 1,
                },
            },
            "idea_to_spec_clarification_answers.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_clarification_answers",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": clarification_answers_ready,
                    "review_state": "answers_ready_for_rerun"
                    if clarification_answers_ready
                    else "answers_blocked",
                },
                "summary": {
                    "accepted_answer_count": 1 if clarification_answers_ready else 0,
                    "unresolved_blocking_count": 0
                    if clarification_answers_ready
                    else 1,
                },
            },
            "product_ontology_gap_review_decisions.json": {
                "schema_version": 1,
                "artifact_kind": "product_ontology_gap_review_decisions",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": ontology_decisions_ready,
                    "review_state": "ontology_gap_decisions_ready"
                    if ontology_decisions_ready
                    else "ontology_gap_decisions_blocked",
                },
                "summary": {
                    "decision_count": 1 if ontology_decisions_ready else 0,
                },
            },
            "idea_to_spec_answer_rerun_input.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_answer_rerun_input",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_input_ready,
                    "review_state": "rerun_input_ready"
                    if rerun_input_ready
                    else "rerun_input_blocked",
                },
                "summary": {
                    "ontology_decision_count": 1 if ontology_decisions_ready else 0,
                },
            },
            "idea_to_spec_rerun_preview.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_rerun_preview",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_preview_ready,
                    "review_state": "rerun_preview_ready"
                    if rerun_preview_ready
                    else "rerun_preview_blocked",
                },
                "summary": rerun_preview_summary,
            },
            "idea_to_spec_rerun_materialization.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_rerun_materialization",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "readiness": {
                    "ready": rerun_materialization_ready,
                    "review_state": "rerun_materialization_ready"
                    if rerun_materialization_ready
                    else "rerun_materialization_blocked",
                },
                "summary": rerun_materialization_summary,
            },
            "idea_to_spec_repair_session.json": {
                "schema_version": 1,
                "artifact_kind": "idea_to_spec_repair_session_journal",
                "contract_ref": "specgraph.idea-to-spec.repair-session-journal.v0.1",
                "canonical_mutations_allowed": False,
                "tracked_artifacts_written": False,
                "authority_boundary": {
                    "may_accept_ontology_terms": False,
                    "may_apply_answers_to_source_artifacts": False,
                    "may_apply_decisions_to_source_artifacts": False,
                    "may_create_branch_or_commit": repair_session_authority_expanded,
                    "may_execute_prompt_agent": False,
                    "may_mark_candidate_graph_accepted": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_open_pull_request": False,
                    "may_publish_read_model": False,
                    "may_write_ontology_lockfile": False,
                    "may_write_ontology_package": False,
                },
                "privacy_boundary": {
                    "raw_idea_text_published": repair_session_privacy_expanded,
                    "raw_model_output_published": False,
                    "raw_operator_note_published": False,
                    "raw_prompt_published": False,
                    "static_flags_are_asserted_invariants": True,
                },
                "session": {
                    "candidate_id": "idea-alpha",
                    "workflow_lane": "product_idea_to_spec",
                    "target_repository_role": "product_spec_workspace",
                    "workspace_route": "/idea-alpha",
                },
                "readiness": {
                    "ready": repair_session_ready,
                    "review_state": "repair_session_journal_ready"
                    if repair_session_ready
                    else "repair_session_journal_blocked",
                },
                "readiness_impact": {
                    "blocked_by": repair_session_blockers,
                    "intermediate_artifacts_ready": repair_session_intermediate_ready,
                    "ready_for_candidate_approval": (
                        repair_session_ready_for_candidate_approval
                    ),
                    "ready_for_platform_promotion": False,
                    "unresolved_ontology_gap_count": (
                        unresolved_ontology_gap_count
                        if include_unresolved_ontology_gap_count
                        else None
                    ),
                },
                "source_artifacts": repair_session_source_artifacts,
                "summary": {
                    "candidate_id": "idea-alpha",
                    "workflow_lane": "product_idea_to_spec",
                    "ready_for_candidate_approval": (
                        repair_session_ready_for_candidate_approval
                    ),
                    "unresolved_ontology_gap_count": (
                        unresolved_ontology_gap_count
                        if include_unresolved_ontology_gap_count
                        else None
                    ),
                    "source_artifact_count": len(repair_session_source_artifacts),
                },
            },
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_product_repair_rerun_artifacts(
        self,
        specgraph_dir: Path,
        *,
        request_authority_expanded: bool = False,
        import_preview_ready: bool = True,
        request_gate_ready: bool = True,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.write_graph_repository_run_artifacts(runs_dir)
        selected_request_id = "rerun-request-1"
        candidate_id = "idea-alpha"
        workspace_id = "idea-alpha-workspace"
        request_state = {
            "schema_version": 1,
            "artifact_kind": "specspace_idea_to_spec_repair_rerun_request_state",
            "state_owner": "SpecSpace",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "consumer_boundary": {
                "specgraph_execution_authority": False,
                "git_service_authority": False,
            },
            "authority_boundary": {
                "may_execute_specgraph": False,
                "may_run_make_target": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "requests": [
                {
                    "id": selected_request_id,
                    "status": "requested",
                    "requested_action": "prepare_repair_draft_rerun",
                    "workspace_id": workspace_id,
                    "candidate_id": candidate_id,
                    "repair_session_id": "repair-session-1",
                    "may_execute_specgraph": False,
                    "may_run_make_target": False,
                    "may_mutate_canonical_specs": False,
                    "may_write_ontology_package": request_authority_expanded,
                    "may_accept_ontology_terms": False,
                    "may_create_branch_or_commit": False,
                    "may_open_pull_request": False,
                    "may_execute_git_service_operation": False,
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                }
            ],
        }
        import_preview = {
            "schema_version": 1,
            "artifact_kind": "specspace_repair_draft_import_preview",
            "contract_ref": (
                "specgraph.idea-to-spec.specspace-repair-draft-import-preview.v0.1"
            ),
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_execute_specgraph": False,
                "may_run_make_target": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "session": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "readiness": {
                "ready": import_preview_ready,
                "review_state": "ready" if import_preview_ready else "blocked",
            },
            "summary": {
                "accepted_for_rerun_count": 1 if import_preview_ready else 0,
            },
        }
        request_gate = {
            "schema_version": 1,
            "artifact_kind": "specspace_repair_rerun_request_gate",
            "contract_ref": (
                "specgraph.idea-to-spec.specspace-repair-rerun-request-gate.v0.1"
            ),
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_execute_specgraph_from_request": False,
                "may_run_make_target_from_request": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "readiness": {
                "ready": request_gate_ready,
                "review_state": "ready" if request_gate_ready else "blocked",
            },
            "summary": {
                "selected_request_id": selected_request_id,
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "resolved_inputs": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
            },
            "recommended_invocation": {
                "make_target": "product-workspace-requested-repair-draft-rerun",
            },
        }
        artifacts = {
            "idea_to_spec_repair_rerun_requests.json": request_state,
            "specspace_repair_draft_import_preview.json": import_preview,
            "specspace_repair_rerun_request_gate.json": request_gate,
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_product_candidate_approval_artifacts(
        self,
        specgraph_dir: Path,
        *,
        intent_authority_expanded: object = False,
        promotion_gate_authority_value: object = False,
        intent_repair_session_ref: str = "runs/idea_to_spec_repair_session.json",
        intent_promotion_gate_ref: str = "runs/idea_to_spec_promotion_gate.json",
        repair_session_ready_for_candidate_approval: bool = True,
        execution_ok: bool = True,
        execution_dry_run: bool = False,
        publication_ok: bool = True,
        publication_dry_run: bool = False,
    ) -> None:
        runs_dir = specgraph_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.write_graph_repository_run_artifacts(
            runs_dir,
            repair_session_ready_for_candidate_approval=(
                repair_session_ready_for_candidate_approval
            ),
        )
        candidate_id = "idea-alpha"
        workspace_id = "idea-alpha"
        intent_state = {
            "artifact_kind": "specspace_idea_to_spec_candidate_approval_intent_state",
            "schema_version": 1,
            "state_owner": "SpecSpace",
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "source_artifacts": {
                "idea_to_spec_repair_session": "runs/idea_to_spec_repair_session.json",
                "idea_to_spec_promotion_gate": "runs/idea_to_spec_promotion_gate.json",
            },
            "intents": [
                {
                    "id": "candidate-approval-intent.idea-alpha.20260626T100000Z",
                    "status": "requested",
                    "requested_action": "approve_candidate_for_promotion_review",
                    "workspace_id": workspace_id,
                    "candidate_id": candidate_id,
                    "repair_session_id": "repair-session.idea-alpha",
                    "repair_session_ref": intent_repair_session_ref,
                    "promotion_gate_ref": intent_promotion_gate_ref,
                    "requested_by": "operator://specspace-local",
                    "reason": "Ready for promotion review.",
                    "created_at": "2026-06-26T10:00:00Z",
                    "updated_at": "2026-06-26T10:00:00Z",
                    "ready_for_candidate_approval": True,
                    "ready_for_platform_promotion": False,
                    "blocked_by": [],
                    "canonical_mutations_allowed": False,
                    "tracked_artifacts_written": False,
                    "may_execute_specgraph": False,
                    "may_execute_prompt_agent": False,
                    "may_apply_to_specgraph": False,
                    "may_mutate_candidate_source_artifacts": False,
                    "may_mutate_canonical_specs": False,
                    "may_write_ontology_package": False,
                    "may_accept_ontology_terms": False,
                    "may_mark_candidate_accepted": intent_authority_expanded,
                    "may_mark_candidate_graph_accepted": False,
                    "may_create_branch_or_commit": False,
                    "may_open_pull_request": False,
                    "may_execute_git_service_operation": False,
                }
            ],
            "summary": {
                "status": "candidate_approval_intent_recorded",
                "intent_count": 1,
                "active_intent_count": 1,
                "workspace_count": 1,
            },
            "consumer_boundary": {
                "specspace_owned_state": True,
                "for_product_approval_workflow": True,
                "may_execute_specgraph": False,
                "may_execute_prompt_agent": False,
                "may_apply_to_specgraph": False,
                "may_mutate_candidate_source_artifacts": False,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
                "may_accept_ontology_terms": False,
                "may_mark_candidate_graph_accepted": False,
                "may_create_branch_or_commit": False,
                "may_open_pull_request": False,
                "may_execute_git_service_operation": False,
            },
            "authority_boundary": {
                "candidate_approval_intent_state_is_authority": False,
                "candidate_approval_decision_authority": False,
                "specgraph_artifact_authority": False,
                "ontology_authority": False,
                "git_service_authority": False,
                "canonical_mutations_allowed": False,
            },
        }
        promotion_gate = {
            "artifact_kind": "idea_to_spec_promotion_gate",
            "schema_version": 1,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "authority_boundary": {
                "may_create_branch_or_commit": False,
                "may_open_pull_request": promotion_gate_authority_value,
                "may_mutate_canonical_specs": False,
                "may_write_ontology_package": False,
            },
            "summary": {
                "workspace_id": workspace_id,
                "candidate_id": candidate_id,
                "promotion_path_count": 1,
            },
        }
        execution_report = {
            "artifact_kind": "platform_product_repair_rerun_execution_report",
            "schema_version": 1,
            "ok": execution_ok,
            "dry_run": execution_dry_run,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "specgraph_dir": str(specgraph_dir),
            "authority_boundary": {
                "executes_specgraph_make_target": not execution_dry_run,
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "writes_ontology_packages": False,
                "accepts_ontology_terms": False,
                "mutates_canonical_specs": False,
                "publishes_private_artifacts": False,
            },
            "summary": {
                "status": "completed" if execution_ok else "failed",
                "error_count": 0 if execution_ok else 1,
                "repair_session_digest": "0" * 64,
                "rerun_report_digest": "1" * 64,
            },
        }
        publication_report = {
            "artifact_kind": "platform_product_repair_rerun_publication_report",
            "schema_version": 1,
            "ok": publication_ok,
            "dry_run": publication_dry_run,
            "canonical_mutations_allowed": False,
            "tracked_artifacts_written": False,
            "specgraph_dir": str(specgraph_dir),
            "authority_boundary": {
                "executes_specgraph_make_target": not publication_dry_run,
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "writes_ontology_packages": False,
                "accepts_ontology_terms": False,
                "mutates_canonical_specs": False,
                "publishes_private_artifacts": False,
            },
            "manifest": {
                "path": str(
                    specgraph_dir / "dist" / "specgraph-public" / "artifact_manifest.json"
                ),
                "present": publication_ok and not publication_dry_run,
                "sha256": "2" * 64 if publication_ok and not publication_dry_run else None,
            },
            "summary": {
                "status": "published" if publication_ok else "failed",
                "error_count": 0 if publication_ok else 1,
                "published_artifact_count": 4 if publication_ok else 0,
                "missing_artifact_count": 0 if publication_ok else 1,
            },
        }
        artifacts = {
            "idea_to_spec_candidate_approval_intents.json": intent_state,
            "idea_to_spec_promotion_gate.json": promotion_gate,
            "platform_product_repair_rerun_execution_report.json": execution_report,
            "platform_product_repair_rerun_publication_report.json": publication_report,
        }
        for filename, payload in artifacts.items():
            (runs_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def write_product_repair_makefile(self, specgraph_dir: Path) -> None:
        makefile = """\
product-workspace-requested-repair-draft-rerun:
\t@mkdir -p runs
\t@printf '%s\\n' '{"artifact_kind":"specspace_repair_draft_rerun_report","contract_ref":"specgraph.idea-to-spec.specspace-repair-draft-rerun.v0.1","readiness":{"ready":true,"review_state":"repair_draft_rerun_ready"},"summary":{"status":"ready"}}' > runs/specspace_repair_draft_rerun_report.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_repair_session_journal","contract_ref":"specgraph.idea-to-spec.repair-session-journal.v0.1","readiness":{"ready":true,"review_state":"repair_session_journal_ready"},"summary":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","ready_for_candidate_approval":true},"readiness_impact":{"intermediate_artifacts_ready":true,"ready_for_candidate_approval":true,"ready_for_platform_promotion":false},"authority_boundary":{"may_accept_ontology_terms":false,"may_apply_answers_to_source_artifacts":false,"may_apply_decisions_to_source_artifacts":false,"may_create_branch_or_commit":false,"may_execute_prompt_agent":false,"may_mark_candidate_graph_accepted":false,"may_mutate_candidate_source_artifacts":false,"may_mutate_canonical_specs":false,"may_open_pull_request":false,"may_publish_read_model":false,"may_write_ontology_lockfile":false,"may_write_ontology_package":false},"privacy_boundary":{"raw_idea_text_published":false,"raw_model_output_published":false,"raw_operator_note_published":false,"raw_prompt_published":false,"static_flags_are_asserted_invariants":true},"session":{"candidate_id":"idea-alpha","workflow_lane":"product_idea_to_spec","target_repository_role":"product_spec_workspace"},"source_artifacts":{"active_candidate":{"source_ref":"runs/active_idea_to_spec_candidate.json"},"clarification_requests":{"source_ref":"runs/idea_to_spec_clarification_requests.json"},"clarification_answers":{"source_ref":"runs/idea_to_spec_clarification_answers.json"},"ontology_decisions":{"source_ref":"runs/product_ontology_gap_review_decisions.json"},"rerun_input":{"source_ref":"runs/idea_to_spec_answer_rerun_input.json"},"rerun_preview":{"source_ref":"runs/idea_to_spec_rerun_preview.json"},"rerun_materialization":{"source_ref":"runs/idea_to_spec_rerun_materialization.json"},"promotion_gate":{"source_ref":"runs/idea_to_spec_promotion_gate.json"}}}' > runs/idea_to_spec_repair_session.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_rerun_preview"}' > runs/idea_to_spec_rerun_preview.json
\t@printf '%s\\n' '{"artifact_kind":"idea_to_spec_rerun_materialization"}' > runs/idea_to_spec_rerun_materialization.json

publish-bundle:
\t@mkdir -p dist/specgraph-public/runs
\t@printf '%s\\n' '{"artifact_kind":"artifact_manifest"}' > dist/specgraph-public/artifact_manifest.json
\t@cp runs/idea_to_spec_repair_session.json dist/specgraph-public/runs/idea_to_spec_repair_session.json
\t@cp runs/specspace_repair_draft_rerun_report.json dist/specgraph-public/runs/specspace_repair_draft_rerun_report.json
\t@cp runs/idea_to_spec_rerun_preview.json dist/specgraph-public/runs/idea_to_spec_rerun_preview.json
\t@cp runs/idea_to_spec_rerun_materialization.json dist/specgraph-public/runs/idea_to_spec_rerun_materialization.json
"""
        (specgraph_dir / "Makefile").write_text(makefile, encoding="utf-8")

    def build_graph_repository_execution_plan(
        self,
        tmp_root: Path,
        *,
        repair_ready: bool = True,
        context_required_count: int = 0,
    ) -> Path:
        runs_dir = tmp_root / "runs"
        runs_dir.mkdir(parents=True)
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

    def build_product_candidate_promotion_request(self, tmp_root: Path) -> tuple[Path, Path]:
        plan_path = self.build_graph_repository_execution_plan(tmp_root)
        approval_decision = self.write_candidate_approval_decision(tmp_root)
        output = tmp_root / "graph_repository_promotion_request.json"
        result = self.run_cli(
            "product-candidate-promotion",
            "request",
            "--plan",
            str(plan_path),
            "--approval-decision",
            str(approval_decision),
            "--output",
            str(output),
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output, approval_decision

    def write_candidate_approval_decision(
        self,
        tmp_root: Path,
        *,
        candidate_id: str = "idea-alpha",
        workflow_lane: str = "product_idea_to_spec",
        target_repository_role: str = "product_spec_workspace",
        decision_state: str = "approved",
        ready: bool = True,
        paths: list[str] | None = None,
    ) -> Path:
        tmp_root.mkdir(parents=True, exist_ok=True)
        approval_path = tmp_root / "candidate_approval_decision.json"
        promotion_paths = paths or ["specs/nodes/SG-SPEC-CANDIDATE.yaml"]
        approval_path.write_text(
            json.dumps(
                {
                    "artifact_kind": "candidate_approval_decision",
                    "schema_version": 1,
                    "contract_ref": (
                        "specgraph.idea-to-spec.candidate-approval-decision.v0.1"
                    ),
                    "canonical_mutations_allowed": False,
                    "ontology_writes_allowed": False,
                    "tracked_artifacts_written": False,
                    "workspace": {
                        "workspace_id": candidate_id,
                        "mode": workflow_lane,
                        "repository_role": target_repository_role,
                        "public_route": f"/{candidate_id}",
                    },
                    "candidate": {
                        "candidate_id": candidate_id,
                        "display_name": "Idea Alpha",
                        "active_candidate_ref": (
                            "runs/active_idea_to_spec_candidate.json"
                        ),
                        "promotion_gate_ref": (
                            "runs/idea_to_spec_promotion_gate.json"
                        ),
                    },
                    "decision": {
                        "requested_state": decision_state,
                        "state": decision_state,
                        "operator_ref": "operator://workspace-owner",
                        "reason": "Approve review-ready candidate promotion.",
                        "conditions": [],
                    },
                    "readiness": {
                        "ready": ready,
                        "review_state": "candidate_approval_ready"
                        if ready
                        else "candidate_approval_blocked",
                        "blocked_by": [] if ready else ["decision_not_approved"],
                    },
                    "promotion_request": {
                        "platform_artifact_kind": (
                            "platform_graph_repository_promotion_request"
                        ),
                        "paths": promotion_paths,
                        "requires_git_service_execution": True,
                    },
                    "source_artifacts": {
                        "candidate_approval_gate": (
                            "runs/platform_candidate_approval_intent_gate_report.json"
                        ),
                        "repair_session": "runs/idea_to_spec_repair_session.json",
                        "promotion_gate": "runs/idea_to_spec_promotion_gate.json",
                        "platform_repair_execution": (
                            "runs/platform_product_repair_rerun_execution_report.json"
                        ),
                        "platform_repair_publication": (
                            "runs/platform_product_repair_rerun_publication_report.json"
                        ),
                    },
                    "authority_boundary": {
                        "may_execute_prompt_agent": False,
                        "may_mutate_candidate_source_artifacts": False,
                        "may_mutate_canonical_specs": False,
                        "may_write_ontology_package": False,
                        "may_write_ontology_lockfile": False,
                        "may_mark_candidate_graph_accepted": False,
                        "may_create_branch_or_commit": False,
                        "may_open_pull_request": False,
                        "may_publish_read_model": False,
                        "may_execute_git_service_operation": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return approval_path

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
                "candidate_approval_decision": "runs/candidate_approval_decision.json",
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

    def test_git_service_validate_rejects_missing_approval_contract_input(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "git-service-operation-contract.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["operations"][0]["required_inputs"].remove(
            "candidate_approval_decision"
        )
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
        self.assertIn("git_service_required_input_missing", codes)

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

    def test_git_service_validate_rejects_missing_approval_request_input(
        self,
    ) -> None:
        request = self.git_service_request()
        del request["inputs"]["candidate_approval_decision"]
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
        self.assertIn("git_service_operation_request_input_missing", codes)

    def test_git_service_execute_promotion_dry_run_plans_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
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
                "--approval-decision",
                str(approval_decision),
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
            approval_decision = self.write_candidate_approval_decision(tmp_root)
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
                "--approval-decision",
                str(approval_decision),
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
            approval_decision = self.write_candidate_approval_decision(tmp_root)
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
                "--approval-decision",
                str(approval_decision),
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

    def test_git_service_execute_promotion_requires_approved_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                decision_state="rejected",
                ready=False,
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
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
        self.assertIn("git_service_candidate_approval_not_approved", codes)
        self.assertIn("git_service_candidate_approval_not_ready", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_approval_candidate_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                candidate_id="other-idea",
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
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
        self.assertIn("git_service_candidate_approval_candidate_mismatch", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_approval_path_mismatch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=["docs/proposals/OTHER.md"],
            )

            result = self.run_cli(
                "git-service",
                "execute-promotion",
                "--contract",
                "git-service-operation-contract.example.json",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
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
        self.assertIn("git_service_candidate_approval_paths_mismatch", codes)
        self.assertEqual(payload["operations"], [])

    def test_git_service_execute_promotion_rejects_bootstrap_target_under_product_profile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request_path = self.build_graph_repository_promotion_request(
                tmp_root
            )
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                workflow_lane="specgraph_bootstrap",
                target_repository_role="specgraph_bootstrap",
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
                "--approval-decision",
                str(approval_decision),
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
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                workflow_lane="specgraph_bootstrap",
                target_repository_role="specgraph_bootstrap",
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
                "--approval-decision",
                str(approval_decision),
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

    def test_graph_repository_validate_requires_repair_session_branch_gate(
        self,
    ) -> None:
        contract = json.loads(
            (REPO_ROOT / "graph-repository-service.example.json").read_text(
                encoding="utf-8"
            )
        )
        contract["validation_gates"]["required_before_branch"].remove(
            "idea_to_spec_repair_session"
        )
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
        self.assertIn("graph_repository_repair_session_gate_missing", codes)

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

    def test_graph_repository_plan_requires_repair_session_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(runs_dir)
            (runs_dir / "idea_to_spec_repair_session.json").unlink()

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
        missing = [
            diagnostic
            for diagnostic in payload["diagnostics"]
            if diagnostic["code"] == "graph_repository_artifact_missing"
        ]
        self.assertTrue(
            any(
                "idea_to_spec_repair_session.json" in diagnostic["subject"]
                for diagnostic in missing
            )
        )
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_blocks_when_repair_session_not_approval_ready(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_ready_for_candidate_approval=False,
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
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("repair_session_not_ready_for_candidate_approval", blockers)

    def test_graph_repository_plan_rejects_stale_repair_session_source_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_stale_source_ref=True,
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
        self.assertIn("graph_repository_repair_session_source_ref_stale", codes)
        self.assertFalse(payload["ok"])

    def test_graph_repository_plan_rejects_write_capable_repair_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                repair_session_authority_expanded=True,
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
        self.assertIn("graph_repository_repair_session_authority_expanded", codes)
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

    def test_graph_repository_plan_blocks_unresolved_ontology_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                unresolved_ontology_gap_count=2,
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
        self.assertEqual(operations["validate_candidate_graph"]["status"], "blocked")
        self.assertEqual(operations["prepare_branch"]["status"], "blocked")
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("rerun_preview_unresolved_ontology_gaps", blockers)
        self.assertIn("rerun_materialization_unresolved_ontology_gaps", blockers)

    def test_graph_repository_plan_blocks_missing_unresolved_gap_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                include_unresolved_ontology_gap_count=False,
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
        operations = {
            operation["name"]: operation for operation in payload["operations"]
        }
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_required_summary_count_missing", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])
        blockers = set(operations["prepare_branch"]["reason"].split(","))
        self.assertIn("rerun_preview_unresolved_gap_count_invalid", blockers)
        self.assertIn("rerun_materialization_unresolved_gap_count_invalid", blockers)

    def test_graph_repository_plan_blocks_malformed_unresolved_gap_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir)
            self.write_graph_repository_run_artifacts(
                runs_dir,
                unresolved_ontology_gap_count="unknown",
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
        self.assertIn("graph_repository_required_summary_count_invalid", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_for_branch"])

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

    def test_product_repair_rerun_plan_builds_execution_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            output = specgraph_dir / "runs" / "product_repair_rerun_plan.json"

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
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
                "platform_product_repair_rerun_execution_plan",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_execute"])
            self.assertFalse(payload["canonical_mutations_allowed"])
            self.assertFalse(payload["tracked_artifacts_written"])
            self.assertEqual(
                payload["target_make"]["target"],
                "product-workspace-requested-repair-draft-rerun",
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertEqual(payload["summary"]["workspace_id"], "idea-alpha-workspace")

    def test_product_repair_rerun_plan_rejects_authority_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_authority_expanded=True,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_repair_rerun_request_authority_expanded", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_to_execute"])

    def test_product_repair_rerun_execute_runs_specgraph_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(execution_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_execution_report",
            )
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["command_result"]["returncode"], 0)
            self.assertTrue(payload["output_artifacts"]["rerun_report"]["ready"])
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_repair_rerun_execute_rejects_tampered_plan_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            with (specgraph_dir / "Makefile").open("a", encoding="utf-8") as makefile:
                makefile.write(
                    "\nunapproved-target:\n"
                    "\t@printf 'ran' > runs/unapproved-target-ran\n"
                )
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target_make"]["target"] = "unapproved-target"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_make_target_unsupported", codes)
            self.assertFalse((specgraph_dir / "runs" / "unapproved-target-ran").exists())

    def test_product_repair_rerun_execute_rejects_tampered_plan_cwd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            other_dir = Path(tmp_dir) / "OtherSpecGraph"
            specgraph_dir.mkdir()
            other_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_makefile(other_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target_make"]["cwd"] = str(other_dir)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_cwd_mismatch", codes)

    def test_product_repair_rerun_execute_requires_specgraph_makefile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            (specgraph_dir / "Makefile").unlink()

            result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_plan_specgraph_makefile_missing", codes)

    def test_product_repair_rerun_publish_verifies_public_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            publication_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_publication.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--output",
                str(publication_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(publication_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_publication_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["published_artifact_count"], 4)
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])

    def test_product_repair_rerun_publish_rejects_dry_run_execution_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--dry-run",
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_execution_report_dry_run", codes)

    def test_product_repair_rerun_publish_requires_specgraph_makefile(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            other_dir = Path(tmp_dir) / "OtherSpecGraph"
            specgraph_dir.mkdir()
            other_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            plan_path = specgraph_dir / "runs" / "product_repair_rerun_plan.json"
            execution_report_path = (
                specgraph_dir / "runs" / "product_repair_rerun_execution.json"
            )
            plan_result = self.run_cli(
                "product-repair-rerun",
                "plan",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(plan_path),
                "--format",
                "json",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            execute_result = self.run_cli(
                "product-repair-rerun",
                "execute",
                "--plan",
                str(plan_path),
                "--output",
                str(execution_report_path),
                "--format",
                "json",
            )
            self.assertEqual(execute_result.returncode, 0, execute_result.stderr)
            execution_report = json.loads(
                execution_report_path.read_text(encoding="utf-8")
            )
            execution_report["specgraph_dir"] = str(other_dir)
            execution_report_path.write_text(
                json.dumps(execution_report),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(execution_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
            self.assertIn("product_repair_rerun_publish_specgraph_makefile_missing", codes)

    def test_product_repair_rerun_smoke_runs_full_demo_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            smoke_report_path = (
                specgraph_dir / "runs" / "platform_product_repair_rerun_smoke.json"
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(smoke_report_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(smoke_report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_repair_rerun_smoke_report",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["status"], "passed")
            self.assertTrue(payload["summary"]["plan_ok"])
            self.assertTrue(payload["summary"]["execution_ok"])
            self.assertTrue(payload["summary"]["publication_ok"])
            self.assertIsInstance(payload["summary"]["rerun_report_digest"], str)
            self.assertIsInstance(payload["summary"]["repair_session_digest"], str)
            self.assertIsInstance(payload["summary"]["manifest_digest"], str)
            self.assertEqual(payload["summary"]["published_artifact_count"], 4)
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["writes_ontology_packages"])
            self.assertFalse(payload["authority_boundary"]["mutates_canonical_specs"])
            self.assertFalse(
                payload["authority_boundary"]["candidate_approval_performed"]
            )
            self.assertFalse(
                payload["authority_boundary"]["git_service_promotion_started"]
            )
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "succeeded")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "succeeded")
            self.assertEqual(statuses["publish_public_safe_bundle"], "succeeded")
            self.assertTrue(payload["phase_reports"]["plan"]["present"])
            self.assertTrue(payload["phase_reports"]["execution"]["present"])
            self.assertTrue(payload["phase_reports"]["publication"]["present"])
            self.assertTrue(
                (
                    specgraph_dir
                    / "dist"
                    / "specgraph-public"
                    / "runs"
                    / "idea_to_spec_repair_session.json"
                ).is_file()
            )

    def test_product_repair_rerun_smoke_resolves_caller_relative_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            caller_dir = tmp_root / "caller"
            caller_dir.mkdir()
            specgraph_dir = tmp_root / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(specgraph_dir)
            profile_path = caller_dir / "profile.json"
            profile_path.write_text(
                (
                    REPO_ROOT / "deployment-profile.product-idea-to-spec.example.json"
                ).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            inputs_dir = caller_dir / "inputs"
            inputs_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_rerun_requests.json",
                "specspace_repair_draft_import_preview.json",
                "idea_to_spec_repair_session.json",
                "specspace_repair_rerun_request_gate.json",
            ):
                (inputs_dir / filename).write_text(
                    (specgraph_dir / "runs" / filename).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--deployment-profile",
                "profile.json",
                "--specgraph-dir",
                os.path.relpath(specgraph_dir, caller_dir),
                "--rerun-request",
                "inputs/idea_to_spec_repair_rerun_requests.json",
                "--import-preview",
                "inputs/specspace_repair_draft_import_preview.json",
                "--repair-session",
                "inputs/idea_to_spec_repair_session.json",
                "--request-gate",
                "inputs/specspace_repair_rerun_request_gate.json",
                "--format",
                "json",
                cwd=caller_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            plan_ref = Path(payload["phase_reports"]["plan"]["path"])
            plan = json.loads(plan_ref.read_text(encoding="utf-8"))
            source_paths = {
                Path(source["path"])
                for source in plan["source_artifacts"]
                if source.get("key")
            }
            self.assertTrue(
                all(
                    path.resolve().is_relative_to(inputs_dir.resolve())
                    for path in source_paths
                )
            )

    def test_product_repair_rerun_smoke_keeps_execute_authority_after_publish_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            makefile_path = specgraph_dir / "Makefile"
            makefile = makefile_path.read_text(encoding="utf-8")
            makefile_path.write_text(
                makefile.split("\npublish-bundle:\n", 1)[0],
                encoding="utf-8",
            )
            self.write_product_repair_rerun_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["summary"]["execution_ok"])
            self.assertFalse(payload["summary"]["publication_ok"])
            self.assertTrue(
                payload["authority_boundary"]["executes_specgraph_make_target"]
            )

    def test_product_repair_rerun_smoke_stops_when_plan_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_repair_rerun_artifacts(
                specgraph_dir,
                request_authority_expanded=True,
            )

            result = self.run_cli(
                "product-repair-rerun",
                "smoke",
                "--specgraph-dir",
                str(specgraph_dir),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["operations"]
            }
            self.assertEqual(statuses["plan_product_repair_rerun"], "failed")
            self.assertEqual(statuses["execute_specgraph_requested_rerun"], "skipped")
            self.assertEqual(statuses["publish_public_safe_bundle"], "skipped")
            self.assertFalse(
                (
                    specgraph_dir
                    / "runs"
                    / "platform_product_repair_rerun_execution_report.json"
                ).exists()
            )
            self.assertFalse(
                (
                    specgraph_dir
                    / "runs"
                    / "platform_product_repair_rerun_publication_report.json"
                ).exists()
            )

    def test_product_candidate_approval_gate_builds_ready_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            output = specgraph_dir / "runs" / "candidate_approval_gate.json"

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
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
                "platform_candidate_approval_intent_gate_report",
            )
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["ready_to_materialize"])
            self.assertEqual(payload["summary"]["candidate_id"], "idea-alpha")
            self.assertEqual(payload["summary"]["workspace_id"], "idea-alpha")
            self.assertEqual(payload["summary"]["approved_path_count"], 1)
            self.assertEqual(
                payload["approved_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])
            self.assertFalse(payload["authority_boundary"]["writes_ontology_packages"])
            self.assertFalse(payload["authority_boundary"]["mutates_canonical_specs"])

    def test_product_candidate_approval_materialize_writes_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)
            gate_report = specgraph_dir / "runs" / "candidate_approval_gate.json"
            decision_path = specgraph_dir / "runs" / "candidate_approval_decision.json"
            gate_result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--output",
                str(gate_report),
                "--format",
                "json",
            )
            self.assertEqual(gate_result.returncode, 0, gate_result.stderr)

            result = self.run_cli(
                "product-candidate-approval",
                "materialize",
                "--gate-report",
                str(gate_report),
                "--output",
                str(decision_path),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            persisted = json.loads(decision_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, persisted)
            self.assertEqual(payload["artifact_kind"], "candidate_approval_decision")
            self.assertEqual(
                payload["contract_ref"],
                "specgraph.idea-to-spec.candidate-approval-decision.v0.1",
            )
            self.assertEqual(payload["decision"]["state"], "approved")
            self.assertTrue(payload["readiness"]["ready"])
            self.assertEqual(payload["candidate"]["candidate_id"], "idea-alpha")
            self.assertEqual(
                payload["promotion_request"]["paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertFalse(
                payload["authority_boundary"]["may_create_branch_or_commit"]
            )
            self.assertFalse(payload["authority_boundary"]["may_open_pull_request"])
            self.assertFalse(
                payload["authority_boundary"]["may_execute_git_service_operation"]
            )

    def test_product_candidate_approval_gate_rejects_authority_expansion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_authority_expanded="true",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_intent_authority_expanded", codes)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_promotion_gate_non_boolean_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                promotion_gate_authority_value=1,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_promotion_gate_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_unready_repair_session(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                repair_session_ready_for_candidate_approval=False,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_approval_repair_session_not_ready_for_candidate_approval",
            codes,
        )
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_requires_publication_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                publication_dry_run=True,
            )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_publication_report_dry_run", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_requires_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_paths_missing", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_rejects_disallowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(specgraph_dir)

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--path",
                "README.md",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_approval_path_not_allowed", codes)
        self.assertFalse(payload["ready_to_materialize"])

    def test_product_candidate_approval_gate_honors_overridden_input_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            specgraph_dir = Path(tmp_dir) / "SpecGraph"
            specgraph_dir.mkdir()
            self.write_product_repair_makefile(specgraph_dir)
            self.write_product_candidate_approval_artifacts(
                specgraph_dir,
                intent_repair_session_ref="inputs/idea_to_spec_repair_session.json",
                intent_promotion_gate_ref="inputs/idea_to_spec_promotion_gate.json",
            )
            inputs_dir = specgraph_dir / "inputs"
            inputs_dir.mkdir()
            for filename in (
                "idea_to_spec_repair_session.json",
                "idea_to_spec_promotion_gate.json",
            ):
                (inputs_dir / filename).write_text(
                    (specgraph_dir / "runs" / filename).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            result = self.run_cli(
                "product-candidate-approval",
                "gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                "idea-alpha",
                "--repair-session",
                "inputs/idea_to_spec_repair_session.json",
                "--promotion-gate",
                "inputs/idea_to_spec_promotion_gate.json",
                "--path",
                "specs/nodes/SG-SPEC-CANDIDATE.yaml",
                "--format",
                "json",
                cwd=specgraph_dir,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ready_to_materialize"])
        self.assertEqual(
            payload["selected_intent"]["repair_session_ref"],
            "inputs/idea_to_spec_repair_session.json",
        )
        self.assertEqual(
            payload["selected_intent"]["promotion_gate_ref"],
            "inputs/idea_to_spec_promotion_gate.json",
        )

    def test_product_candidate_approval_materialize_rejects_blocked_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            gate_report = Path(tmp_dir) / "blocked_gate.json"
            gate_report.write_text(
                json.dumps(
                    {
                        "artifact_kind": (
                            "platform_candidate_approval_intent_gate_report"
                        ),
                        "schema_version": 1,
                        "ok": False,
                        "ready_to_materialize": False,
                        "canonical_mutations_allowed": False,
                        "ontology_writes_allowed": False,
                        "tracked_artifacts_written": False,
                        "approved_paths": [],
                        "authority_boundary": {
                            "executes_git_commands": "true",
                            "opens_pull_requests": False,
                            "writes_ontology_packages": False,
                            "mutates_canonical_specs": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "product-candidate-approval",
                "materialize",
                "--gate-report",
                str(gate_report),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = set(payload["readiness"]["blocked_by"])
        self.assertIn("product_candidate_approval_gate_report_not_ok", codes)
        self.assertIn("product_candidate_approval_gate_not_ready", codes)
        self.assertIn("product_candidate_approval_gate_authority_expanded", codes)

    def test_product_candidate_promotion_request_uses_approval_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
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
            self.assertEqual(payload["candidate_id"], "idea-alpha")
            self.assertEqual(payload["workflow_lane"], "product_idea_to_spec")
            self.assertEqual(payload["target_repository_role"], "product_spec_workspace")
            self.assertEqual(payload["authority_profile"], "workspace_owner_controlled")
            self.assertEqual(
                payload["commit_paths"],
                ["specs/nodes/SG-SPEC-CANDIDATE.yaml"],
            )
            self.assertEqual(payload["candidate_branch"], "graph-candidate/idea-alpha")
            self.assertEqual(
                payload["requested_operations"],
                ["prepare_branch", "create_commit", "open_review"],
            )
            self.assertFalse(payload["authority_boundary"]["executes_git_commands"])
            self.assertFalse(payload["authority_boundary"]["creates_commits"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_requests"])

    def test_product_candidate_promotion_request_dry_run_does_not_write(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            output = tmp_root / "graph_repository_promotion_request.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--output",
                str(output),
                "--dry-run",
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["local_files_written"], [])
            self.assertFalse(output.exists())

    def test_product_candidate_promotion_request_rejects_blocked_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(
                tmp_root,
                repair_ready=False,
                context_required_count=1,
            )
            approval_decision = self.write_candidate_approval_decision(tmp_root)

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_plan_not_ready", codes)
        self.assertIn("graph_repository_prepare_branch_not_ready", codes)
        self.assertNotIn("git_service_candidate_approval_paths_mismatch", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_cross_run_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root / "plan-b")
            approval_decision = self.write_candidate_approval_decision(tmp_root / "plan-a")

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_source_plan_mismatch", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_unapproved_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                decision_state="needs_context",
                ready=False,
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_approval_not_approved", codes)
        self.assertIn("product_candidate_promotion_approval_not_ready", codes)
        self.assertIn("git_service_candidate_approval_not_approved", codes)
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_request_rejects_unsupported_path_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(
                tmp_root,
                paths=["README.md"],
            )

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("graph_repository_promotion_path_not_allowed", codes)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["commit_paths"], [])

    def test_product_candidate_promotion_request_rejects_truthy_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            plan_path = self.build_graph_repository_execution_plan(tmp_root)
            approval_decision = self.write_candidate_approval_decision(tmp_root)
            payload = json.loads(approval_decision.read_text(encoding="utf-8"))
            payload["authority_boundary"]["may_open_pull_request"] = "true"
            approval_decision.write_text(json.dumps(payload), encoding="utf-8")

            result = self.run_cli(
                "product-candidate-promotion",
                "request",
                "--plan",
                str(plan_path),
                "--approval-decision",
                str(approval_decision),
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_promotion_approval_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ok"])

    def test_product_candidate_promotion_execute_dry_run_plans_git_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "product_candidate_promotion_execution_report.json"
            git_service_output = tmp_root / "git_service_promotion_execution_report.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--output",
                str(output),
                "--git-service-output",
                str(git_service_output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["artifact_kind"],
                "platform_product_candidate_promotion_execution_report",
            )
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["status"], "dry_run")
            self.assertFalse(workspace_dir.exists())
            self.assertTrue(output.is_file())
            self.assertTrue(git_service_output.is_file())
            self.assertTrue(payload["git_service_execution"]["ok"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["git_service_execution"]["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "dry_run")
            self.assertEqual(statuses["commit_candidate"], "skipped_dry_run")
            self.assertFalse(payload["authority_boundary"]["opens_pull_request"])

    def test_product_candidate_promotion_execute_runs_controlled_local_adapter(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            materialized_source = tmp_root / "materialized"
            spec_path = materialized_source / "specs" / "nodes" / "SG-SPEC-CANDIDATE.yaml"
            spec_path.parent.mkdir(parents=True)
            spec_path.write_text(
                "id: SG-SPEC-CANDIDATE\nsummary: Candidate spec\n",
                encoding="utf-8",
            )
            workspace_dir = tmp_root / "candidate-worktree"
            output = tmp_root / "product_candidate_promotion_execution_report.json"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--materialized-source-dir",
                str(materialized_source),
                "--open-review-dry-run",
                "--repo",
                "0al-spec/SpecGraph",
                "--output",
                str(output),
                "--format",
                "json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["diagnostics"])
            self.assertFalse(payload["dry_run"])
            self.assertTrue(payload["open_review_dry_run"])
            self.assertTrue(payload["authority_boundary"]["controlled_git_service_execution"])
            self.assertTrue(
                payload["authority_boundary"]["creates_candidate_worktree_or_branch"]
            )
            self.assertTrue(payload["authority_boundary"]["creates_candidate_commit"])
            self.assertFalse(payload["authority_boundary"]["opens_pull_request"])
            statuses = {
                operation["name"]: operation["status"]
                for operation in payload["git_service_execution"]["operations"]
            }
            self.assertEqual(statuses["prepare_worktree"], "succeeded")
            self.assertEqual(statuses["commit_candidate"], "succeeded")
            self.assertEqual(statuses["open_review"], "dry_run")
            self.assertTrue(output.is_file())
            self.assertTrue(
                (
                    workspace_dir
                    / ".platform"
                    / "git_service_promotion_execution_report.json"
                ).is_file()
            )
            self.assertTrue((workspace_dir / "specs/nodes/SG-SPEC-CANDIDATE.yaml").is_file())
            subject = self.run_git(
                workspace_dir,
                "log",
                "-1",
                "--pretty=%s",
            ).stdout.strip()
            self.assertEqual(subject, "Promote Idea Alpha candidate spec graph")

    def test_product_candidate_promotion_execute_rejects_truthy_request_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request, approval_decision = (
                self.build_product_candidate_promotion_request(tmp_root)
            )
            request_payload = json.loads(promotion_request.read_text(encoding="utf-8"))
            request_payload["authority_boundary"]["opens_pull_requests"] = "true"
            promotion_request.write_text(
                json.dumps(request_payload),
                encoding="utf-8",
            )
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn(
            "product_candidate_promotion_request_authority_expanded",
            codes,
        )
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["git_service_command_result"])

    def test_product_candidate_promotion_execute_rejects_cross_run_decision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            promotion_request = self.build_graph_repository_promotion_request(
                tmp_root / "plan-b"
            )
            approval_decision = self.write_candidate_approval_decision(tmp_root / "plan-a")
            repository_dir = self.create_graph_repository_checkout(tmp_root)
            workspace_dir = tmp_root / "candidate-worktree"

            result = self.run_cli(
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(promotion_request),
                "--approval-decision",
                str(approval_decision),
                "--repository-dir",
                str(repository_dir),
                "--workspace-dir",
                str(workspace_dir),
                "--dry-run",
                "--format",
                "json",
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("product_candidate_promotion_source_plan_mismatch", codes)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["git_service_command_result"])

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
