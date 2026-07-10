# 0AL Platform

Control plane for local 0AL SpecGraph/SpecSpace/SpecPM workspaces and service
orchestration.

## Purpose

`Platform` is the orchestration repository for a local 0AL workspace. It does not
replace the product repositories:

- `SpecGraph` remains the specification graph engine and supervisor runtime.
- `SpecSpace` remains the visual operator interface.
- `SpecPM` remains the specification package manager and private registry lane.
- `Metrics` remains the metric-pack and research/reference source.

`Platform` coordinates how these services are launched together, how product
workspaces are discovered, and how reusable spec packages move through a
review-first import flow.

## Ownership Boundary

`Platform` may orchestrate product workspace creation, track workspace catalog
entries, and pass operator intent to SpecGraph. It must not independently define
or generate the canonical SpecGraph project contract.

SpecGraph owns:

- `specgraph.project.yaml` schema and validation semantics;
- product workspace initialization safety rules;
- the versioned durable product workspace binding contract;
- initialization reports such as `runs/product_workspace_initialization.json`;
- root-intent capture boundaries and no-core-mutation guarantees.

Platform owns:

- workspace catalog records;
- service topology and launch profiles;
- local paths and provider wiring;
- calling a SpecGraph-owned initializer when workspace creation needs canonical
  SpecGraph semantics.

SpecSpace may expose a product workspace creation UI, but route navigation is not
workspace authority. A production creation flow should pass operator intent to a
Platform-owned boundary that records the workspace, validates identifiers and
repository role, calls SpecGraph initialization when needed, and returns a
durable report for SpecSpace to display.

## Local Workspace Shape

The intended local layout is:

```text
0AL/
  Platform/
  SpecGraph/
  SpecSpace/
  SpecPM/
  Metrics/
  <product-workspaces>/
```

`0AL/` is an organization checkout root. It does not need to be a git repository.
`Platform/` is the versioned control plane inside that root.

Set `ORG_ROOT` to the absolute path of that organization checkout root before
using the example configs. For example:

```bash
export ORG_ROOT="$HOME/Development/GitHub/0AL"
```

## Product Workspaces

A product workspace is a folder-document managed by SpecGraph:

```text
MyProduct/
  specgraph.project.yaml
  specs/
  docs/proposals/
  runs/
  .specgraph/
```

The default client-facing profile is `product_workspace`. In that mode SpecGraph
should refine the product graph, but it must not mutate SpecGraph core specs,
core tools, or self-evolution surfaces unless an operator explicitly routes the
concern upstream.

## Operator CLI

List known workspaces from the Platform catalog:

```bash
scripts/platform.py workspace list
scripts/platform.py workspace list --format json --kind product_workspace
scripts/platform.py workspace doctor
scripts/platform.py workspace doctor --format json
scripts/platform.py workspace init \
  --project-id my-product \
  --path "${ORG_ROOT}/MyProduct" \
  --display-name "My Product" \
  --root-intent "describe the product goal"
scripts/platform.py deployment-profile validate \
  --profile deployment-profile.product-idea-to-spec.example.json
scripts/platform.py deployment-profile validate \
  --profile deployment-profile.specgraph-bootstrap-internal.example.json
scripts/platform.py graph-repository validate \
  --contract graph-repository-service.example.json
scripts/platform.py git-service validate-contract \
  --contract git-service-operation-contract.example.json
scripts/platform.py git-service validate-request \
  --request path/to/git-service-request.json
scripts/platform.py git-service validate-response \
  --response path/to/git-service-response.json
scripts/platform.py managed-operation contract
scripts/platform.py managed-operation validate-request \
  --request runs/hosted_managed_operation_request.json
scripts/platform.py git-service execute-promotion \
  --contract git-service-operation-contract.example.json \
  --deployment-profile deployment-profile.product-idea-to-spec.example.json \
  --promotion-request runs/graph_repository_promotion_request.json \
  --approval-decision runs/candidate_approval_decision.json \
  --repository-dir ../SpecGraph \
  --workspace-dir .platform/candidates/my-idea-v1-worktree \
  --materialized-source-dir runs/materialized-candidates
scripts/platform.py graph-repository plan \
  --contract graph-repository-service.example.json \
  --runs-dir ../SpecGraph/runs \
  --output runs/graph_repository_execution_plan.json
scripts/platform.py graph-repository prepare-local \
  --plan runs/graph_repository_execution_plan.json \
  --candidate-id my-idea-v1 \
  --workspace-dir .platform/candidates/my-idea-v1
scripts/platform.py graph-repository promotion-request \
  --plan runs/graph_repository_execution_plan.json \
  --candidate-id my-idea-v1 \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --title "Add candidate spec graph" \
  --body "Review candidate spec graph produced from the idea-to-spec flow." \
  --output runs/graph_repository_promotion_request.json
scripts/platform.py graph-repository prepare-worktree \
  --plan runs/graph_repository_execution_plan.json \
  --repository-dir ../SpecGraph \
  --candidate-id my-idea-v1 \
  --workspace-dir .platform/candidates/my-idea-v1-worktree
scripts/platform.py graph-repository commit-worktree \
  --prepare-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_worktree_prepare_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree \
  --path specs/nodes/SG-SPEC-CANDIDATE.yaml \
  --message "Add candidate spec graph"
scripts/platform.py graph-repository open-review \
  --commit-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_review_commit_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree \
  --base main \
  --title "Add candidate spec graph" \
  --body "Review candidate spec graph produced from the idea-to-spec flow."
scripts/platform.py graph-repository review-status \
  --open-review-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_open_review_report.json \
  --worktree-dir .platform/candidates/my-idea-v1-worktree
scripts/platform.py graph-repository publish-read-model \
  --review-status-report .platform/candidates/my-idea-v1-worktree/.platform/graph_repository_review_status_report.json \
  --bundle-dir ../SpecGraph/dist/specgraph-public \
  --output-dir dist/specgraph-public
scripts/platform.py deploy render --dry-run
scripts/platform.py deploy up
scripts/platform.py deploy status
scripts/platform.py deploy down
scripts/platform.py deploy render --profile production-web
scripts/platform.py deploy bundle --output-dir dist/platform-deploy-bundle
scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --specspace-api-image-ref ghcr.io/0al-spec/specspace-api@sha256:<digest> \
  --specspace-ui-image-ref ghcr.io/0al-spec/specspace-ui@sha256:<digest>
scripts/platform.py deploy timeweb-render \
  --output-dir dist/platform-timeweb-deploy \
  --image-lock dist/platform-service-images.json
```

The CLI reads `PLATFORM_WORKSPACES_CATALOG` when set, then
`workspaces.local.yaml` when present, and otherwise falls back to
`workspaces.example.yaml`.

`workspace doctor` reports warnings and errors for catalog shape, duplicate IDs,
governance profile mismatches, registry references, and local path availability.
Warnings exit with status `0`; errors exit with status `1`; catalog read/parse
failures exit with status `2`.

`workspace init` delegates workspace creation to a SpecGraph-owned initializer
(`tools/supervisor.py --init-product-workspace`) and adds the new entry to
`workspaces.local.yaml` only after SpecGraph returns a successful initialization
report. Set `SPECGRAPH_HOME` to point at the SpecGraph checkout, or place
SpecGraph as a sibling of Platform under `ORG_ROOT`. Pass `--dry-run` to preview
the command and the catalog entry without invoking SpecGraph.

`graph-repository validate` checks the MVP Git-backed Graph Repository Service
contract. The contract fixes the production write boundary for candidate
workspaces, validation gates, branch/commit/review operations, and public-safe
read-model publication without granting SpecSpace direct canonical write
authority.

The local commands are the MVP adapter for that boundary. Production should
expose these operations through a Git Service that owns repository binding,
refs, credentials, isolated workspaces, audit reports, and read-model
publication, rather than treating an arbitrary local checkout as the storage
contract.

`git-service validate-contract` checks the production-facing Git Service
operation contract. It validates the stable request/response envelope, required
operations, idempotency keys, ref ownership, lock scopes, audit fields, and
authority boundary for:

- `prepare_worktree`;
- `commit_candidate`;
- `open_review`;
- `review_status`;
- `publish_read_model`.

`git-service validate-request` and `git-service validate-response` validate the
generic operation envelopes that a future hosted service or queue-backed worker
will exchange. These envelopes are deliberately separate from the local
`graph-repository` adapter commands so SpecSpace and orchestrators do not bind
to local filesystem paths as the product contract. A `prepare_worktree` request
must include `candidate_approval_decision` in `inputs`; envelope validation only
checks the ref shape, while `execute-promotion` validates the decision content.

`deployment-profile validate` checks the deployment authority boundary that
keeps client-facing product work separate from SpecGraph bootstrapping. The
tracked `deployment-profile.product-idea-to-spec.example.json` profile exposes
the product idea-to-spec workbench and permits controlled Git Service promotion
only for `target_repository_role: product_spec_workspace`. The tracked
`deployment-profile.specgraph-bootstrap-internal.example.json` profile exposes
bootstrap/self-evolution surfaces but leaves Git Service writes in
`dry_run_only` mode.

`git-service execute-promotion` consumes a
`platform_graph_repository_promotion_request` and a ready
`candidate_approval_decision`. It validates both artifacts against the Git
Service operation contract and the active deployment profile, then orchestrates
the local adapter sequence: `graph-repository prepare-worktree`,
`graph-repository commit-worktree`, then `graph-repository open-review`. It writes a single
`platform_git_service_promotion_execution_report` for SpecSpace/operator review.
Pass `--open-review-dry-run` to validate the review handoff without pushing a
branch or creating a pull request.

`graph-repository plan` reads the required SpecGraph idea-to-spec run artifacts
and emits a report-only execution plan for the repository service boundary. The
planner verifies that the inputs remain review-only and does not run Git, open
reviews, publish read models, or mutate canonical SpecGraph specs. For
product idea-to-spec promotion, the required inputs include the clarification
answers, product ontology gap decisions, rerun input, rerun preview, and rerun
materialization artifacts; unresolved ontology gaps keep branch preparation
blocked.

`product-repair-rerun plan|execute|publish|smoke` is the Platform adapter
between a SpecSpace repair rerun request and the next SpecGraph repair-chain
artifacts. It validates the SpecSpace-owned request state, SpecGraph import
preview, request gate, repair session journal, and product deployment profile
before it can run the controlled SpecGraph
`product-workspace-requested-repair-draft-rerun` make target. With
`--build-repaired-handoff`, execute/smoke also run the fixed repaired handoff
target and verify repaired candidate approval readiness through a read-only
gate. The adapter may refresh public-safe `runs/*.json` and the static bundle,
but it does not create Git branches or commits, open pull requests, accept
ontology terms, write Ontology packages, materialize approval decisions, or
mutate canonical specs.

`graph-repository prepare-local` validates a ready execution plan and writes a
local candidate workspace manifest/report. It calculates the candidate branch
and planned Git commands, but still does not execute Git, open pull requests, or
promote candidate specs.

`graph-repository promotion-request` creates a report-only handoff artifact for
the future review promotion. It validates the ready plan, candidate id,
materialized candidate paths, and review metadata without executing Git,
creating commits, opening pull requests, or accepting candidate specs.

`graph-repository prepare-worktree` is the first controlled executor step. It
creates a local Git worktree and candidate branch from a ready execution plan,
but still does not commit, open reviews, merge, accept specs, or publish read
models.

`graph-repository commit-worktree` creates a candidate-branch commit from
explicit relative paths. It does not open reviews, merge, accept specs into the
canonical branch, write Ontology packages, or publish read models.

`graph-repository open-review` pushes the candidate branch and opens a pull
request. It still does not merge, accept candidate specs into the canonical
branch, write Ontology packages, or publish read models.

`graph-repository review-status` reads pull request state through `gh pr view`
and writes a local status report. It is read-only with respect to the graph
lifecycle and does not publish read models.

`graph-repository publish-read-model` copies a public-safe bundle after a merged
review status. It requires an artifact manifest and assumes the source bundle
has already passed SpecGraph publish gates.

Install local Python tooling with:

```bash
python3 -m pip install -r requirements-dev.txt
```

For local service launch, copy `.env.example` to `.env`, set `ORG_ROOT`, and use
`scripts/platform.py deploy ...` as the Docker Compose entry point. The command
defaults to `docker-compose.local.yml` when present, otherwise
`docker-compose.example.yml`; it passes `.env` when present.
The example profile uses overrideable image variables so operators can pin
known-good local images without editing tracked Compose files. The web API URL
is derived from `SPECSPACE_API_HOST` and `SPECSPACE_API_PORT`.
Use `--profile production-web` to overlay a static SpecSpace web profile that
builds `viewer/app/dist` and serves the production assets instead of running the
Vite development server.
Use `deploy bundle` to create the portable Compose artifact that CI uploads for
Compose-capable single-node hosts. The bundle includes `.env.example`, not a
machine-local `.env`. It is not the current Timeweb Cloud Apps manifest-only
deploy path.
Use `deploy timeweb-render` to create a Timeweb Cloud Apps manifest-only deploy
tree. That profile requires digest-pinned SpecSpace API/UI image refs and
contains no source files, bind mounts, build sections, or required environment
interpolation.
The Timeweb port contract is intentionally narrow: the public `app` service
uses `8080:80`, while `specspace-api` is internal-only on exposed container port
`8001`. Do not publish API host ports, use Timeweb-reserved `80:80`, or return
to the old `5173:80` binding.
`--image-lock` accepts a JSON `platform_service_image_lock` artifact from a
service-producing CI job. The lock carries digest-pinned image refs for
`specspace_api` and `specspace_ui`, letting Platform render one composite deploy
manifest without storing Timeweb secrets or rebuilding service images.
The Timeweb renderer also enables SpecSpace HTTP-provider Hyperprompt compile
with a `/tmp` scratch workspace and bounded runtime limits; use
`--disable-hyperprompt-http-compile` for a manifest-level rollback.
Use `--product-workspace-artifact-base-url` or
`SPECSPACE_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL` when a product workspace should
read a separate public-safe artifact bundle from the root SpecGraph showcase.
If no product workspace artifact base is provided, Platform derives the Team
Decision Log demo base as
`<SPECSPACE_ARTIFACT_BASE_URL>/workspaces/team-decision-log`. The older
`--team-decision-log-artifact-base-url` flag remains as a compatibility alias
for the first pilot.

Managed SpecSpace operations are opt-in. Production deployments should leave
backend Platform execution disabled unless the deployment profile explicitly
allows it. In that default posture, SpecSpace should expose
`managed_mode_readiness.status = read_only` and keep managed operation actions
inspect/request-only while the Platform wrappers remain available for local or
operator-controlled execution.
Validate that posture with:

```bash
.venv/bin/python scripts/platform.py specspace product-smoke \
  --base-url https://specgraph.space \
  --workspace team-decision-log \
  --artifact-base-url https://specgraph.tech/workspaces/team-decision-log \
  --output runs/specspace_product_workspace_production_smoke_report.json
```

The smoke checks both `/team-decision-log` and
`/team-decision-log?view=demo`, verifies the workspace-specific artifact base,
and requires production managed execution to stay disabled unless the deployment
profile intentionally changes.

The GitHub Actions workflow `Timeweb Publish` is the production Timeweb deploy
publisher. SpecSpace CI produces the service image lock and triggers this
workflow; Platform renders, validates, and publishes the `timeweb-deploy` branch
watched by Timeweb.

## Starter Files

- [PRD.md](PRD.md) defines the MVP product boundary.
- [WORKPLAN.md](WORKPLAN.md) breaks the first implementation into phases.
- [workspaces.example.yaml](workspaces.example.yaml) shows the workspace catalog.
- [schemas/workspace-catalog.schema.json](schemas/workspace-catalog.schema.json)
  defines the workspace catalog validation contract.
- [docs/workspace-catalog.md](docs/workspace-catalog.md) documents workspace
  catalog fields, versioning, and guardrails.
- [requirements-dev.txt](requirements-dev.txt) lists local validation and CLI
  Python dependencies.
- [scripts/platform.py](scripts/platform.py) provides the initial operator CLI.
- [docs/deployment.md](docs/deployment.md) records the single-node deployment
  and cost-control plan.
- [services.example.yaml](services.example.yaml) shows managed service metadata.
- [.env.example](.env.example) defines local Compose environment knobs.
- [docker-compose.example.yml](docker-compose.example.yml) sketches the local dev
  service topology.
- [docker-compose.production-web.example.yml](docker-compose.production-web.example.yml)
  overlays the dev topology with a production static SpecSpace web service.
- [.github/workflows/deploy-bundle.yml](.github/workflows/deploy-bundle.yml)
  validates and uploads the portable deployment bundle and the Timeweb
  manifest-only deploy tree.

Copy example files to local, untracked variants before putting machine-specific
paths or credentials in them.
