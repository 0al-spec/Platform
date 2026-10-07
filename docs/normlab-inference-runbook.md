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

The OpenAI secret is the selected OpenAI-compatible supplier's credential,
including CoreInfra when its API base is selected. Replace it with the new
supplier's credential when changing suppliers; never send an old direct-OpenAI
key to a reseller. The file name is unchanged. Both providers use Bearer headers.

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
| Egress → Responses supplier | TLS TCP 443 to configured DNS host; adapter POST API base + `/responses` | Outbound only |
| Egress → System One supplier | TLS TCP 443 to configured DNS host; adapter POST API base + `/systemone` | Outbound only |

Only the egress container joins a network with a default internet route.
NormLab cannot reach the egress proxy directly, and gateway has no direct
internet network. The proxy permits the two configured exact CONNECT authorities and
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

Requires a **new image containing configurable endpoints**, not merely the
initial gateway image from NormLab #28. The default destinations remain direct
OpenAI and TypeSafe. A startup file check prevents the legacy image from silently
ignoring these URL settings; it does not prove API/account readiness.
In `/etc/0al/normlab-staging.env`, select CoreInfra with:

```dotenv
PLATFORM_NORMLAB_OPENAI_BASE_URL=https://hub.coreinfra.ai/codex/api/v1
# Use the model identifier confirmed by this supplier:
PLATFORM_NORMLAB_OPENAI_MODEL=gpt-6-luna
```

The complete API prefix is retained, producing exactly
`https://hub.coreinfra.ai/codex/api/v1/responses`. Compose sends the same base
to gateway and egress. The proxy replaces `api.openai.com:443` with
`hub.coreinfra.ai:443` for this configuration; no other OpenAI destination is
allowed. `PLATFORM_NORMLAB_TYPESAFE_BASE_URL` similarly selects System One's
API base (default `https://api.typesafe.ai/v1`). Both require HTTPS, DNS names,
port 443 and no credentials/query/fragment. These non-secret URLs never reach
the browser. Rotate the corresponding key with the hidden-input installer.

Recreate **both gateway and egress** after changing an API base; otherwise
their independently derived settings can disagree and requests fail closed.
Keep the image digest identical across all three services. The configuration
does not establish supplier compatibility: Responses must accept non-streaming
JSON, strict `text.format` JSON Schema, `store:false`, Bearer auth and reasoning
settings. Chat Completions/SSE-only protocols need another adapter. The supplied
CoreInfra URL was probed with GET without credentials on 2026-10-07 and returned
404; authenticated POST and model access remain unverified. Do not infer readiness
from that probe or from mocked tests. Run one synthetic acceptance case after
supplier/account eligibility and key provisioning are established.

The supplied VPS screenshot indicates a Russian region. Russia is not in
[OpenAI's supported-country list](https://developers.openai.com/api/docs/supported-countries).
Confirm an eligible provider/account/deployment arrangement before adding keys
or enabling this profile. The proxy is on the same VPS and does not change
region or external source IP. TypeSafe account/region access also needs checking.
For a reseller, assess its own supported regions, account terms and API access;
the direct-OpenAI observation does not establish CoreInfra's eligibility.
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

In gateway mode NormLab reads its token file at startup and exits if it is missing
or not a private (`0400`/`0600`) file, which also stops the manual demo. Install
the secrets first and keep `config --quiet` as the gate before `up`.

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

For rollback, first recreate only NormLab from the base staging file, which
leaves inference disabled and detaches it from the inference network:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml \
  up --detach --wait --no-deps normlab
```

Compose then warns about orphan helper containers and suggests
`--remove-orphans`; that warning is expected, do not add the flag. Stop the
helpers with the overlay in the file list, otherwise Compose answers
`no such service`:

```sh
docker compose --project-name normlab-staging \
  --env-file /etc/0al/normlab-staging.env \
  --file docker-compose.normlab-staging.example.yml \
  --file docker-compose.normlab-inference.example.yml \
  stop normlab-inference-gateway normlab-inference-egress
```

Keep their secret files and the data volume for recovery; do not run a shared
Compose `down` or remove volumes. Do not use `--remove-orphans` on a shared
project without inventorying unrelated services.

Local/CI configuration validation is provided by
`tests/test_normlab_inference.py`; the application owns provider/egress contract
tests. Neither replaces a deployment acceptance run in the intended region.
