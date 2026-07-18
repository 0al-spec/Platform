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
                "merges_pull_requests": False,
                "publishes_read_models": False,
                "ontology_package_write": False,
                "ontology_term_acceptance": False,
                "private_artifact_publication": False,
                "specspace_direct_git_write": False,
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
                "status": "review_probe_completed",
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
                "accepts_arbitrary_commands": False,
                "expands_operation_allowlist": False,
                "executes_unpinned_requests": False,
                "keeps_worker_running": False,
                "retries_irreversible_operations": False,
                "queue_status_is_lifecycle_evidence": False,
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


if __name__ == "__main__":
    unittest.main()
