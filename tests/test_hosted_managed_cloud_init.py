from __future__ import annotations

from pathlib import Path
import unittest


class HostedManagedCloudInitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cloud_init = (
            Path(__file__).resolve().parents[1]
            / "deploy"
            / "hosted-managed"
            / "cloud-init.production.example.yaml"
        ).read_text(encoding="utf-8")

    def test_bootstrap_has_the_required_host_baseline(self) -> None:
        self.assertTrue(self.cloud_init.startswith("#cloud-config\n"))
        for package in (
            "ca-certificates",
            "curl",
            "git",
            "jq",
            "ufw",
            "docker.io",
            "docker-compose-v2",
            "python3",
            "unattended-upgrades",
            "util-linux",
        ):
            self.assertIn(f"  - {package}\n", self.cloud_init)
        for directory in (
            "/srv/0al/platform",
            "/srv/0al/specgraph",
            "/srv/0al/specspace-state",
            "/srv/0al/backups",
            "/srv/0al/evidence",
            "/srv/0al/secrets",
        ):
            self.assertIn(directory, self.cloud_init)
        self.assertIn("set -eu", self.cloud_init)
        self.assertIn("chown 1000:1000", self.cloud_init)
        self.assertIn("chown root:1000 /srv/0al/secrets", self.cloud_init)
        self.assertLess(
            self.cloud_init.index("chown 1000:1000"),
            self.cloud_init.index(
                "touch /var/lib/0al-hosted-managed-bootstrap-complete"
            ),
        )
        self.assertNotIn("install -d -o 1000", self.cloud_init)
        self.assertIn("/srv/0al/.runtime-home", self.cloud_init)
        self.assertIn("chmod 0700 /srv/0al/.runtime-home", self.cloud_init)
        self.assertIn("systemctl enable --now docker", self.cloud_init)

    def test_bootstrap_hardens_ssh_and_only_opens_ingress_ports(self) -> None:
        self.assertIn("ssh_pwauth: false", self.cloud_init)
        self.assertIn("PasswordAuthentication no", self.cloud_init)
        self.assertIn("KbdInteractiveAuthentication no", self.cloud_init)
        self.assertIn("PermitRootLogin prohibit-password", self.cloud_init)
        self.assertIn("ufw default deny incoming", self.cloud_init)
        self.assertIn("ufw allow OpenSSH", self.cloud_init)
        self.assertIn("ufw allow 80/tcp", self.cloud_init)
        self.assertIn("ufw allow 443/tcp", self.cloud_init)
        self.assertNotIn("8091", self.cloud_init)
        self.assertNotIn("5432", self.cloud_init)

    def test_bootstrap_cannot_contain_runtime_or_secret_configuration(self) -> None:
        forbidden = (
            "PLATFORM_MANAGED_OPERATION_",
            "ghcr.io/",
            "BEGIN OPENSSH PRIVATE KEY",
            "BEGIN PRIVATE KEY",
            "github-token",
            "service-token",
            "database-password",
            "tls-private-key",
        )
        for value in forbidden:
            self.assertNotIn(value, self.cloud_init)
        self.assertIn("no SSH key", self.cloud_init)
        self.assertIn("no SSH key, deployment image", self.cloud_init)
