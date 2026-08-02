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
```

The UI opens at `http://127.0.0.1:5175`. The default persistent operator state
is stored outside the checkout at:

```text
~/Library/Application Support/0AL/SpecSpace/state
```

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

Machine-specific paths can be overridden through `ORG_ROOT`, `PLATFORM_DIR`,
`SPECGRAPH_DIR`, `SPECGRAPH_RUNS_DIR`, `SPECSPACE_DIR`, `DIALOG_DIR`,
`SPECSPACE_STATE_DIR`, and `SPECSPACE_MAC_PRODUCT_RUNTIME_DIR`.
