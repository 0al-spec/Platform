# Deployment Plan

## Decision

Platform should make the default deployment target a single-node bundle: many
0AL services, one operator-managed host.

The cost target for the solo-operator profile is one small VPS, not one VPS per
service. Service count must not map directly to monthly hosting cost.

## Default Profile: Single Node

The default deploy shape is:

```text
one VPS
  reverse proxy
    specspace web
    specspace api
    specpm registry or index
    optional specgraph api or worker
```

Platform should expose this as one deployment surface:

```bash
scripts/platform.py deploy render
scripts/platform.py deploy up
scripts/platform.py deploy status
scripts/platform.py deploy down
```

Docker Compose is the first implementation target for this profile. The
operator should not manually assemble service ports, routes, image tags, and
volumes from memory.

## Public Workspace Routing

The first product-facing deployment should keep a single public SpecSpace site
while routing users to distinct workspaces:

```text
specgraph.space/
  -> SpecGraph bootstrap/showcase workspace

specgraph.space/team-decision-log
  -> Team Decision Log product_idea_to_spec pilot workspace
```

This is still one SpecSpace deployment, not a separate Team Decision Log
application. The root route demonstrates SpecGraph and its bootstrap
capabilities; the Team Decision Log route demonstrates a user product moving
from idea to candidate specification graph.

The route layer should resolve a workspace registry/catalog entry and an
artifact manifest for the active workspace. Product routes must use deployment
profiles that hide bootstrap/self-evolution surfaces and allow Git Service
promotion only to `product_spec_workspace` repository roles. The
`/team_decision_log` spelling may be supported as an alias, but
`/team-decision-log` is the canonical route.

The Timeweb deployment can keep the root SpecGraph showcase on the default
artifact base URL while pointing the active product workspace at a separate
public-safe artifact bundle:

```text
SPECSPACE_ARTIFACT_BASE_URL=https://specgraph.tech
SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL=team-decision-log=https://specgraph.tech/workspaces/team-decision-log
```

If `SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL` is omitted, Platform renders
the tracked Team Decision Log and Hosted Operation Canary routes with derived
product artifact bases:

```text
https://specgraph.tech/workspaces/team-decision-log
https://specgraph.tech/workspaces/hosted-operation-canary
```

The root SpecGraph showcase continues to use `SPECSPACE_ARTIFACT_BASE_URL`.
The product route consumes its artifact base through a product workspace
provider and reads product `runs/*.json` surfaces such as
`runs/candidate_spec_graph.json`. This keeps bootstrap/self-evolution artifacts
from becoming the default data source for `/team-decision-log`.

Production SpecSpace deployments should remain read-only unless a deployment
profile explicitly opts into backend-managed Platform execution. Do not set
`--enable-platform-execution` or its environment equivalent for the public
Timeweb route by default. The Product Workspace API exposes
`managed_mode_readiness`; production smoke should report `status: read_only`
and `platform_execution_disabled` while still showing the managed operations
registry as inspect-only telemetry.

Use the Platform smoke wrapper to validate the public product route end to end:

```bash
.venv/bin/python scripts/platform.py specspace product-smoke \
  --base-url https://specgraph.space \
  --workspace team-decision-log \
  --artifact-base-url https://specgraph.tech/workspaces/team-decision-log \
  --expect-managed-mode read_only \
  --output runs/specspace_product_workspace_production_smoke_report.json \
  --format json
```

The smoke is report-only. It checks `/api/v1/health`, the product workspace API,
the operator route shell, the presentation route shell at `?view=demo`,
workspace-specific artifact routing, managed-mode readiness, and write-authority
flags. It does not execute Platform, SpecGraph, Git Service, or read-model
publication operations. The wrapper retries transient
restart-window transport failures and HTTP `502` / `503` / `504` responses with
a bounded attempt count; persistent failures remain blocking and are recorded in
the durable smoke report.

### Hosted managed-operation canary

The hosted queue profile has a separate canary command for validating the
authenticated Platform service and worker. It consumes an already validated
queue request; it does not build an arbitrary request from CLI arguments and it
cannot run irreversible operations.

Start with the read-only review-status operation:

```bash
.venv/bin/python scripts/platform.py managed-operation canary \
  --service-url http://127.0.0.1:8091 \
  --auth-token-file /run/secrets/managed_operation_token \
  --request runs/hosted_canary_review_status_request.json \
  --artifact-root ../SpecGraph \
  --output runs/platform_hosted_managed_operation_canary_report.json \
  --format json
```

The canary checks service health, request-contract validity, operation
allowlisting, authenticated enqueue, queue terminal state, and the complete
set of digest-pinned authoritative output reports. When `--artifact-root` is
provided, it also verifies the output bytes against the receipt digests inside
the workspace-scoped `runs/<workspace-id>` directory.

The report is transport evidence, not lifecycle completion and not a promotion
gate. Queue `succeeded` is accepted only together with the expected Platform
output reports. Read-only review-status is enabled by default; the registered
promotion dry-run can be tested only with explicit `--allow-dry-run`. Git
review, read-model publication, consume-on-attempt operations, and automatic
retry of ambiguous outcomes remain outside the canary profile.

The report is public-safe: it contains opaque request/workspace identifiers,
logical artifact refs, and digests, but never bearer tokens, token paths, local
checkout paths, raw idea text, or the full request envelope.

For a dedicated VM or an N100-class staging node, use the standalone
`docker-compose.hosted-managed-runtime.example.yml` profile documented in
[`hosted-managed-operations.md`](hosted-managed-operations.md). It packages
PostgreSQL, the authenticated service, and a worker into one host and one
monthly infrastructure unit. The development runtime supports both `amd64` and `arm64`
through the Debian Python base image; build it on the target architecture or
publish a multi-architecture image.

Review-status canaries must use portable GitHub PR evidence from the product
promotion execution report. A deployed worker must not depend on a candidate
worktree path or `.platform/graph_repository_open_review_report.json` that only
exists on the developer workstation.

Before enabling operations with non-replayable side effects, run recovery in
strict mode against the hosted queue:

```bash
.venv/bin/python scripts/platform.py managed-operation recover \
  --queue-adapter postgresql \
  --database-url-file /run/secrets/managed_operation_database_url \
  --max-attempts 3 \
  --strict
```

Strict recovery succeeds only when expired replay-safe leases are requeued and
ambiguous consume-on-attempt or irreversible leases are quarantined. It fails
if a receipt contradicts the operation registry, so a deployment cannot hide a
replay-policy drift behind a green recovery command.

### TLS-fronted production profile

The standalone VM profile proves the container boundary but publishes only on
host loopback. Use `docker-compose.hosted-managed-production.example.yml` for a
remote production SpecSpace connection. This separate profile adds a
digest-pinned Caddy ingress and keeps PostgreSQL and the Platform HTTP service
on an internal Docker network. Only the worker receives an egress network for
read-only GitHub review inspection. The Platform service has no direct host
port.

Production rollout and sign-off are documented in
[`hosted-managed-operations.md`](hosted-managed-operations.md#production-rollout-and-sign-off).
For reproducible initial VPS provisioning, use the versioned
[`cloud-init.production.example.yaml`](../deploy/hosted-managed/cloud-init.production.example.yaml)
from that runbook. It is host bootstrap only: it contains no deployment images,
repository checkout, SSH key, or runtime secret.
Issue and renew the dedicated HTTPS certificate with the tracked
`deploy/hosted-managed/hosted-managed-tls.sh` helper described in the same
runbook. The helper pins issuance to the expected IPv4 and synchronizes only
the configured certificate lineage into the runtime secret files.
The production profile starts with its worker stopped. Versioned bounded
policies permit either one exact `review_status_execute` request through
`bounded-worker` or, after a separate rollout decision, one exact
`promotion_execute_dry_run` request through `promotion-dry-run-window`. The
dry-run profile requires two digest-pinned Platform reports and proves that no
Git mutation occurred. The former long-running worker is isolated behind
`continuous-worker`, is limited to the review-status profile, and requires a
separate rollout decision. Detailed operator commands and evidence semantics are in
[`hosted-managed-operations.md`](hosted-managed-operations.md#bounded-worker-operating-policy).

The production contract is checked in CI with:

```bash
make hosted-managed-production-contract
```

It fails when images are mutable, the allowlist is absent, the Platform service
publishes a direct port, TLS ingress is missing, maintenance or worker tooling
is enabled by default, the bounded policy expands beyond read-only scope, or
service/worker network authority expands.

Production images are published separately by the manual
`publish-hosted-managed-images.yml` workflow. Consume only refs from its
validated `platform_hosted_managed_image_lock`; workflow commit tags are build
discovery aids and are not deployment inputs. The same lock also pins the
third-party PostgreSQL runtime image used by the production Compose profile.
Render the non-secret production environment from that lock with
`scripts/render_hosted_managed_production_env.py`; this avoids manually
transcribing image digests. Its default profile keeps the allowlist fixed to the
read-only canary operation; an explicit tracked operation profile is required
for a bounded dry-run transition. The `bounded-product-dry-run` profile exposes
both reviewed operations to the service while keeping the worker stopped and
requiring an operation-specific one-request window.

## Local Compose Entry Point

The working plan for this phase is maintained in
[`local-service-launch-plan.md`](local-service-launch-plan.md).

The initial implementation wraps Docker Compose directly:

- `deploy render` runs `docker compose config`;
- `deploy up` runs `docker compose up -d`;
- `deploy status` runs `docker compose ps`;
- `deploy down` runs `docker compose down`.

Use `--profile production-web` to add
`docker-compose.production-web.example.yml` on top of the default Compose file.
That profile builds SpecSpace static assets and serves `viewer/app/dist` through
a Node static file server instead of running the Vite development server.
If another local process already owns the default web port, set
`SPECSPACE_WEB_PORT` in `.env` or the shell and rerun `deploy up`.

Use `--profile hosted-managed` to add both the production web overlay and
`docker-compose.hosted-managed.example.yml`. This profile requires
`PLATFORM_MANAGED_OPERATION_TOKEN` and
`PLATFORM_MANAGED_OPERATION_DB_PASSWORD`; it runs PostgreSQL, the private
Platform enqueue/status service, a long-running worker, and SpecSpace in hosted
managed mode. Queue status remains transport telemetry and does not replace
validated Platform output reports.

For a production canary, set
`PLATFORM_MANAGED_OPERATION_ALLOWLIST=review_status_execute`. The same
allowlist is passed to the HTTP service and worker, and the service health
report exposes only the enabled operation ids. Add
`promotion_execute_dry_run` only for an explicit dry-run rollout; do not enable
Git review, publication, or consume-on-attempt operations during canary.
After the independent dry-run sign-off, the tracked
`bounded-product-dry-run` profile may advertise both reviewed operations. It
does not start a worker: each bounded window narrows the worker container to
one operation and one exact request.

The `hosted-managed-contract` CI job provides the fast pre-deployment layer. It
runs the canary against the real HTTP handler with an in-process SQLite queue
and worker, checks service and queue safety contracts, and renders the hosted
Compose profile twice. Rendering without
`PLATFORM_MANAGED_OPERATION_ALLOWLIST` must fail; rendering with the read-only
canary operation must pass the same allowlist to both the service and worker.
This job does not replace a deployed canary or the PostgreSQL integration job.

The separate `hosted-managed-postgres` CI job runs against a PostgreSQL 16
service container. In addition to queue lifecycle, concurrent enqueue, workspace
lock, and recovery tests, it exercises the canary through the real authenticated
HTTP handler and a PostgreSQL-backed worker. It remains bounded to the read-only
`review_status_execute` operation and uses fixture-owned artifacts; it does not
contact a deployment or perform Git operations.

The `hosted-managed-compose-smoke` job covers the container boundary that the
in-process jobs intentionally omit. It starts only PostgreSQL, the authenticated
service, and the worker from the tracked Compose profile, then verifies the
PostgreSQL service health contract and a fresh worker heartbeat. The smoke uses
temporary fixture-owned secrets and a read-only allowlist, enqueues no managed
request, and always removes its containers and volumes.

The command resolves Compose inputs in this order:

- compose file: `PLATFORM_COMPOSE_FILE`, then `docker-compose.local.yml`, then
  `docker-compose.example.yml`;
- env file: `PLATFORM_ENV_FILE`, then `.env` when present;
- project name: `--project-name`, then `COMPOSE_PROJECT_NAME`, then
  `0al-platform`.

Copy `.env.example` to `.env` and set `ORG_ROOT` to the local `0AL/` checkout
root before running the profile.

The example profile keeps images overrideable through `.env`:

- `SPECPM_IMAGE`;
- `SPECSPACE_API_IMAGE`;
- `SPECSPACE_WEB_IMAGE`.

The default SpecPM public index container installs `git` at startup because the
reviewed public-index manifest can include remote package sources. This keeps
the first Compose profile runnable without introducing owned Platform images
yet; a later production profile should move dependency installation into built
images.

The SpecPM service publishes registry metadata under `/v0/`. Its root `/`
serves a small browser-friendly index that links to `/v0/` and
`/v0/status/index.json`.

SpecSpace API also receives a writable `specspace-dialogs` volume mounted at
`SPECSPACE_DIALOG_DIR` because `viewer/server.py` still requires a dialog store.
That dialog store is runtime state, not a Platform catalog or SpecGraph project
contract.

## CI Ownership

Timeweb Cloud Apps deployment is Platform-owned. Platform defines the
Timeweb-compatible manifest-only deploy tree and publishes the deploy branch
watched by Timeweb. SpecSpace remains the producer of the API/UI images and the
deployment health signal.

Platform CI publishes a `platform-deploy-bundle` artifact for the
`production-web` profile. The bundle targets Compose-capable single-node hosts
that can mount an `ORG_ROOT` checkout. It contains:

- `docker-compose.example.yml`;
- `docker-compose.production-web.example.yml`;
- `.env.example`;
- `platform-deploy-bundle.json`;
- bundle-local operator notes.

The bundle deliberately ships `.env.example`, not `.env`. Machine-local values
such as `ORG_ROOT`, public ports, and image pins remain outside git and outside
the Platform artifact.

The Timeweb Cloud Apps path is manifest-only, uses digest-pinned images, and
avoids bind mounts and required environment interpolation. Do not switch that
path to the single-node Platform bundle directly. Use the Platform Timeweb
manifest profile instead.

## Timeweb Manifest Profile

Platform can render and validate the Timeweb Cloud Apps deploy tree:

```bash
scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --specspace-api-image-ref ghcr.io/0al-spec/specspace-api@sha256:<digest> \
  --specspace-ui-image-ref ghcr.io/0al-spec/specspace-ui@sha256:<digest>

scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --image-lock dist/platform-service-images.json

scripts/platform.py deploy timeweb-validate \
  --path dist/platform-timeweb-deploy
```

Every generated Timeweb profile enables SpecSpace's bounded single-operator
HTTP Basic authentication boundary. Before deploying the generated tree, add
one independent global secret to the Timeweb application:

```text
SPECSPACE_OPERATOR_AUTH_PASSWORD
```

Generate a random value of at least 32 characters and keep it separate from the
Platform managed-operation token and both PostgreSQL passwords. The generated
Compose declares the variable without a value; Timeweb injects the secret at
runtime. Neither the renderer nor GitHub receives the value. The non-secret
defaults are:

```text
SPECSPACE_OPERATOR_AUTH_USERNAME=operator
SPECSPACE_OPERATOR_AUTH_ALLOWED_ORIGIN=https://specgraph.space
```

Open `https://specgraph.space/api/v1/operator-session` once to establish the
browser's native Basic Auth session. Public-safe artifact and Product Workspace
projections remain anonymous; raw SpecSpace state and every mutation or managed
operation require the operator credentials.

`--image-lock` is the preferred handoff from service-producing CI to Platform.
It keeps the composite deploy renderer independent from how service images are
built:

```json
{
  "artifact_kind": "platform_service_image_lock",
  "schema_version": 1,
  "services": {
    "specspace_api": {
      "image_ref": "ghcr.io/0al-spec/specspace-api@sha256:<digest>"
    },
    "specspace_ui": {
      "image_ref": "ghcr.io/0al-spec/specspace-ui@sha256:<digest>"
    }
  }
}
```

Explicit `--specspace-api-image-ref` and `--specspace-ui-image-ref` values, or
their environment variables, override image lock values. This keeps local
operator checks possible while preserving one Platform-owned renderer for the
production Timeweb tree.

The Timeweb renderer enables SpecSpace HTTP-provider Hyperprompt compile by
default. The rendered API service keeps SpecGraph artifacts read-only and passes
a scratch workspace plus bounded runtime limits to SpecSpace:

```text
SPECSPACE_HYPERPROMPT_HTTP_COMPILE_ENABLED=true
SPECSPACE_HYPERPROMPT_WORK_DIR=/tmp
SPECSPACE_HYPERPROMPT_COMPILE_TIMEOUT_SECONDS=60
SPECSPACE_HYPERPROMPT_MAX_INPUT_BYTES=1048576
SPECSPACE_HYPERPROMPT_MAX_OUTPUT_BYTES=2097152
SPECSPACE_HYPERPROMPT_BUNDLE_RETENTION_COUNT=20
```

Use `--disable-hyperprompt-http-compile` for an emergency rollback without
changing service images. The same values can be overridden through the matching
`SPECSPACE_HYPERPROMPT_*` environment variables or the `deploy timeweb-render`
flags.

The rendered tree contains only:

- `docker-compose.yml`;
- `README.md`;
- `platform-timeweb-deploy.json`.

For the one-operation production canary, render the Timeweb-compatible bounded
profile:

```bash
scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --image-lock dist/platform-service-images.json \
  --enable-hosted-managed-bounded-canary
```

This profile is intentionally narrower than the ordinary durable hosted
profile. It has no Compose `volumes` or `secrets`, requires
`SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN` as an App-bound Timeweb runtime
variable through a value-less Compose environment key, stores SpecSpace request
state under `/tmp`, and enables only
`review_status_execute`. A container restart loses the SpecSpace-side compact
receipt state; the Platform PostgreSQL queue and authoritative reports remain
the recovery source. Roll back by rendering again with
`--disable-hosted-managed-execution`.

The default remains read-only. After a separate rollout decision, render the
hosted SpecSpace client with:

```bash
scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --image-lock dist/platform-service-images.json \
  --enable-hosted-managed-execution \
  --hosted-managed-executor-url https://managed.specgraph.tech
```

This profile adds one named volume for SpecSpace-owned queue/request state and
one Compose secret sourced from the deployment environment variable
`SPECSPACE_HOSTED_MANAGED_EXECUTOR_TOKEN`. The secret value is never rendered
into Git, the image, or `platform-timeweb-deploy.json`. It does not add a local
SpecGraph `runs` mirror: hosted Platform remains responsible for resolving and
validating workspace-scoped artifacts. A published HTTP-provider binding is
accepted only after SpecSpace validates its workspace identity, digests,
routing, repository identity, and closed authority boundary.

Guardrails:

- the first service is `app`, because Timeweb proxies the public domain to the
  first service;
- the `app` service publishes exactly one Timeweb-safe binding, `8080:80`.
  Do not use `80:80` because Timeweb reserves host port 80 for its internal
  proxy, and do not use the old `5173:80` binding because existing deployments
  can keep that host port allocated during a replacement deploy;
- the `specspace-api` service is internal-only: it listens on container port
  `8001` and declares `expose: ["8001"]`, but it must not publish a host port.
  The public UI reaches it through the Compose network as `specspace-api:8001`;
- API/UI image refs must be digest-pinned and must not use `latest`;
- no source `build` sections;
- no bind mounts; named volumes and Compose secrets are forbidden in the
  Timeweb read-only, bounded-canary, and external-state profiles;
- every Timeweb profile must enable the single-operator boundary and declare
  `SPECSPACE_OPERATOR_AUTH_PASSWORD` as a value-less runtime environment key;
  mutable external state or managed execution must fail startup when this
  boundary is disabled;
- Timeweb runtime secrets must be attached to the application in the control
  panel and declared only as value-less environment keys in Compose. They must
  not appear as `${VAR}` interpolation or assigned values. Timeweb resolves
  Compose before injecting App runtime variables, so interpolation replaces an
  otherwise valid secret with an empty string; omitting the key entirely does
  not pass it into a secondary Compose service;
- no required `${VAR:?message}` interpolation;
- SpecSpace API must read SpecGraph artifacts through `--artifact-base-url`;
- SpecSpace API must read SpecPM metadata through `--specpm-registry-url`;
- SpecSpace API must carry the expected Hyperprompt HTTP compile flag and
  limits.
- the Timeweb external-state profile must use HTTPS executor and state-service
  URLs, global environment references for two independent bearer tokens,
  persistent external state, and an ephemeral local cache. Its default client
  allowlist remains exactly `review_status_execute`; the explicit
  `--enable-hosted-managed-promotion-dry-run` flag expands it only to
  `promotion_execute_dry_run,review_status_execute`. Local subprocess execution
  remains disabled.

### Timeweb Storage Contract

The production read-only profile is stateless at the SpecSpace application
boundary. A growing Timeweb disk does not by itself mean that product workspace
state is stored in the application container: Timeweb may retain old Docker
images, layers, containers, deployment cache, or logs outside the active
Compose filesystem.

| Data | Production location | Survives an App redeploy | Contract |
| --- | --- | --- | --- |
| Product and candidate artifacts | `specgraph.tech/workspaces/<workspace-id>` | Yes, outside Timeweb App | Read-only SpecGraph public artifacts and digests |
| Canonical specs and history | SpecGraph Git repository | Yes, outside Timeweb App | Git review and publication lifecycle |
| Platform queue and authoritative reports | Hosted Platform PostgreSQL and VPS artifact root | Yes, outside Timeweb App | Platform remains lifecycle authority |
| SpecSpace HTTP/provider cache | Process memory | No | Rebuilt from remote artifacts |
| Hyperprompt compile scratch | Container `/tmp`, retention bounded to 20 bundles | No | Disposable scratch only |
| Legacy dialog directory | Container `/data/dialogs`, no volume in read-only profile | No | Must not be treated as durable product state |
| SpecSpace mutable drafts, requests, and intents | External SpecSpace state PostgreSQL on the hosted Platform VPS | Yes, outside Timeweb App | Workspace-scoped CAS records; container `/tmp` is cache only |

The generated `platform-timeweb-deploy.json` records one explicit state
profile. `read_only_no_mutable_state` rejects hosted execution and all mutable
state configuration. `ephemeral_canary` permits only the bounded legacy canary.
`external_postgresql` enables persistent hosted mode without a Timeweb volume:
the app keeps an expendable cache under `/tmp`, while the authenticated external
state service owns durable records. The ordinary `persistent_local_volume`
profile remains incompatible with Timeweb Cloud Apps because that platform
rejects its required Compose volume and secret mounts.

### Timeweb Disk Observation And Cleanup Policy

Track the next five production deployments in
[the bounded disk observation log](timeweb-disk-observation-log.md). Review the
trend after deployment three. Escalate earlier if disk usage reaches 80 percent.

The historical symptom is consistent with platform-retained Docker data:
Timeweb support removed old container data on 2026-07-03 and recovered more than
9 GB without restoring application-owned workspace state. If the new
observation again shows monotonic unexplained growth, ask Timeweb support to:

1. report which images, layers, containers, deployment cache, or logs consume
   the application disk;
2. remove unused deployment data while preserving the active application,
   domain, and global environment variables;
3. state whether an automatic image/container retention or prune policy can be
   enabled.

Do not use `docker system prune` instructions for this Cloud Apps deployment
unless Timeweb explicitly provides supported host access. The App is deployed
from digest-pinned prebuilt images and has no `build:` section, so image
production is already outside the Timeweb host; provider-side retention remains
the likely source of repeated deploy growth.

## Timeweb Production Control Plane

The production control plane is split by ownership boundary:

- SpecSpace CI builds and publishes the API/UI images.
- SpecSpace CI writes `platform_service_image_lock`.
- SpecSpace CI triggers Platform's `Timeweb Publish` workflow.
- Platform CI renders and validates the manifest-only deploy tree.
- Platform CI publishes the generated tree to `0al-spec/Platform:timeweb-deploy`.
- Timeweb Cloud Apps deploys from `0al-spec/Platform:timeweb-deploy`.

The first deployment after introducing operator access control must use this
order:

1. Keep the generated Timeweb profile read-only.
2. Add `SPECSPACE_OPERATOR_AUTH_PASSWORD` as a global Timeweb App secret.
3. Deploy the auth-enabled API/UI image pair.
4. Run `specspace product-smoke`; anonymous private-state GET and managed POST
   must both return `401`.
5. Open `/api/v1/operator-session`, authenticate, and verify the operator can
   read the intended private workspace state.
6. Only then restore the external-state profile and the bounded managed
   operation allowlist.

If step 4 or 5 fails, return to the read-only profile. Do not expose mutable
state as a workaround.

Platform exposes the publisher as a GitHub Actions workflow:

- workflow: `Timeweb Publish`;
- input: `service_image_lock_json`, containing a
  `platform_service_image_lock` JSON object;
- input: `artifact_base_url`, the root SpecGraph showcase artifact base URL;
- input: `product_workspace_artifact_base_url`, optional product workspace
  artifact base URL, falling back to `artifact_base_url` when empty;
- input: `publish_deploy_branch`, default `false`;
- output artifact: `platform-timeweb-deploy`;
- branch publish: enabled when `publish_deploy_branch=true`.

SpecSpace should call the workflow with `publish_deploy_branch=true` for the
production path. Manual operator checks can use `publish_deploy_branch=false` to
verify rendering, validation, and the uploaded deploy artifact without changing
the branch watched by Timeweb.

Rollback is Platform-side: republish the last known-good image lock, or reset
`timeweb-deploy` to a known-good generated deploy commit and redeploy Timeweb.
Keep the same image digests in the rollback deploy unless the image itself is
the failure source.

## Service Boundaries

The single-node profile keeps separate service processes and containers even
when they run on one host:

- `SpecGraph` owns graph runtime and product workspace initialization semantics.
- `SpecSpace` owns the visual operator UI and API.
- `SpecPM` owns package registry or static index behavior.
- `Platform` owns service topology, local wiring, deployment profile selection,
  and operator commands.

This keeps runtime ownership clear while preserving a low-cost deployment path.

## Static Hosting

Static public sites, such as a documentation or landing page for
`specgraph.tech`, should not require a dedicated dynamic host. They can be
served from the same VPS, GitHub Pages, Cloudflare Pages, or another static
hosting surface depending on repository visibility and operational preference.

The Platform deployment target should therefore distinguish:

- static public web assets;
- dynamic API services;
- private or local operator surfaces;
- registry/index assets.

## Product vs Bootstrap Profiles

Platform separates the client-facing product workbench from SpecGraph
self-evolution through tracked deployment profile contracts:

- `deployment-profile.product-idea-to-spec.example.json` exposes the
  idea-to-spec workspace, ontology workspace, pre-SIB metrics, and controlled
  promotion review after an approved `candidate_approval_decision` and a ready
  `idea_to_spec_repair_session` journal. Its Git Service mode is
  `controlled_promotion`,
  but only for
  `workflow_lane: product_idea_to_spec` and
  `target_repository_role: product_spec_workspace`.
- `deployment-profile.specgraph-bootstrap-internal.example.json` exposes
  bootstrap, supervisor self-evolution, proposal runtime, and local operator
  diagnostics. Its Git Service mode is `dry_run_only`, so it cannot create
  review commits or pull requests through `git-service execute-promotion`.

Validate either profile before wiring it into a deployment:

```bash
scripts/platform.py deployment-profile validate \
  --profile deployment-profile.product-idea-to-spec.example.json
scripts/platform.py deployment-profile validate \
  --profile deployment-profile.specgraph-bootstrap-internal.example.json
```

This keeps the product deployment from indexing or executing bootstrap flows,
while still preserving the internal bootstrap profile for maintainers.

## Production Notes

Do not run the SpecSpace web frontend in production through a Vite development
server. The production profile should build static assets and serve them through
the reverse proxy or a small static server.

Preferred production shape:

```text
SpecSpace web: static build
SpecSpace API: lightweight API service
SpecPM: static index or small registry service
SpecGraph: API/worker only when public runtime access is needed
```

## Non-Goals

- Do not require one host per service.
- Do not make an all-in-one image the canonical production path.
- Do not hide service ownership by merging all components into one long-running
  process.
- Do not require Kubernetes for the solo-operator profile.

## Optional Demo Profile

An all-in-one image can be useful for demos, tutorials, and throwaway local
experiments:

```text
0al/platform-all-in-one:dev
```

That image should be treated as a convenience profile, not the primary
deployment contract.

## Success Criteria

- A solo operator can run the public 0AL surface on one low-cost VPS.
- Platform can start, stop, and report status for the full service set with one
  command surface.
- Service logs and health checks remain distinguishable per component.
- Static assets do not force an additional paid dynamic host.
- The deployment profile can later evolve from Compose to another orchestrator
  without changing component ownership boundaries.
