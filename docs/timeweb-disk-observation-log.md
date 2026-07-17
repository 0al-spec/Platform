# Timeweb Cloud Apps Disk Observation Log

This is a bounded operational observation for the production SpecSpace
application. It distinguishes application-owned state from Timeweb-managed
Docker image, layer, container, deployment-cache, and log retention.

The observation starts with the first production deployment after this policy
is merged and ends after five deployments. Evaluate the trend after deployment
three; continue through deployment five unless the threshold below already
requires escalation.

The operator records values reported by the Timeweb control panel. Do not place
tokens, environment values, raw idea text, or other private workspace state in
this log.

| Deploy | UTC timestamp | Release commit | API/UI image digests | Used before | Used after or at +24h | Delta | Result / notes |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | pending | pending | pending | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending | pending | pending | trend review due |
| 4 | pending | pending | pending | pending | pending | pending | pending |
| 5 | pending | pending | pending | pending | pending | pending | observation closes |

Escalate to Timeweb support when either condition is met:

- unexplained disk usage grows monotonically across three observed deployments;
- disk usage reaches 80 percent before the five-deployment observation closes.

The support request should ask Timeweb to identify and remove unused deployment
containers, images, layers, build cache, and retained logs without deleting the
active application configuration, domain, or global environment variables. It
should also ask whether an automatic retention or prune policy can be enabled
for the application.

After support cleanup, record the before/after values in the relevant row.
Recreating the application is not the default cleanup procedure because
application-level settings can be lost during replacement.
