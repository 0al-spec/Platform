#!/usr/bin/env python3
"""Test double for SpecGraph tools/supervisor.py.

Controlled via env vars:
- FAKE_SUPERVISOR_OUTCOME: "ready" (default) | "blocked" | "crash" | "no_report"
- FAKE_SUPERVISOR_ARGV_LOG: optional path; if set, each invocation appends
  its argv as a JSON line for the calling test to inspect.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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

    workspace_root = Path(args.workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "runs").mkdir(exist_ok=True)
    (workspace_root / "specs").mkdir(exist_ok=True)
    (workspace_root / "docs" / "proposals").mkdir(parents=True, exist_ok=True)
    (workspace_root / "specgraph.project.yaml").write_text(
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
