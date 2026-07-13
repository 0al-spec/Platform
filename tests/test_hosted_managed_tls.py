from __future__ import annotations

from pathlib import Path
import unittest


class HostedManagedTlsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.script = (
            root / "deploy" / "hosted-managed" / "hosted-managed-tls.sh"
        ).read_text(encoding="utf-8")
        self.cloud_init = (
            root
            / "deploy"
            / "hosted-managed"
            / "cloud-init.production.example.yaml"
        ).read_text(encoding="utf-8")

    def test_cloud_init_installs_certbot(self) -> None:
        self.assertIn("  - certbot\n", self.cloud_init)
        self.assertIn("  - dnsutils\n", self.cloud_init)

    def test_provisioning_is_fail_closed_and_dns_pinned(self) -> None:
        self.assertTrue(self.script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
        self.assertIn('[[ "${resolved_ipv4}" == "${expected_ip}" ]]', self.script)
        self.assertIn('[[ -z "${resolved_ipv6}" ]]', self.script)
        self.assertIn('dig +short A "${domain}"', self.script)
        self.assertIn('dig +short AAAA "${domain}"', self.script)
        self.assertNotIn("getent ahostsv6", self.script)
        self.assertIn("domain must resolve to the expected IPv4 only", self.script)
        self.assertIn("domain must not publish IPv6", self.script)
        self.assertIn("--standalone --non-interactive --agree-tos", self.script)
        self.assertIn("--keep-until-expiring --preferred-challenges http", self.script)
        self.assertIn('systemctl enable --now certbot.timer', self.script)
        self.assertNotIn("register-unsafely-without-email", self.script)

    def test_runbook_verifies_the_live_deploy_hook_after_dry_run(self) -> None:
        runbook = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "hosted-managed-operations.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "certbot renew --dry-run --no-random-sleep-on-renew",
            runbook,
        )
        self.assertIn("RENEWED_LINEAGE=/etc/letsencrypt/live/managed.example.org", runbook)
        self.assertIn("RENEWED_DOMAINS=managed.example.org", runbook)
        self.assertIn("renewal-hooks/deploy/0al-hosted-managed-tls", runbook)
        self.assertNotIn("renew --dry-run --run-deploy-hooks", runbook)

    def test_renewal_syncs_only_the_configured_lineage(self) -> None:
        self.assertIn("renewed lineage does not match configured domain", self.script)
        self.assertIn('[[ "${renewed_domain}" == "${domain}" ]]', self.script)
        self.assertLess(
            self.script.index('[[ "${matched}" == true ]] || exit 0'),
            self.script.index("renewed lineage does not match configured domain"),
        )
        self.assertIn('chown root:1000 "${certificate_temp}"', self.script)
        self.assertIn('chmod 0644 "${temporary}"', self.script)
        self.assertIn("tls-certificate.pem", self.script)
        self.assertIn("tls-private-key.pem", self.script)
        self.assertIn("--force-recreate managed-operation-ingress", self.script)

    def test_script_contains_no_deployment_identity_or_credentials(self) -> None:
        for forbidden in (
            "@specgraph",
            "service-token",
            "github-token",
            "database-password",
        ):
            self.assertNotIn(forbidden, self.script)
        self.assertNotRegex(self.script, r"readonly [A-Z_]*DOMAIN=.*\.[a-z]{2,}")
        self.assertNotRegex(self.script, r"readonly [A-Z_]*IP=[0-9]")
