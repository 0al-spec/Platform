# Local Service Launch Plan

## Context

Platform is the local control plane for running the 0AL service set from sibling
checkouts under one operator-managed `0AL/` root. Phase 1 through Phase 3
established repository boundaries, workspace catalog validation, and delegated
product workspace initialization.

Phase 4 makes local service launch an explicit Platform responsibility without
collapsing service ownership. Platform owns topology, Compose wiring, local
operator commands, and deployment profiles. SpecGraph, SpecSpace, and SpecPM
continue to own their own runtime contracts.

## Target Outcome

A solo operator can start, inspect, and stop the local 0AL surface with one
Platform command surface:

```bash
scripts/platform.py deploy render
scripts/platform.py deploy up
scripts/platform.py deploy status
scripts/platform.py deploy down
```

The default profile should run on one machine and map cleanly to a low-cost VPS
deployment later. The canonical production path is a Compose-managed set of
separate services, not one long-running all-in-one process.

## Implementation Slices

### Slice 1: Runnable Compose Entry Point

Status: implemented in PR #10.

- Add `.env.example` for local knobs.
- Add `deploy render/up/status/down` wrappers around Docker Compose.
- Parameterize ports, images, and public API URLs.
- Keep tracked Compose files portable and placeholder-based.
- Make `http://127.0.0.1:8081/`, `http://127.0.0.1:8001/`, and
  `http://127.0.0.1:5173/` useful operator entry points.

### Slice 2: Health And Readiness

Status: next.

- Add Compose health checks for SpecPM public index, SpecSpace API, and
  SpecSpace web.
- Keep health checks dependency-light: use Python in Python containers and Node
  in Node containers instead of requiring extra curl/wget packages.
- Treat `deploy status` as the operator's first readiness view.

### Slice 3: Production Static Web Profile

Status: planned.

- Stop treating the Vite development server as the production shape.
- Add a production web service that builds SpecSpace static assets and serves
  them through a small static server or reverse proxy.
- Keep the development profile available for local iteration.

### Slice 4: CI-Produced Compose Artifact

Status: planned.

- Make CI render or publish the deployment Compose file that Timeweb can consume.
- Keep machine-local `.env` values outside git.
- Prefer image tags and immutable inputs over rebuilding from live checkouts on
  the VPS.

### Slice 5: Image Hardening

Status: planned.

- Move startup dependency installation into owned images.
- Pin image tags and make runtime containers start quickly.
- Preserve separate logs and health checks per service.

## Guardrails

- Do not require one VPS per service.
- Do not make all-in-one images the primary deployment contract.
- Do not store secrets, tokens, private keys, or machine-local absolute paths in
  tracked files.
- Do not make Platform implement SpecGraph, SpecSpace, or SpecPM business
  logic.
- Do not hide service ownership by merging components into one process.

## Validation

For every local launch slice:

```bash
python3 -m unittest discover -s tests
python3 -m compileall scripts/platform.py tests
git diff --check
ORG_ROOT=/path/to/0AL scripts/platform.py deploy render
ORG_ROOT=/path/to/0AL scripts/platform.py deploy up
ORG_ROOT=/path/to/0AL scripts/platform.py deploy status
curl -fsS http://127.0.0.1:8001/api/v1/health
curl -fsS http://127.0.0.1:8081/v0/status/index.json
curl -fsS http://127.0.0.1:5173/
```

When the SpecPM browser entry point changes, also verify:

```bash
curl -fsS http://127.0.0.1:8081/
```
