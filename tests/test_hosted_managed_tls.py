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

    def test_provisioning_is_fail_closed_and_dns_pinned(self) -> None:
        self.assertTrue(self.script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"))
        self.assertIn('grep -Fxq "${expected_ip}"', self.script)
        self.assertIn("--standalone --non-interactive --agree-tos", self.script)
        self.assertIn("--keep-until-expiring --preferred-challenges http", self.script)
        self.assertIn('systemctl enable --now certbot.timer', self.script)
        self.assertNotIn("register-unsafely-without-email", self.script)

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
            "managed.specgraph.tech",
            "46.229.214.241",
            "@specgraph",
            "service-token",
            "github-token",
            "database-password",
        ):
            self.assertNotIn(forbidden, self.script)
