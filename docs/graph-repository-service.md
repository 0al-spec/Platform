# Graph Repository Service Contract

The Graph Repository Service is the managed write boundary between SpecSpace UI
and a Git-backed SpecGraph workspace.

SpecSpace must not mutate a local checkout directly in production. It should
send authoring and promotion intent to a repository service that owns candidate
workspace allocation, validation gates, branch/commit creation, review opening,
and public-safe read-model publication.

## Current Slice

This repository currently defines the contract shape, example artifact, and
local validator:

- schema: `schemas/graph-repository-service-contract.schema.json`;
- example: `graph-repository-service.example.json`;
- CLI: `scripts/platform.py graph-repository validate`;
- report-only execution plan: `scripts/platform.py graph-repository plan`.

The validator is intentionally stricter than ordinary JSON parsing. It checks
the schema and report-only authority rules:

- no canonical spec mutation without review;
- no Ontology package writes;
- no candidate acceptance without gates;
- no merge without policy;
- no private artifact publication;
- `promotion_policy.auto_merge_allowed` remains false in the MVP.

## Minimal Flow

```text
SpecSpace UI
  -> Graph Repository Service
  -> create_candidate_workspace
  -> validate_candidate_graph
  -> prepare_branch
  -> create_commit
  -> open_review
  -> publish_read_model
```

The first implementation can be a local CLI/service wrapper around Git
worktrees and `make publish-bundle`. Hosted production can later replace the
storage backend with a managed Git provider or queue-backed worker without
changing the UI authority model.

## Validate

```bash
scripts/platform.py graph-repository validate \
  --contract graph-repository-service.example.json
```

Use JSON output for CI:

```bash
scripts/platform.py graph-repository validate \
  --contract graph-repository-service.example.json \
  --format json
```

## Plan

Build a local report-only execution plan from SpecGraph run artifacts:

```bash
scripts/platform.py graph-repository plan \
  --contract graph-repository-service.example.json \
  --runs-dir ../SpecGraph/runs \
  --output runs/graph_repository_execution_plan.json
```

The planner requires these SpecGraph artifacts:

- `idea_event_storming_intake.json`;
- `candidate_spec_graph.json`;
- `pre_sib_coherence_report.json`;
- `candidate_repair_loop_report.json`.

Each artifact must remain review-only:

- `canonical_mutations_allowed: false`;
- `tracked_artifacts_written: false`.

The planner does not run Git, create commits, open pull requests, publish read
models, write Ontology packages, or mutate canonical SpecGraph specs. It only
reports whether the read-only inputs are ready for the later repository service
executor.
