# Durable Product Workspace Binding

## Purpose

A successful product workspace initialization execution report owns one
versioned `workspace_binding`. Later managed operations use that binding rather
than deriving state, run, artifact, or repository paths from a route slug.

The binding joins:

```text
workspace identity
→ SpecSpace state namespace
→ SpecGraph run directory
→ product artifact bundle
→ repository/worktree identity
```

## Ownership

- SpecGraph owns valid product-workspace identity, relative layout semantics,
  `specgraph.project.yaml`, and initialization evidence.
- Platform owns the external binding across execution roots, artifact routing,
  catalog identity, and repository resolution.
- SpecSpace discovers the Platform binding, renders a public-safe projection,
  and resolves local product runs only from a trusted binding.
- The browser does not author or mutate bindings.

## Contract

`platform_product_workspace_initialization_execution_report.workspace_binding`
uses:

```text
artifact_kind = platform_product_workspace_binding
contract_ref = platform.product-workspace.binding.v1
schema_version = 1
status = ready
```

The contract contains typed `identity`, `routing`, `execution`,
`repository`, and `provenance` sections. `binding_revision_sha256` covers
logical identity and routing fields. Provenance pins the initialization plan and
SpecGraph initialization report by SHA-256.

Artifact routing URLs, when present, must use HTTP(S). The manifest URL is a
derived field and must equal `<product_artifact_base_url>/artifact_manifest.json`.
This prevents a valid logical revision from being reused with a substituted
manifest endpoint.

Absolute workspace paths belong only to the local execution section. SpecSpace
must expose booleans describing local resolution, not the paths themselves.

## Compatibility

An older published workspace without the v1 binding remains readable as
`legacy_read_only`. Backend-managed execution requires a ready trusted
binding. Explicit run-directory overrides are debug surfaces and must match the
bound run directory.

Repair rerun plans/reports, candidate approval gates/decisions, promotion
requests/execution reports, review-status reports, and read-model publication
reports carry a compact digest-pinned binding context. A consumer must compare
that context with the selected initialization report before executing a managed
operation.

## Verification

The execution-backed SpecSpace product demo uses real Platform wrappers to run:

```text
SpecSpace creation request
→ Platform initialization plan
→ initialization execution request
→ SpecGraph workspace initialization
→ ready durable binding
→ UI-started intake and continuation
→ workspace-scoped candidate artifacts
```

The smoke reloads the browser after initialization, checks the public-safe
binding projection, rejects shared/default run fallback, and scans generated
public-safe idea artifacts for raw input leakage.

## Failure Modes

Managed execution fails closed for:

- workspace, route, repository-role, or state-namespace mismatch;
- invalid run-directory refs;
- binding revision mismatch;
- missing or malformed initialization evidence digests;
- unknown or truthy `may_*` authority fields;
- stale, foreign, blocked, or dry-run initialization reports.

## Non-Goals

The binding does not create worktrees, branches, commits, pull requests, or read
models. It does not mutate canonical specs, write Ontology packages, accept
Ontology terms, or publish raw idea content.
