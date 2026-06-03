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

Timeweb Cloud Apps deployment is moving toward Platform ownership. Platform now
defines a Timeweb-compatible manifest-only deploy tree, while SpecSpace remains
the producer of the API/UI images and deployment health signal.

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

The current SpecSpace Timeweb Cloud Apps path is also manifest-only, uses
digest-pinned images, and avoids bind mounts and required environment
interpolation. Do not switch that path to the single-node Platform bundle
directly. Use the Platform Timeweb manifest profile instead.

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
their environment variables, override image lock values. This supports gradual
CI migration while preserving one Platform-owned renderer for the final
Timeweb tree.

The rendered tree contains only:

- `docker-compose.yml`;
- `README.md`;
- `platform-timeweb-deploy.json`.

Guardrails:

- the first service is `app`, because Timeweb proxies the public domain to the
  first service;
- API/UI image refs must be digest-pinned and must not use `latest`;
- no source `build` sections;
- no bind mounts or named volumes;
- no required `${VAR:?message}` interpolation;
- SpecSpace API must read SpecGraph artifacts through `--artifact-base-url`;
- SpecSpace API must read SpecPM metadata through `--specpm-registry-url`.

SpecSpace CI can switch its publish step to invoke this Platform renderer once
it provides either the digest-pinned image refs or a `platform_service_image_lock`
artifact as input. Timeweb secrets or deploy variables should move only in that
explicit cutover step.

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
