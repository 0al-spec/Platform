from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import hosted_managed_public_report_publication as publication


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Response:
    status = 204


class HostedManagedPublicReportPublicationTests(unittest.TestCase):
    def execution_report(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": publication.PROMOTION_EXECUTION_KIND,
            "ok": True,
            "dry_run": False,
            "open_review_dry_run": False,
            "workflow_lane": "product_idea_to_spec",
            "workspace_id": publication.WORKSPACE_ID,
            "candidate_id": publication.WORKSPACE_ID,
            "candidate_branch": "graph-candidate/hosted-operation-canary",
            "authority_boundary": {
                "controlled_git_service_execution": True,
                "creates_candidate_commit": True,
                "creates_candidate_worktree_or_branch": True,
                "opens_pull_requests": True,
                "merges_pull_requests": False,
                "publishes_read_models": False,
                "ontology_package_write": False,
                "ontology_term_acceptance": False,
                "private_artifact_publication": False,
                "specspace_direct_git_write": False,
            },
            "workspace_binding": self.workspace_binding(),
        }

    def workspace_binding(self) -> dict:
        return {
            "status": "ready",
            "workspace_id": publication.WORKSPACE_ID,
            "binding_id": (
                f"product-workspace-binding://{publication.WORKSPACE_ID}"
            ),
            "binding_revision_sha256": "c" * 64,
            "source_sha256": "d" * 64,
            "authority_boundary": {
                "may_create_git_commit": False,
                "may_execute_platform": False,
                "may_execute_specgraph": False,
                "may_open_pull_request": False,
                "may_publish_read_model": False,
                "report_only": True,
            },
        }

    def review_evidence(self, execution_digest: str) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": publication.REVIEW_OBJECT_KIND,
            "generated_at": "2026-07-18T12:00:00+00:00",
            "ok": True,
            "probe_only": True,
            "promotion_execution_report_ref": (
                "runs/product_candidate_promotion_execution_report.json"
            ),
            "promotion_execution_report_sha256": execution_digest,
            "workspace_id": publication.WORKSPACE_ID,
            "candidate_id": publication.WORKSPACE_ID,
            "candidate_branch": "graph-candidate/hosted-operation-canary",
            "review_url": "https://github.com/0al-spec/SpecGraph/pull/690",
            "review_number": 690,
            "review_state_at_capture": "open",
            "review_head_sha": "a" * 40,
            "base_branch": "main",
            "command": ["gh", "pr", "view"],
            "command_result": {"stdout": "/Users/private"},
            "privacy_boundary": {
                "public_safe": True,
                "raw_idea_included": False,
                "local_paths_included": False,
            },
            "authority_boundary": {
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "publishes_read_models": False,
                "creates_git_commits": False,
                "mutates_canonical_specs": False,
                "writes_ontology_packages": False,
                "accepts_ontology_terms": False,
            },
            "workspace_binding": self.workspace_binding(),
        }

    def review_status(self) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": publication.REVIEW_STATUS_KIND,
            "generated_at": "2026-07-18T12:05:00+00:00",
            "ok": True,
            "workflow_lane": "product_idea_to_spec",
            "workspace_id": publication.WORKSPACE_ID,
            "candidate_id": publication.WORKSPACE_ID,
            "candidate_branch": "graph-candidate/hosted-operation-canary",
            "review_probe_only": False,
            "review_state": "open",
            "review_decision": "",
            "workspace_dir": "/srv/private",
            "graph_repository_command": ["gh", "pr", "view"],
            "graph_repository_command_result": {"stdout": "/home/private"},
            "pull_request": {
                "number": 690,
                "url": "https://github.com/0al-spec/SpecGraph/pull/690",
                "state": "OPEN",
                "isDraft": False,
                "headRefName": "graph-candidate/hosted-operation-canary",
                "baseRefName": "main",
                "headRefOid": "a" * 40,
                "reviewDecision": "",
                "mergedAt": None,
                "mergeCommit": None,
            },
            "graph_repository_review_status": {
                "artifact_kind": "platform_graph_repository_review_status_report",
                "ok": True,
                "review_state": "open",
                "review_url": "https://github.com/0al-spec/SpecGraph/pull/690",
                "summary": {
                    "status": "waiting_for_review_merge",
                    "review_merged": False,
                },
            },
            "summary": {
                "status": "waiting_for_review_merge",
                "review_merged": False,
                "read_model_published": False,
                "error_count": 0,
            },
            "authority_boundary": {
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "publishes_read_models": False,
                "canonical_spec_mutation_without_review": False,
                "ontology_package_write": False,
                "ontology_term_acceptance": False,
                "private_artifact_publication": False,
                "specspace_direct_git_write": False,
            },
        }

    def worker_window(self, report_digest: str) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": publication.WORKER_WINDOW_KIND,
            "contract_ref": publication.WORKER_WINDOW_CONTRACT_REF,
            "window_id": "review-status-20260718t120000z",
            "request": {
                "operation_id": publication.OPERATION_ID,
                "workspace_id": publication.WORKSPACE_ID,
                "request_id": (
                    "managed-operation://hosted-operation-canary/"
                    "review_status_execute/0123456789abcdef01234567"
                ),
                "initial_attempt": 0,
            },
            "execution": {
                "operation_processed": True,
                "receipt_status": "succeeded",
                "attempt": 1,
                "authoritative_output_reports": [
                    {
                        "logical_ref": publication.REVIEW_STATUS_REF,
                        "sha256": report_digest,
                    }
                ],
            },
            "summary": {
                "status": "bounded_worker_window_completed",
                "one_shot_cycle_complete": True,
                "queue_drained": True,
                "processed_operation_count": 1,
                "authoritative_reports_ready": True,
            },
            "privacy_boundary": {
                "public_safe": True,
                "includes_request_payload": False,
                "includes_secret_values": False,
                "includes_local_paths": False,
            },
            "authority_boundary": {
                "platform_output_reports_are_authoritative": True,
                "executes_one_pinned_allowlisted_operation": True,
                "accepts_arbitrary_commands": False,
                "expands_operation_allowlist": False,
                "executes_unpinned_requests": False,
                "keeps_worker_running": False,
                "retries_irreversible_operations": False,
                "queue_status_is_lifecycle_evidence": False,
            },
        }

    def merged_review_status(self) -> dict:
        payload = self.review_status()
        payload["review_state"] = "merged"
        payload["pull_request"].update(
            {
                "state": "MERGED",
                "mergedAt": "2026-07-19T10:08:00Z",
                "mergeCommit": {"oid": "b" * 40},
            }
        )
        payload["graph_repository_review_status"]["review_state"] = "merged"
        payload["graph_repository_review_status"]["summary"] = {
            "status": "ready_for_read_model_publication",
            "review_merged": True,
        }
        payload["summary"] = {
            "status": "ready_for_read_model_publication",
            "review_merged": True,
            "read_model_published": False,
            "error_count": 0,
        }
        return payload

    def read_model_publication(self, review_status_digest: str) -> dict:
        return {
            "schema_version": 1,
            "artifact_kind": publication.READ_MODEL_PUBLICATION_KIND,
            "generated_at": "2026-07-19T10:10:00+00:00",
            "ok": True,
            "dry_run": False,
            "workflow_lane": "product_idea_to_spec",
            "workspace_id": publication.WORKSPACE_ID,
            "candidate_id": publication.WORKSPACE_ID,
            "candidate_branch": publication.CANDIDATE_BRANCH,
            "review_state": "merged",
            "product_review_status_report_ref": (
                "/tmp/product_candidate_promotion_review_status_report.json"
            ),
            "product_review_status_report_sha256": review_status_digest,
            "bundle_dir": "/tmp/private-bundle",
            "output_dir": "/tmp/private-read-model",
            "graph_repository_command": ["platform", "publish-read-model"],
            "graph_repository_command_result": {"stdout": "/Users/private"},
            "graph_repository_publish_read_model": {
                "artifact_kind": publication.GRAPH_READ_MODEL_PUBLICATION_KIND,
                "ok": True,
                "dry_run": False,
                "review_state": "merged",
                "read_models_published": [
                    "/tmp/private-read-model/artifact_manifest.json"
                ],
                "summary": {
                    "published": True,
                    "file_count": 1530,
                    "error_count": 0,
                },
            },
            "authority_boundary": {
                "executes_git_commands": False,
                "opens_pull_requests": False,
                "merges_pull_requests": False,
                "publishes_read_models": True,
                "canonical_spec_mutation_without_review": False,
                "ontology_package_write": False,
                "ontology_term_acceptance": False,
                "private_artifact_publication": False,
                "specspace_direct_git_write": False,
            },
            "summary": {
                "status": "published",
                "review_merged": True,
                "read_model_published": True,
                "published_manifest": (
                    "/tmp/private-read-model/artifact_manifest.json"
                ),
                "error_count": 0,
            },
        }

    def test_review_object_packet_drops_command_and_local_path_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            write_json(execution, self.execution_report())
            write_json(evidence, self.review_evidence(sha256(execution)))

            report, provenance = publication.build_review_object_report(
                evidence_path=evidence.resolve(),
                execution_report_path=execution.resolve(),
            )
            packet = publication.build_packet(
                logical_ref=publication.REVIEW_OBJECT_REF,
                report=report,
                provenance=provenance,
            )

        rendered = json.dumps(packet)
        self.assertNotIn("command", report)
        self.assertNotIn("/Users", rendered)
        self.assertEqual(packet["summary"]["report_count"], 1)
        self.assertEqual(packet["report"]["review_number"], 690)
        self.assertEqual(
            packet["report"]["workspace_binding"],
            {
                "status": "ready",
                "workspace_id": publication.WORKSPACE_ID,
                "binding_id": (
                    f"product-workspace-binding://{publication.WORKSPACE_ID}"
                ),
            },
        )

    def test_review_status_requires_digest_pinned_attempt_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"
            write_json(source, self.review_status())
            write_json(window, self.worker_window(sha256(source)))

            report, provenance = publication.build_review_status_report(
                worker_window_path=window.resolve(),
                source_report_path=source.resolve(),
            )
            packet = publication.build_packet(
                logical_ref=publication.REVIEW_STATUS_REF,
                report=report,
                provenance=provenance,
            )
            invalid = self.worker_window(sha256(source))
            invalid["execution"]["attempt"] = 2
            write_json(window, invalid)
            with self.assertRaisesRegex(publication.PublicationError, "does not pin"):
                publication.build_review_status_report(
                    worker_window_path=window.resolve(),
                    source_report_path=source.resolve(),
                )

        rendered = json.dumps(packet)
        self.assertNotIn("/srv/private", rendered)
        self.assertNotIn("/home/private", rendered)
        self.assertNotIn("graph_repository_command", report)
        self.assertEqual(report["review_state"], "open")
        self.assertEqual(provenance["attempt"], 1)

    def test_read_model_publication_packet_pins_merged_review_and_is_public_safe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_status = root / "review-status.json"
            worker_window = root / "worker-window.json"
            source = root / "publication.json"
            write_json(review_status, self.merged_review_status())
            write_json(worker_window, self.worker_window(sha256(review_status)))
            write_json(source, self.read_model_publication(sha256(review_status)))

            report, provenance = (
                publication.build_read_model_publication_report(
                    worker_window_path=worker_window.resolve(),
                    review_status_report_path=review_status.resolve(),
                    source_report_path=source.resolve(),
                )
            )
            packet = publication.build_packet(
                logical_ref=publication.READ_MODEL_PUBLICATION_REF,
                report=report,
                provenance=provenance,
            )

        rendered = json.dumps(packet)
        self.assertEqual(
            packet["operation_id"],
            publication.READ_MODEL_PUBLICATION_OPERATION_ID,
        )
        self.assertEqual(report["summary"]["status"], "published")
        self.assertEqual(report["summary"]["published_file_count"], 1530)
        self.assertEqual(report["review"]["number"], 690)
        self.assertTrue(report["authority_boundary"]["publishes_read_models"])
        self.assertNotIn("/tmp/", rendered)
        self.assertNotIn("/Users/", rendered)
        self.assertNotIn("graph_repository_command", rendered)
        self.assertEqual(provenance["attempt"], 1)

    def test_read_model_publication_rejects_digest_and_authority_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_status = root / "review-status.json"
            worker_window = root / "worker-window.json"
            source = root / "publication.json"
            write_json(review_status, self.merged_review_status())
            write_json(worker_window, self.worker_window(sha256(review_status)))

            payload = self.read_model_publication("e" * 64)
            write_json(source, payload)
            with self.assertRaisesRegex(
                publication.PublicationError,
                "not public-publication ready",
            ):
                publication.build_read_model_publication_report(
                    worker_window_path=worker_window.resolve(),
                    review_status_report_path=review_status.resolve(),
                    source_report_path=source.resolve(),
                )

            payload = self.read_model_publication(sha256(review_status))
            payload["authority_boundary"]["may_publish_private_artifacts"] = True
            write_json(source, payload)
            with self.assertRaisesRegex(
                publication.PublicationError,
                "not public-publication ready",
            ):
                publication.build_read_model_publication_report(
                    worker_window_path=worker_window.resolve(),
                    review_status_report_path=review_status.resolve(),
                    source_report_path=source.resolve(),
                )

    def test_invalid_authority_blocks_without_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            write_json(execution, self.execution_report())
            payload = self.review_evidence(sha256(execution))
            payload["authority_boundary"]["may_merge_review"] = True
            write_json(evidence, payload)

            with self.assertRaisesRegex(publication.PublicationError, "not public"):
                publication.build_review_object_report(
                    evidence_path=evidence.resolve(),
                    execution_report_path=execution.resolve(),
                )

    def test_review_object_requires_expected_non_dry_run_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            payload = self.execution_report()
            payload["authority_boundary"]["opens_pull_requests"] = False
            write_json(execution, payload)
            write_json(evidence, self.review_evidence(sha256(execution)))

            with self.assertRaisesRegex(publication.PublicationError, "expands authority"):
                publication.build_review_object_report(
                    evidence_path=evidence.resolve(),
                    execution_report_path=execution.resolve(),
                )

    def test_review_object_rejects_additional_true_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            payload = self.execution_report()
            payload["authority_boundary"]["may_publish_private_artifacts"] = True
            write_json(execution, payload)
            write_json(evidence, self.review_evidence(sha256(execution)))

            with self.assertRaisesRegex(publication.PublicationError, "expands authority"):
                publication.build_review_object_report(
                    evidence_path=evidence.resolve(),
                    execution_report_path=execution.resolve(),
                )

    def test_review_object_rejects_foreign_workspace_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            write_json(execution, self.execution_report())
            payload = self.review_evidence(sha256(execution))
            payload["workspace_binding"]["workspace_id"] = "foreign-workspace"
            write_json(evidence, payload)

            with self.assertRaisesRegex(publication.PublicationError, "binding"):
                publication.build_review_object_report(
                    evidence_path=evidence.resolve(),
                    execution_report_path=execution.resolve(),
                )

    def test_review_object_rejects_binding_revision_drift_from_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution = root / "execution.json"
            evidence = root / "evidence.json"
            write_json(execution, self.execution_report())
            payload = self.review_evidence(sha256(execution))
            payload["workspace_binding"]["binding_revision_sha256"] = "e" * 64
            write_json(evidence, payload)

            with self.assertRaisesRegex(publication.PublicationError, "does not match"):
                publication.build_review_object_report(
                    evidence_path=evidence.resolve(),
                    execution_report_path=execution.resolve(),
                )

    def test_dispatch_is_fixed_and_does_not_expose_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            packet_path = root / "packet.json"
            token_file = root / "token"
            report = self.review_status()
            report.pop("workspace_dir")
            report.pop("graph_repository_command")
            report.pop("graph_repository_command_result")
            packet = publication.build_packet(
                logical_ref=publication.REVIEW_STATUS_REF,
                report=report,
                provenance={"source_sha256": "a" * 64},
            )
            write_json(packet_path, packet)
            token_file.write_text("secret-token-value-0123456789\n")
            captured: dict = {}

            def opener(request, timeout):
                captured["url"] = request.full_url
                captured["headers"] = dict(request.header_items())
                captured["body"] = json.loads(request.data)
                captured["timeout"] = timeout
                return Response()

            dispatch = publication.dispatch_packet(
                packet_path=packet_path.resolve(),
                token_file=token_file.resolve(),
                ref="main",
                urlopen=opener,
            )

            self.assertEqual(
                dispatch["summary"]["status"],
                "publication_dispatch_accepted",
            )
            self.assertIn(publication.GITHUB_REPOSITORY, captured["url"])
            self.assertEqual(captured["body"]["ref"], "main")
            self.assertNotIn("secret-token", json.dumps(dispatch))
            self.assertNotIn("secret-token", json.dumps(captured["body"]))
            self.assertEqual(
                dispatch["publication_packet_sha256"],
                hashlib.sha256(publication._json_bytes(packet)).hexdigest(),
            )

            with self.assertRaisesRegex(publication.PublicationError, "must be main"):
                publication.dispatch_packet(
                    packet_path=packet_path.resolve(),
                    token_file=token_file.resolve(),
                    ref="feature-branch",
                    urlopen=opener,
                )

            injected = json.loads(json.dumps(packet))
            injected["source_provenance"]["note"] = "/srv/0al/private/report.json"
            write_json(packet_path, injected)
            with self.assertRaisesRegex(publication.PublicationError, "local path"):
                publication.dispatch_packet(
                    packet_path=packet_path.resolve(),
                    token_file=token_file.resolve(),
                    ref="main",
                    urlopen=opener,
                )

            packet_path.write_text(
                json.dumps(packet, separators=(",", ":")),
                encoding="utf-8",
            )
            compact_file_digest = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            dispatch = publication.dispatch_packet(
                packet_path=packet_path.resolve(),
                token_file=token_file.resolve(),
                ref="main",
                urlopen=opener,
            )
            self.assertNotEqual(
                dispatch["publication_packet_sha256"],
                compact_file_digest,
            )
            self.assertEqual(
                dispatch["publication_packet_sha256"],
                hashlib.sha256(publication._json_bytes(packet)).hexdigest(),
            )

            injected = json.loads(json.dumps(packet))
            injected["source_provenance"]["github_token"] = "not-a-real-secret"
            write_json(packet_path, injected)
            with self.assertRaisesRegex(
                publication.PublicationError,
                "forbidden field",
            ):
                publication.dispatch_packet(
                    packet_path=packet_path.resolve(),
                    token_file=token_file.resolve(),
                    ref="main",
                    urlopen=opener,
                )

    def test_digest_mismatch_blocks_review_status_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"
            write_json(source, self.review_status())
            write_json(window, self.worker_window("b" * 64))

            with self.assertRaisesRegex(publication.PublicationError, "does not pin"):
                publication.build_review_status_report(
                    worker_window_path=window.resolve(),
                    source_report_path=source.resolve(),
                )

    def test_review_status_requires_positive_pinned_operation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"
            write_json(source, self.review_status())

            for value in (False, None):
                payload = self.worker_window(sha256(source))
                if value is None:
                    payload["authority_boundary"].pop(
                        "executes_one_pinned_allowlisted_operation"
                    )
                else:
                    payload["authority_boundary"][
                        "executes_one_pinned_allowlisted_operation"
                    ] = value
                write_json(window, payload)
                with self.assertRaisesRegex(
                    publication.PublicationError,
                    "does not pin",
                ):
                    publication.build_review_status_report(
                        worker_window_path=window.resolve(),
                        source_report_path=source.resolve(),
                    )

    def test_review_status_preserves_probe_without_publication_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"
            payload = self.review_status()
            payload["review_probe_only"] = True
            payload["summary"]["status"] = "review_probe_completed"
            write_json(source, payload)
            write_json(window, self.worker_window(sha256(source)))

            report, _provenance = publication.build_review_status_report(
                worker_window_path=window.resolve(),
                source_report_path=source.resolve(),
            )

        self.assertTrue(report["review_probe_only"])
        self.assertEqual(report["review_state"], "open")
        self.assertEqual(report["summary"]["status"], "review_probe_completed")
        self.assertEqual(
            report["graph_repository_review_status"]["summary"]["status"],
            "review_probe_completed",
        )
        self.assertFalse(report["summary"]["review_merged"])
        self.assertFalse(report["summary"]["read_model_published"])

    def test_review_status_normalizes_legacy_closed_status_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"
            payload = self.review_status()
            payload["review_state"] = "closed"
            payload["pull_request"]["state"] = "CLOSED"
            payload["graph_repository_review_status"]["review_state"] = "closed"
            # This is the immutable status emitted by the pre-fix producer.
            payload["summary"]["status"] = "waiting_for_review_merge"
            write_json(source, payload)
            write_json(window, self.worker_window(sha256(source)))

            report, provenance = publication.build_review_status_report(
                worker_window_path=window.resolve(),
                source_report_path=source.resolve(),
            )

        self.assertEqual(report["review_state"], "closed")
        self.assertEqual(
            report["summary"]["status"],
            "review_closed_without_merge",
        )
        self.assertEqual(
            report["graph_repository_review_status"]["summary"]["status"],
            "review_closed_without_merge",
        )
        self.assertFalse(report["summary"]["review_merged"])
        self.assertEqual(provenance["attempt"], 1)

    def test_review_status_rejects_probe_foreign_branch_and_state_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "status.json"
            window = root / "window.json"

            for mutate in (
                lambda payload: payload.__setitem__("review_probe_only", True),
                lambda payload: payload.__setitem__(
                    "candidate_branch",
                    "graph-candidate/foreign",
                ),
                lambda payload: payload["summary"].__setitem__(
                    "status",
                    "ready_for_read_model_publication",
                ),
                lambda payload: payload["pull_request"].__setitem__(
                    "state",
                    "MERGED",
                ),
            ):
                payload = self.review_status()
                mutate(payload)
                write_json(source, payload)
                write_json(window, self.worker_window(sha256(source)))
                with self.assertRaisesRegex(
                    publication.PublicationError,
                    "not public-publication ready|identity",
                ):
                    publication.build_review_status_report(
                        worker_window_path=window.resolve(),
                        source_report_path=source.resolve(),
                    )

    def test_public_packet_rejects_non_may_authority_secret_and_non_finite_json(
        self,
    ) -> None:
        report = self.review_status()
        report.pop("workspace_dir")
        report.pop("graph_repository_command")
        report.pop("graph_repository_command_result")
        packet = publication.build_packet(
            logical_ref=publication.REVIEW_STATUS_REF,
            report=report,
            provenance={"source_sha256": "a" * 64},
        )

        injected = json.loads(json.dumps(packet))
        injected["authority_boundary"]["executes_managed_operations"] = True
        with self.assertRaisesRegex(publication.PublicationError, "dispatch-ready"):
            publication.validate_packet_for_dispatch(injected)

        injected = json.loads(json.dumps(packet))
        injected["source_provenance"]["detail"] = "github_pat_" + "a" * 32
        with self.assertRaisesRegex(publication.PublicationError, "secret-like"):
            publication.validate_packet_for_dispatch(injected)

        injected = json.loads(json.dumps(packet))
        injected["source_provenance"]["depth"] = float("nan")
        with self.assertRaisesRegex(publication.PublicationError, "non-strict JSON"):
            publication.validate_packet_for_dispatch(injected)


if __name__ == "__main__":
    unittest.main()
