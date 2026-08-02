# Mac Product Workspace

The Mac product-workspace profile is the local single-operator path for writing
specifications through SpecSpace. It composes the existing SpecSpace UI,
SpecSpace backend-managed execution, Platform wrappers, and a sibling SpecGraph
checkout without enabling the hosted queue or production Git operations.

## Boundary

```text
browser
  -> authenticated SpecSpace backend
  -> allowlisted local Platform wrapper
  -> workspace-scoped SpecGraph run artifacts
```

The browser does not execute a shell. SpecSpace does not mutate canonical specs
or Ontology packages directly. Git review and publication remain separate
controlled lifecycle operations.

## Prerequisites

Keep `Platform`, `SpecGraph`, `SpecSpace`, and `ChatGPTDialogs` as sibling
checkouts under one organization root. Platform and SpecSpace dependencies must
already be installed:

```text
0AL/
  Platform/
  SpecGraph/
  SpecSpace/
  ChatGPTDialogs/canonical_json/
```

The default operator credential is read from the macOS Keychain generic-password
item used by production smoke:

```text
service: 0AL SpecSpace production smoke
account: operator
```

Override the service without exposing the password:

```bash
SPECSPACE_OPERATOR_AUTH_KEYCHAIN_SERVICE='0AL SpecSpace local operator' \
make mac-product-workspace
```

## Commands

```bash
make mac-product-workspace-doctor
make mac-product-workspace
make mac-product-workspace-status
make mac-product-workspace-stop
make mac-product-workspace-e2e
```

The UI opens at `http://127.0.0.1:5175`. The default persistent operator state
is stored outside the checkout at:

```text
~/Library/Application Support/0AL/SpecSpace/state
```

New product workspaces and their Platform catalog also live outside every Git
checkout:

```text
~/Library/Application Support/0AL/SpecSpace/workspaces/
~/Library/Application Support/0AL/SpecSpace/workspaces.local.yaml
```

The profile creates an empty local catalog on first start. SpecSpace uses these
explicit roots when it converts a UI workspace-creation request into the
report-only Platform initialization plan and request. Route slugs are never
treated as filesystem roots.

SpecGraph artifacts default to the sibling checkout's `runs` directory. Tests
and isolated operator profiles should override it rather than sharing demo or
user artifacts:

```bash
SPECGRAPH_RUNS_DIR=/path/to/private/workspace-runs \
make mac-product-workspace
```

The profile passes the same resolved path to SpecSpace as `--runs-dir`, reports
it from `doctor`, `start`, and `status`, and creates it only after the parent
directory passes the writable preflight. It also passes the selected API port
to the GraphSpace dev server as `SPECSPACE_API_PORT`, allowing isolated test
profiles to use non-default loopback ports when the consumer supports it.

Runtime logs and the mode-`0600` process ownership manifest are stored under:

```text
~/Library/Caches/0AL/SpecSpace/mac-product-workspace/logs
```

Platform starts the backend and UI in dedicated process groups and records their
PIDs plus expected command tokens. `stop` only signals those owned process
groups; it never kills arbitrary listeners by port. A PID or command mismatch
fails closed and requires operator inspection.

The Keychain password is materialized as a mode `0600` temporary file only for
backend startup. The file is removed after SpecSpace becomes ready; the password
is not written to logs or tracked configuration.

## Daily specification-writing flow

1. Run the preflight and start the profile:

   ```bash
   make mac-product-workspace-doctor
   make mac-product-workspace
   ```

2. Open `http://127.0.0.1:5175`. Authenticate as `operator` when the browser
   asks for the single-operator credential.
3. Use the workspace `+` action, enter a display name and initial idea, and save
   the creation request.
4. In Product Workspace, prepare and run controlled initialization. The route is
   usable only after the initialization report is ready for that workspace.
5. Submit the private raw idea and a public-safe summary, request intake
   execution, and run the allowlisted operation.
6. If clarification is required, answer every blocking question, save the
   answers, request continuation, and run controlled continuation.
7. Inspect `Candidate overview`, `Workflow topology`, and `Reviewable
   specifications`. Selecting a materialized specification shows its YAML while
   preserving the canonical node id as evidence.
8. Stop the profile when finished:

   ```bash
   make mac-product-workspace-stop
   ```

The materialized YAML files are reviewable candidate output. This local flow
does not accept the candidate, mutate canonical specifications, write Ontology
packages, create Git commits, or open pull requests.

## Persistence and restart

The state directory, workspace catalog, workspace directories, and scoped
SpecGraph run artifacts are the durable operator data. Runtime PIDs, logs, and
temporary password files are not product data.

| Data | Default location | Durable | Safe to remove |
| --- | --- | --- | --- |
| SpecSpace mutable state | `~/Library/Application Support/0AL/SpecSpace/state` | yes | no |
| Product workspace catalog | `~/Library/Application Support/0AL/SpecSpace/workspaces.local.yaml` | yes | no |
| Product workspace directories | `~/Library/Application Support/0AL/SpecSpace/workspaces/` | yes | no |
| Candidate and specification artifacts | `../SpecGraph/runs/<workspace-id>/` | yes | no |
| Process manifest and logs | `~/Library/Caches/0AL/SpecSpace/mac-product-workspace/` | no | after the profile is stopped |
| E2E-owned profile | `../SpecSpace/graphspace/test-results/mac-product-workspace-restart/` | test evidence only | yes, through the E2E runner |

Normal restart is bounded:

```bash
make mac-product-workspace-stop
make mac-product-workspace
```

Return to the same workspace route. The candidate ref, materialized
specification list, and artifact SHA-256 values must remain unchanged.

## Release-candidate verification

Run the cross-repository browser proof before relying on a new stack:

```bash
make mac-product-workspace-e2e
```

The target uses dedicated ports and isolated SpecSpace state/catalog roots. It
cleans only the exact test workspace `runs/mac-specification-marathon`, runs the
real Platform and SpecGraph handoffs, restarts the profile, and verifies:

- a workspace and raw idea originate in the UI;
- clarification answers are saved through SpecSpace;
- the active candidate is not the Team Decision Log fixture;
- reviewable YAML specifications are materialized;
- the raw idea is absent from public-safe artifacts;
- candidate and specification digests are identical after restart;
- the owned backend/UI process groups and ports are released afterward.

Evidence is written under:

```text
../SpecSpace/graphspace/test-results/mac-product-workspace-restart/
```

The summary artifact is `product-workspace-restart-report.json`; screenshots
show creation, initialization, intake, reviewable specifications, and the
post-restart workspace.

## Recovery and retry policy

Start with read-only diagnosis:

```bash
make mac-product-workspace-status
make mac-product-workspace-doctor
```

Then inspect the backend and UI logs under the runtime directory reported by
`status`. Do not delete SpecSpace state, the workspace catalog, scoped run
artifacts, or `.managed-operation-attempts` evidence to make the UI look ready.

Use this recovery order:

1. If `status` reports a healthy owned profile, refresh the browser before
   executing anything again.
2. If the profile is stopped, run `make mac-product-workspace`; existing durable
   state is reused.
3. If `stop` reports a PID or command-ownership mismatch, inspect the recorded
   process and manifest. Do not kill an arbitrary listener by port and do not
   edit the manifest to bypass the guard.
4. If an operation failed before its request was consumed, correct the reported
   missing input and retry the same guided action.
5. If an operation is `consumed`, `superseded`, `ambiguous`, or
   `recovery_required`, preserve its attempt report. Create a fresh UI
   request/intent only when the operation-specific next action says to do so.
6. Never blindly retry approval, non-dry-run promotion, Git review, or
   publication after a timeout. Inspect durable Platform evidence first.

For a corrupted or accidentally removed durable artifact, stop the profile and
restore the state, catalog, workspace directory, and matching
`runs/<workspace-id>` snapshot as one consistency set. Restoring only one layer
can create a binding or digest mismatch, which is expected to fail closed.

## Troubleshooting

- **Keychain lookup fails:** unlock the login Keychain and verify that service
  `0AL SpecSpace production smoke`, account `operator`, exists. Do not export the
  password into a shell history.
- **Port is already used:** use `status` to determine whether the listener is
  owned by this profile. Stop the owner or select explicit `API_PORT` and
  `UI_PORT`; do not use broad process-kill commands.
- **Workspace route exists but initialization is blocked:** inspect the prepared
  initialization request and binding report. A route slug is not a filesystem
  binding.
- **Candidate is present but marked review required:** inspect readiness and
  repair findings. Artifact presence is not approval readiness.
- **UI cannot find a scoped artifact:** verify that the ref starts with the exact
  `runs/<workspace-id>/` prefix and that the durable workspace binding points to
  the same run directory.
- **E2E cleanup fails:** treat the run as failed even if Playwright passed. The
  runner intentionally refuses symlinked or out-of-scope cleanup paths.

Machine-specific paths can be overridden through `ORG_ROOT`, `PLATFORM_DIR`,
`SPECGRAPH_DIR`, `SPECGRAPH_RUNS_DIR`, `SPECSPACE_DIR`, `DIALOG_DIR`,
`SPECSPACE_STATE_DIR`, `SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR`,
`SPECSPACE_PRODUCT_WORKSPACE_CATALOG`, and
`SPECSPACE_MAC_PRODUCT_RUNTIME_DIR`.
