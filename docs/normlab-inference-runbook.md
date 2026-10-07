# NormLab inference on the existing VPS

Prepared 2026-10-07; opt-in configuration, not an applied production change.
Requires a new digest-pinned NormLab image containing `server/inference-gateway.ts`
and `server/inference-egress.ts`. The old staging image does not provide these
entrypoints. See the [application contract](https://github.com/SoundBlaster/NormLab/blob/main/docs/HOSTED_INFERENCE.md)
for pipeline limits, retained artifacts and provider semantics.

## Secret paths and installation

| Secret | Exact VPS file | Container mount | Mounted in |
| --- | --- | --- | --- |
| OpenAI API key | `/srv/0al/secrets/normlab-inference/openai-api-key` | `/run/secrets/normlab_openai_api_key` | Gateway |
| TypeSafe API key | `/srv/0al/secrets/normlab-inference/typesafe-api-key` | `/run/secrets/normlab_typesafe_api_key` | Gateway, optional TypeSafe overlay |
| Internal token | `/srv/0al/secrets/normlab-inference/gateway-token` | `/run/secrets/normlab_inference_token` | Gateway + NormLab |

The existing `/srv/0al/secrets/normlab-operator-password` remains the browser's
operator credential. The gateway token is independently generated and never
used as that password. GitHub/GHCR tokens remain independent registry credentials.

On the VPS, from the Platform checkout, run:

```sh
sudo python3 scripts/install_normlab_inference_secret.py gateway
sudo python3 scripts/install_normlab_inference_secret.py openai
# Only when enabling Jev classification:
sudo python3 scripts/install_normlab_inference_secret.py typesafe
```

The helper prompts for API keys with hidden terminal input, creates only the
dedicated directory (root, `0700`), and atomically installs files owned by
`1000:1000` with mode `0400`. It prints paths/permissions, never values.
Keys must contain 32–8192 printable ASCII characters without whitespace.
Paste directly from the provider dashboard/password manager. Do not pass values
as CLI arguments, environment variables, Compose literals, GitHub comments or
chat messages. `/etc/0al/normlab-staging.env` contains image/model/quota settings
only. File-backed Compose secrets are host files, not an encrypted vault.

To rotate a credential, run the same helper and recreate its consumers: gateway
for provider keys, both NormLab and gateway for the internal token. Replacement
is atomic, and an existing bind mount/process may still hold the prior value
until recreation. Preserve the named NormLab data volume.

## Network policy

| Hop | Operation | Exposure |
| --- | --- | --- |
| Browser → existing Caddy → NormLab | HTTPS 443 `/normlab/api/parking/extract`, private 4317 | Existing operator auth/Origin/CSRF |
| NormLab → gateway | POST `http://normlab-inference-gateway:4318/v1/extract` | Dedicated internal network + internal token |
| Gateway → egress | CONNECT `http://normlab-inference-egress:4319` | Second dedicated internal network |
| Egress → OpenAI | TLS TCP 443 to `api.openai.com`; adapter POST `/v1/responses` | Outbound only |
| Egress → TypeSafe | TLS TCP 443 to `api.typesafe.ai`; adapter POST `/v1/systemone` | Outbound only |

Only the egress container joins a network with a default internet route.
NormLab cannot reach the egress proxy directly, and gateway has no direct
internet network. The proxy permits the two exact CONNECT authorities and
checks resolved public addresses before dialing. It rejects private IPs,
literal IP authorities, plaintext HTTP, alternate ports and other domains.
TLS certificate/hostname checks remain enabled in the gateway. Domain/port
checks happen in the proxy; API path/shape restrictions happen in the adapters.
There is no TLS interception or generic user-configurable forward proxy.

Docker's embedded DNS forwards name resolution through the VPS resolver.
Egress therefore needs DNS resolution and outbound TCP 443; no new incoming
host port, Caddy route, Timeweb App Platform application or public DNS name is
needed. Networks are scoped to Compose project `normlab-staging`, while the
existing external ingress network remains `platform-managed-normlab`.
The proxy itself and host/Docker administration remain trusted. Do not interpret
this topology as a host firewall destination rule or protection from host root.

## Enable after review and provider availability confirmation

The supplied VPS screenshot indicates a Russian region. Russia is not in
[OpenAI's supported-country list](https://developers.openai.com/api/docs/supported-countries).
Confirm an eligible provider/account/deployment arrangement before adding keys
or enabling this profile. The proxy is on the same VPS and does not change
region or external source IP. TypeSafe account/region access also needs checking.
The manual demo remains usable without these overlays.

Update `PLATFORM_NORMLAB_IMAGE` in `/etc/0al/normlab-staging.env` to the new CI
image digest. Existing health checks do not verify account access or inference.
Render the OpenAI discovery + OpenAI classification profile:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml \
  --file docker-compose.normlab-inference.example.yml config --quiet
```

Append `--file docker-compose.normlab-typesafe.example.yml` before `config`
to select OpenAI discovery + Jev classification. The base inference overlay
needs only the OpenAI file and internal token; TypeSafe's file is required only
by its overlay. Model defaults are `gpt-6-luna` and pinned `jev-1.13.0`.
The model is chosen by server configuration, never a browser request.

After configuration review, replace `config --quiet` with
`up --detach normlab normlab-inference-gateway normlab-inference-egress` using
the same file list. Compose starts the egress/gateway health dependencies first.
It does not restart the shared Platform/Caddy project. Gateway/proxy memory
limits are 256/128 MiB, adding at most 384 MiB of configured ceilings to the
existing NormLab profile; confirm actual free VPS memory before activation.
No additional billable Timeweb app is created.

## Acceptance and rollback

1. Verify all three containers are healthy and neighboring Platform services
   retain their prior state. Inspect network memberships: only the proxy joins
   the outbound bridge. Check no new host ports are published.
2. Check public health `200` and unauthenticated UI/API `401`, then open the
   operator route with the existing credential. The UI should disclose external
   inference when enabled.
3. From NormLab and gateway, direct access to provider IP/443 should fail.
   Through the proxy, CONNECT to `example.com:443` and private destinations
   should be denied; the two provider TLS hostnames should be reachable.
   A connection check without authorization does not establish usable keys.
4. Run one synthetic case through the UI. Verify exact quotes, source digest,
   resolved model names and pending decisions in its original extraction.
   Then deliberately test provider rejection/timeout: the old draft revision
   must remain available. No production readiness or extraction quality claim
   follows from a single successful call.
5. Default six attempts/hour and one active extraction are application limits.
   The counter resets on gateway restart; configure provider project spending
   limits as the billing control. No retries/fallbacks are enabled.

For rollback recreate only NormLab using the original staging file with
`NORMLAB_INFERENCE_MODE` disabled/default, then stop the two helper services.
Keep their secret files and the data volume for recovery; do not run a shared
Compose `down` or remove volumes. Do not use `--remove-orphans` on a shared
project without inventorying unrelated services.

Local/CI configuration validation is provided by
`tests/test_normlab_inference.py`; the application owns provider/egress contract
tests. Neither replaces a deployment acceptance run in the intended region.
