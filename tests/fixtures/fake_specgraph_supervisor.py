#!/usr/bin/env python3
"""Test double for SpecGraph tools/supervisor.py.

Controlled via env vars:
- FAKE_SUPERVISOR_OUTCOME: "ready" (default) | "blocked" | "crash" |
  "no_report" | "chatty" | "hang"
- FAKE_SUPERVISOR_ARGV_LOG: optional path; if set, each invocation appends
  its argv as a JSON line for the calling test to inspect.
- FAKE_SUPERVISOR_HANG_SECONDS: seconds to sleep before producing output
  when outcome is "hang"; defaults to 5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    log_path = os.environ.get("FAKE_SUPERVISOR_ARGV_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")

    parser = argparse.ArgumentParser()
    parser.add_argument("--init-product-workspace", action="store_true", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--root-intent")
    args = parser.parse_args(argv[1:])

    outcome = os.environ.get("FAKE_SUPERVISOR_OUTCOME", "ready")

    if outcome == "crash":
        sys.stderr.write("fake supervisor: simulated crash\n")
        return 2

    if outcome == "hang":
        hang_for = float(os.environ.get("FAKE_SUPERVISOR_HANG_SECONDS", "5"))
        time.sleep(hang_for)
        # Should be killed by the parent timeout before reaching this line in tests.
        return 0

    if outcome == "chatty":
        sys.stdout.write("supervisor: starting initialization\n")
        sys.stdout.write("supervisor: writing artifacts\n")
        sys.stdout.flush()

    workspace_root = Path(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "runs").mkdir(exist_ok=True)
    (workspace_root / "specs").mkdir(exist_ok=True)
    (workspace_root / "docs" / "proposals").mkdir(parents=True, exist_ok=True)
    project_config_path = workspace_root / "specgraph.project.yaml"
    project_config_path.write_text(
        f"project: {args.project_id}\n",
        encoding="utf-8",
    )

    if outcome == "no_report":
        return 0

    if outcome == "blocked":
        status = "blocked"
        review_state = "blocked"
        findings = [
            {
                "level": "ERROR",
                "code": "fake_blocker",
                "subject": "workspace",
                "message": "fake supervisor reports a blocker",
            }
        ]
    else:
        status = "initialized"
        review_state = "ready_for_review"
        findings = []

    binding_evidence = {
        "contract_ref": "specgraph.product-workspace.binding-evidence.v0.1",
        "proposal_id": "0211",
        "status": "ready" if status == "initialized" else "blocked",
        "identity": {
            "workspace_id": args.project_id,
            "display_name": args.display_name,
            "governance_profile": "product_workspace",
            "repository_role": "product_spec_workspace",
        },
        "layout": {
            "root_reference": "workspace_relative",
            "project_config_ref": "specgraph.project.yaml",
            "specs_root_ref": "specs",
            "proposals_root_ref": "docs/proposals",
            "runs_root_ref": "runs",
            "supervisor_state_root_ref": ".specgraph",
        },
        "project_config": {
            "source_ref": "specgraph.project.yaml",
            "source_sha256": hashlib.sha256(project_config_path.read_bytes()).hexdigest(),
        },
        "repository": {
            "repository_role": "product_spec_workspace",
            "workspace_identity": args.project_id,
            "worktree_identity": f"product-workspace/{args.project_id}",
            "creates_worktree": False,
        },
        "privacy_boundary": {
            "workspace_relative_refs_only": True,
            "local_input_path_persisted": False,
            "raw_root_intent_published": False,
        },
        "authority_boundary": {
            "report_only": True,
            "may_execute_platform": False,
            "may_mutate_canonical_specs": False,
            "may_write_ontology_packages": False,
            "may_accept_ontology_terms": False,
            "may_create_git_commit": False,
            "may_open_pull_request": False,
        },
    }
    binding_evidence["evidence_sha256"] = hashlib.sha256(
        json.dumps(
            binding_evidence,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    report = {
        "artifact_kind": "product_workspace_initialization",
        "project": {
            "project_id": args.project_id,
            "display_name": args.display_name,
            "governance_profile": "product_workspace",
        },
        "workspace": {
            "created_paths": ["specs", "runs", "docs/proposals"],
            "existing_paths": [],
            "root_reference": str(workspace_root),
        },
        "root_intent": {
            "status": "captured" if args.root_intent else "absent",
            "artifact_path": "docs/proposals/root_intent.md" if args.root_intent else None,
            "content_sha256": None,
        },
        "validation_findings": findings,
        "workspace_binding_evidence": binding_evidence,
        "review_state": review_state,
        "summary": {"status": status},
    }

    (workspace_root / "runs" / "product_workspace_initialization.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
