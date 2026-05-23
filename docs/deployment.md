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

The initial implementation wraps Docker Compose directly:

- `deploy render` runs `docker compose config`;
- `deploy up` runs `docker compose up -d`;
- `deploy status` runs `docker compose ps`;
- `deploy down` runs `docker compose down`.

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

SpecSpace API also receives a writable `specspace-dialogs` volume mounted at
`SPECSPACE_DIALOG_DIR` because `viewer/server.py` still requires a dialog store.
That dialog store is runtime state, not a Platform catalog or SpecGraph project
contract.

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
