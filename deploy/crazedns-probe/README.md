# Timeweb → CrazeDNS → home connectivity probe

A disposable, stateless test application. It has no access to Platform data,
PostgreSQL, GitHub, AI providers, files outside its own source/secret, or shell
execution endpoints. It is not a SpecSpace backend and does not change production
SpecSpace routing.

## Topology

```text
Operator browser → separate Timeweb App (client role, HTTP Basic authentication)
                 → HTTPS CrazeDNS test hostname
                 → router reverse proxy → LXC 103:18086 (home role, bearer token)
```

CrazeDNS terminates public HTTPS at the router. This test uses HTTP from the
router to the separate home listener on the LAN. It does not claim end-to-end
TLS to the container. Only synthetic payloads and the test-scoped credential are
sent over that LAN hop.

## Home service

Copy this directory to `/srv/crazedns-probe/app` in LXC 103. Generate a fresh
random token of at least 32 characters outside Git and store it in
`/srv/crazedns-probe/secrets/probe-token`, readable by container uid 1000 only.
Use a separate Compose project:

```sh
docker compose -f compose.home.yml config --quiet
docker compose -f compose.home.yml up -d --build
```

The service binds `192.168.1.161:18086`. Configure only a dedicated test CrazeDNS
subdomain to proxy this listener. Preserve all other router routes and access
levels. Public exposure and saving router configuration require operator
authorization under HomeLocal rules; record any saved or temporary route there.

`GET /health` is a public liveness endpoint. All other home routes require the
test bearer token. The service supports only GET/POST on `/v1/probe` and
`/specspace-state/v1/probe`. POST accepts JSON objects up to 8192 bytes.

## Timeweb service

Publish **only this directory** at the root of a dedicated deployment branch so
Timeweb sees its Dockerfile. Keep autodeploy disabled. Create a separate backend
App using the smallest suitable preset; do not modify the production App.

Set runtime variables in the provider's secret/variable facility:

- `PROBE_ROLE=client`
- `PROBE_HOME_URL=https://<test-hostname>`
- `PROBE_TOKEN`: the dedicated home token
- `PROBE_OPERATOR_PASSWORD`: a different random password of at least 32 characters

Do not pass secrets as Docker build arguments, bake them into image layers,
commit them, or log rendered environment values. The application refuses to
start with missing credentials. Login to the test page as `operator`; press
the check button to make the server-side probe. No backend token enters the UI.

## Acceptance

One authenticated `POST /api/probe` on the Timeweb App performs five bounded
server-side requests with a fresh nonce:

1. No bearer token → genuine application JSON with HTTP 401.
2. Wrong bearer token → genuine application JSON with HTTP 401.
3. Valid authenticated GET → matching nonce and method.
4. Valid POST/JSON → matching nonce and payload.
5. POST via the state-service prefix → matching nonce and payload.

All five must pass for `ok=true`; a login page, redirect, TLS failure, malformed
JSON, wrong nonce, or inaccessible backend is a failed check. Calls have five
second timeouts, do not follow redirects, and accept bounded responses. Only one
probe may run at once. The remote URL is configured server-side, never supplied
by a request. `/health` proves process liveness only, not home connectivity.
The Dockerfile healthcheck targets that endpoint, independently of whether the
home server is reachable; successful deployment does not imply a passing probe.

## Verification and cleanup

Run `tests/test_crazedns_probe.py` with the repository Python environment.
Local tests cover real loopback HTTP, both authentication boundaries, JSON/body
limits, prefix routing, credential mismatch, and origin checks. They do not
establish CrazeDNS or Timeweb readiness.

For cleanup, remove only the dedicated test route, stop only the
`crazedns-probe` Compose project, delete only the dedicated Timeweb App, and
revoke the two test credentials. Keep production routes, Apps and volumes intact.
