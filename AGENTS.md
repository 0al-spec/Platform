# Platform Agent Instructions

## Task Pull Requests

For every task that changes tracked repository files, finish by creating or
updating a focused GitHub pull request for that task unless the user explicitly
asks not to. Keep the PR scoped to the task, push the branch, include the
validation performed, and use the repository pull request template when one
exists.

## Python Environment

Use the repository virtual environment for local Python commands. Prefer
`.venv/bin/python` directly or run Make targets that default to it when present.
Do not run broad local validation with the system Python unless no repository
virtual environment exists yet.

## 0AL Local Ops Logging

For cross-repo observations, coordination tasks, blockers, or handoffs, write a
local ops entry through the `.0al` logging CLI when it is available:

```bash
../.0al/scripts/0al-log.py --project platform --kind note --owner unclassified \
  --title "<short title>" \
  --text "<what happened, what is needed, and any suggested next action>"
```

Use `.0al` only for coordination. Canonical Platform changes belong in this
repository. Do not edit `../.0al/tasks.md` or `../.0al/decisions.md` directly unless
the user explicitly asks for tracker maintenance, and never write secrets,
credentials, private keys, or machine-local tokens to `.0al`.

## Cross-Repo Worktrees

When coordinating parallel Ontology-SpecGraph-SpecSpace work, follow the explicit
[Ontology-SpecGraph-SpecSpace worktree process](docs/ontology-specgraph-specspace-worktree-process.md).

For the active Ontology-SpecGraph-SpecSpace sequencing and next recommended
slice, consult the
[Ontology-SpecGraph-SpecSpace roadmap](docs/ontology-specgraph-specspace-roadmap.md).
