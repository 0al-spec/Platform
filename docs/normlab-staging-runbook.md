# NormLab private staging

NormLab staging runs beside Platform's managed services at
`https://managed.specgraph.tech/normlab`. It uses the Platform TLS ingress,
operator-only Basic Auth, a private container network, and a dedicated Docker
volume for its SQLite database and receipt-signing key. The public
`https://specgraph.space` Timeweb application is not changed.

This is a synthetic-data staging deployment. It has no OpenAI or TypeSafe.ai
keys in the base profile and the NormLab container is attached only to an internal
Docker network, so it has no outbound provider access. The optional
[inference overlays](normlab-inference-runbook.md) prepare isolated provider access;
they are not enabled by deploying the base profile. Do not add real case data.

## Prerequisites

- The Platform production Compose profile is already deployed with the
  `platform-managed-normlab` internal network from
  `docker-compose.hosted-managed-production.example.yml`.
- The VPS has at least 2 GiB of free memory for NormLab's bounded Lean process.
- The VPS can pull the private `ghcr.io/soundblaster/normlab` image. Authenticate
  Docker with a GitHub token that has `read:packages`; never put that token in
  this repository or in the Compose environment.
- Create `/srv/0al/secrets/normlab-operator-password` on the VPS with a unique
  password. The container runs as UID/GID `1000`; make the file owned by
  `1000:1000` with mode `0400` so the application can read it without exposing
  the secret to other host users.
- Create `/etc/0al/normlab-staging.env` from
  `deploy/hosted-managed/normlab-staging.env.example`. Set
  `PLATFORM_NORMLAB_IMAGE` there to the digest-pinned
  image from the `normlab-image-lock` CI artifact, and set
  `PLATFORM_NORMLAB_OPERATOR_PASSWORD_FILE` to that password-file path.

## Deploy

Apply the Platform production Compose update through its normal deployment
procedure after merging the Platform PR. This creates the shared internal
network and adds the route to the existing TLS ingress. The ingress
configuration gains one route and an internal network; it does not alter the
SpecGraph.space Timeweb app. Applying the changed Platform profile may briefly
restart Caddy:

```sh
docker compose --project-name platform-managed-production \
  --env-file /etc/0al/hosted-managed-production.env \
  --file docker-compose.hosted-managed-production.example.yml config
```

The command above only validates the rendered configuration; it does not create
the network. Confirm the Platform ingress is healthy before continuing. Then
start NormLab as its own Compose project:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml config

docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml up --detach
```

Check container health and the public operator route:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml ps

curl --fail https://managed.specgraph.tech/normlab/health
```

Open `https://managed.specgraph.tech/normlab/`. The browser should prompt for
the operator username and password. Static assets and API requests share the
same authentication boundary; only the minimal `/health` response is public.

## Persistence and removal

The SQLite database and signing key live in the named volume
`normlab-staging_normlab-data`. A normal `up` or container replacement keeps
the volume. Do not use `docker compose down --volumes` unless you intend to
delete both the research history and its signing identity. Back up the volume
using the procedure in NormLab's
[deployment runbook](https://github.com/SoundBlaster/NormLab/blob/main/docs/DEPLOYMENT.md)
with the volume name above.

To stop the service while preserving its data:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml down
```

## Limits

- One shared operator password; no user accounts or per-user data separation.
- Lean verification is limited to 1024 MiB and the container to 2 GiB and one CPU.
- Timeweb App Platform is not the stateful host for this service: its Compose
  profile rejects volumes and each redeploy creates a new data environment.
- Provider inference requires the separately reviewed overlays and a new compatible
  NormLab image; the base profile keeps its previous isolation and manual demo.
