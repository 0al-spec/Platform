# Workspace Catalog

The workspace catalog is Platform-owned metadata for discovering local 0AL
workspaces. It is intentionally narrower than SpecGraph's project contract:
Platform tracks identity, local paths, provider wiring, status, and optional
SpecPM registry references, while SpecGraph owns `specgraph.project.yaml`
schema and workspace initialization semantics.

The machine-readable schema is
[`schemas/workspace-catalog.schema.json`](../schemas/workspace-catalog.schema.json).
It uses JSON Schema draft 2020-12:
<https://json-schema.org/draft/2020-12/json-schema-core.html>.

The catalog is written as YAML for operator convenience. YAML parsing should
stay compatible with YAML 1.2:
<https://yaml.org/spec/1.2.2/>.

## Files

- `workspaces.example.yaml` is the tracked portable example.
- `workspaces.local.yaml` is the untracked machine-local catalog.
- `schemas/workspace-catalog.schema.json` is the versioned validation contract.

## Versioning

`schema_version: 1` is the current catalog format. Backward-compatible additions
should be optional fields. Breaking changes must use a new `schema_version` and
a migration note.

Consumers should also verify semantic constraints that JSON Schema cannot fully
express, such as unique `project_id` values, unique `registry_id` values, and
whether a workspace path exists on the local machine. Schema version 1 treats
absolute paths as POSIX-style paths.

## Top-Level Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Catalog format version. Current value: `1`. |
| `artifact_kind` | yes | Must be `platform_workspace_catalog`. |
| `organization_root` | yes | Absolute local `0AL/` checkout root, or `${ORG_ROOT}` in examples. |
| `workspaces` | yes | Known core repositories and product workspaces. |
| `registries` | no | Known SpecPM private registries available to workspaces. |

## Workspace Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `project_id` | yes | Stable Platform-local identifier. |
| `display_name` | yes | Operator-facing name. |
| `kind` | yes | `core_repository` or `product_workspace`. |
| `status` | yes | `active`, `inactive`, or `archived`. |
| `path` | yes | Absolute local path, or `${ORG_ROOT}/...` in examples. |
| `governance_profile` | yes | `self_hosted_bootstrap` for core, `product_workspace` for products. |
| `specgraph_config` | yes | Relative path to the SpecGraph project config. |
| `provider` | yes | Local provider settings. Currently only `local_filesystem`. |
| `registry` | no | Review-first SpecPM registry reference for product imports. |

## Provider Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `type` | yes | Must be `local_filesystem` in schema version 1. |
| `specs_root` | yes | Workspace-relative specs directory. |
| `runs_root` | yes | Workspace-relative runs directory. |
| `proposals_root` | no | Workspace-relative proposal directory, normally `docs/proposals`. |

## Registry Fields

Workspace registry references use:

| Field | Required | Meaning |
| --- | --- | --- |
| `registry_id` | yes | Identifier matching one entry in top-level `registries`. |
| `import_policy` | yes | Must be `review_first`. |

Top-level registry definitions use:

| Field | Required | Meaning |
| --- | --- | --- |
| `registry_id` | yes | Stable Platform-local registry identifier. |
| `kind` | yes | Must be `specpm_private_registry`. |
| `base_url` | yes | Local or private registry URL. |
| `authority` | yes | Current value: `dev_observation_only`. |
| `import_policy` | yes | Must be `review_first`. |

## Guardrails

- Keep tracked examples portable; do not commit machine-specific absolute paths.
- Keep secrets, credentials, private keys, and tokens out of catalog files.
- Use `product_workspace` for external/client-facing product workspaces.
- Keep SpecPM imports `review_first`; the catalog must not imply automatic
  materialization into canonical specs.
- Do not duplicate SpecGraph-owned initialization semantics in Platform.

## Validation

The first validation layer is structural schema validation. The next layer,
implemented by `platform workspace doctor`, should check local realities:

- referenced paths exist;
- `project_id` and `registry_id` values are unique;
- product workspaces use `governance_profile: product_workspace`;
- registry references point to known `registries` entries;
- missing paths are reported as diagnostics rather than crashes.
