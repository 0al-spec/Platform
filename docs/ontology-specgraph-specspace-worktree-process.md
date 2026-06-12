# Ontology-SpecGraph-SpecSpace Worktree Process

## Purpose

Use this process when the Ontology, SpecGraph, and SpecSpace line needs to move
in parallel without blocking unrelated work in the primary checkouts.

The process keeps each repository on its own branch and worktree while preserving
the product dependency direction:

1. Ontology defines or emits the source artifact.
2. SpecGraph consumes, validates, and derives review artifacts.
3. SpecSpace presents review surfaces and user actions from those derived
   artifacts.

Platform owns this process as operator coordination only. Canonical contracts,
schemas, code, and tests still belong in the repository that owns the behavior.

## When To Use

Use parallel worktrees for bounded cross-repo slices such as:

- an `ontologyc` adapter/report contract;
- a prompt-agent invocation artifact;
- a SpecSpace review surface artifact/API;
- fixture-first integration work where downstream repositories can consume a
  stable sample before the upstream PR is merged.

Do not use this process to skip repository ownership boundaries. In particular,
do not move Platform or Docker packaging ahead of a stable SpecGraph-to-SpecSpace
contract, and do not introduce canonical mutations before the adapter/review
artifact contract is validated.

## Worktree Layout

Prefer one common root under the local organization checkout:

```bash
ORG_ROOT=/Users/egor/Development/GitHub/0AL
SLICE_ID=ont-sg-0061
WT_ROOT="$ORG_ROOT/.worktrees/ont-sg-ss"
```

Create one branch and one worktree per repository:

```bash
mkdir -p "$WT_ROOT"

git -C "$ORG_ROOT/Ontology" fetch origin
git -C "$ORG_ROOT/Ontology" worktree add \
  -b "codex/${SLICE_ID}-ontologyc-report" \
  "$WT_ROOT/Ontology-${SLICE_ID}" \
  origin/main

git -C "$ORG_ROOT/SpecGraph" fetch origin
git -C "$ORG_ROOT/SpecGraph" worktree add \
  -b "codex/${SLICE_ID}-specgraph-consumer" \
  "$WT_ROOT/SpecGraph-${SLICE_ID}" \
  origin/main

git -C "$ORG_ROOT/SpecSpace" fetch origin
git -C "$ORG_ROOT/SpecSpace" worktree add \
  -b "codex/${SLICE_ID}-review-surface" \
  "$WT_ROOT/SpecSpace-${SLICE_ID}" \
  origin/main
```

If a branch already exists, inspect it first:

```bash
git -C "$ORG_ROOT/<Repo>" status -sb
git -C "$ORG_ROOT/<Repo>" worktree list
```

Then either reuse the existing worktree or create a new worktree from that
branch instead of creating a second branch with the same purpose.

## Slice Contract

Before editing implementation code, write down the bounded contract for the
slice:

- source artifact name and location;
- authority fields and digest/version rules;
- expected derived artifact or API shape;
- failure modes and diagnostics;
- fixture path used by downstream repositories before upstream merge;
- validation command for each repository.

For the current Ontology-SpecGraph-SpecSpace line, the preferred ordering is:

1. `ontologyc` adapter/report contract: document, policy/schema, fixtures, and
   smoke tests.
2. Prompt-agent invocation boundary: typed invocation input, output, evidence
   references, and failure modes.
3. SpecSpace review surface contract: import proposal, resolved references,
   gaps, governance evidence, and review action artifact/API.

## Parallel Work Rules

- Keep each repository branch focused on the smallest owned behavior.
- Let downstream repositories consume fixtures or contract samples while the
  upstream PR is still open.
- Do not point downstream tests at an unmerged sibling checkout unless the PR
  explicitly documents that local-only dependency.
- Keep generated or machine-local state out of tracked files.
- Use explicit file staging and one focused commit per repository slice.
- Open one focused PR per repository and include the validation that was run.
- Merge in dependency order: Ontology, then SpecGraph, then SpecSpace.
- After each merge, rebase or refresh downstream branches onto the updated
  upstream contract and rerun their validation.

## Coordination Log

For cross-repo handoffs, blockers, or decisions, write a local `.0al` ops note
from the repository where the coordination is discovered:

```bash
../.0al/scripts/0al-log.py --project platform --kind note --owner unclassified \
  --title "Ontology-SpecGraph-SpecSpace slice handoff" \
  --text "Record the active slice, open PRs, contract artifact paths, validation, blockers, and next action."
```

Do not put secrets, tokens, private keys, machine-local credentials, or private
customer data into `.0al`.

## Validation Checklist

For each repository worktree:

```bash
git status -sb
git diff --check
```

Then run the repository-owned gates from that repository's `AGENTS.md`,
`README.md`, or task-specific workflow. For documentation-only Platform changes,
at minimum validate markdown structure and links by inspection, and run broader
tests only when the changed content affects executable behavior.

Before merging a stack:

1. Confirm every PR has green required checks.
2. Inspect unresolved GitHub review threads through GraphQL, not only flat PR
   comments.
3. Resolve review feedback in the source PR thread after the fix lands.
4. Merge oldest/upstream PRs first.
5. Refresh downstream branches after each upstream merge.

## Success Criteria

The slice is complete when:

- each repository has a merged, focused PR for its owned behavior;
- downstream repositories no longer depend on local-only upstream paths;
- review artifacts are derived from versioned, digest-checked inputs;
- `.0al` has enough local coordination context for the next operator to resume;
- the primary checkouts can return to `main` without carrying the slice work.
