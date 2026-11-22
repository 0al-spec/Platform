# Heroes III ingress

The hosted managed ingress routes `/heroes3` to `/heroes3/` and proxies
`/heroes3/*` to `vcmi-lobby-website-1:80`, preserving the path prefix. This
is the independent VCMI website and terrain painter, not the Platform service
or the TCP game lobby. The VCMI Compose project attaches its website to the
Platform managed ingress network; it must not publish the website's port on
the host. The website must be running for this route to serve content; without
it requests to the route can fail, while the other routes remain independent.

Caddy is the trusted entry point for the painter's client rate limit. It must
not trust arbitrary forwarded addresses from external callers, and untrusted
containers must not be attached to the shared ingress network. Consult the
VCMI deployment documentation before changing the proxy chain.

After deploying a Platform configuration update, check `/heroes3` redirects to
`/heroes3/`, the landing page and `/heroes3/api/health` respond through HTTPS,
and the other Platform and NormLab routes retain their expected behavior. An
HTTP health response does not establish that a multiplayer game works.
