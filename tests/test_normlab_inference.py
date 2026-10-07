"""Exercise actual merged Compose policies and safe secret-file provisioning."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.install_normlab_inference_secret import install_secret

ROOT = Path(__file__).resolve().parents[1]


def render(*overlays: str) -> dict:
    environment = {
        **os.environ,
        "PLATFORM_NORMLAB_IMAGE": "ghcr.io/soundblaster/normlab@sha256:" + "1" * 64,
        "PLATFORM_NORMLAB_OPERATOR_PASSWORD_FILE": "/tmp/normlab-fixture-password",
    }
    command = ["docker", "compose", "--project-name", "normlab-inference-contract"]
    for name in ("staging", *overlays):
        command.extend(
            ["--file", str(ROOT / f"docker-compose.normlab-{name}.example.yml")]
        )
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command, env=environment, capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


class NormLabInferenceTests(unittest.TestCase):
    def test_base_has_no_provider_secrets_or_outbound_network(self):
        payload = render()
        self.assertEqual(set(payload["services"]), {"normlab"})
        app = payload["services"]["normlab"]
        self.assertEqual(set(app["networks"]), {"normlab-private"})
        self.assertEqual(
            {s["source"] for s in app["secrets"]}, {"normlab_operator_password"}
        )

    def test_only_egress_has_an_outbound_network_and_only_gateway_has_provider_keys(
        self,
    ):
        for overlays in [("inference",), ("inference", "typesafe")]:
            with self.subTest(overlays=overlays):
                payload = render(*overlays)
                services = payload["services"]
                self.assertEqual(
                    set(services),
                    {
                        "normlab",
                        "normlab-inference-gateway",
                        "normlab-inference-egress",
                    },
                )
                expected_networks = {
                    "normlab": {"normlab-private", "inference-private"},
                    "normlab-inference-gateway": {
                        "inference-private",
                        "inference-proxy-private",
                    },
                    "normlab-inference-egress": {
                        "inference-proxy-private",
                        "inference-egress",
                    },
                }
                for name, service in services.items():
                    self.assertFalse(service.get("ports"))
                    self.assertEqual(service["user"], "1000:1000")
                    self.assertTrue(service["read_only"])
                    self.assertEqual(service["cap_drop"], ["ALL"])
                    self.assertEqual(set(service["networks"]), expected_networks[name])
                    for network in service["networks"]:
                        if network != "normlab-private":
                            self.assertEqual(
                                payload["networks"][network].get("internal", False),
                                network != "inference-egress",
                            )
                    self.assertNotIn(
                        "NORMLAB_OPENAI_API_KEY", service.get("environment", {})
                    )
                    self.assertNotIn(
                        "NORMLAB_TYPESAFE_API_KEY", service.get("environment", {})
                    )
                self.assertEqual(
                    {s["source"] for s in services["normlab"]["secrets"]},
                    {"normlab_operator_password", "normlab_inference_token"},
                )
                self.assertFalse(services["normlab-inference-egress"].get("secrets"))
                self.assertFalse(services["normlab-inference-egress"].get("volumes"))
                gateway = services["normlab-inference-gateway"]
                expected_keys = {"normlab_inference_token", "normlab_openai_api_key"}
                if "typesafe" in overlays:
                    expected_keys.add("normlab_typesafe_api_key")
                self.assertEqual(
                    {s["source"] for s in gateway["secrets"]}, expected_keys
                )
                self.assertEqual(
                    gateway["environment"]["NORMLAB_INFERENCE_CLASSIFIER"],
                    "typesafe" if "typesafe" in overlays else "openai",
                )
                self.assertEqual(
                    payload["secrets"]["normlab_openai_api_key"]["file"],
                    "/srv/0al/secrets/normlab-inference/openai-api-key",
                )

    def test_provisioning_is_private_atomic_and_rejects_bad_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "secrets"
            key = "synthetic-fixture-key-not-for-a-provider-00000"
            path = install_secret(
                "openai", key, folder, uid=os.getuid(), gid=os.getgid()
            )
            self.assertEqual(path.read_text(), key)
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            second = install_secret(
                "openai", key + "new", folder, uid=os.getuid(), gid=os.getgid()
            )
            self.assertEqual(second.read_text(), key + "new")
            self.assertEqual(list(folder.iterdir()), [second])
            with self.assertRaises(ValueError):
                install_secret("../elsewhere", key, folder)
            with self.assertRaises(ValueError):
                install_secret("openai", key + "\n", folder)
            alias = folder / "typesafe-api-key"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                install_secret("typesafe", key, folder)


if __name__ == "__main__":
    unittest.main()
