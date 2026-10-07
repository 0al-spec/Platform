"""Exercise actual merged Compose policies and safe secret-file provisioning."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.install_normlab_inference_secret import install_secret

ROOT = Path(__file__).resolve().parents[1]


def render(*overlays: str, settings: dict[str, str] | None = None) -> dict:
    environment = {
        **os.environ,
        "PLATFORM_NORMLAB_IMAGE": "ghcr.io/soundblaster/normlab@sha256:" + "1" * 64,
        "PLATFORM_NORMLAB_OPERATOR_PASSWORD_FILE": "/tmp/normlab-fixture-password",
        "PLATFORM_NORMLAB_OPENAI_BASE_URL": "https://api.openai.com/v1",
        "PLATFORM_NORMLAB_TYPESAFE_BASE_URL": "https://api.typesafe.ai/v1",
        "PLATFORM_NORMLAB_INFERENCE_CLASSIFIER": "openai",
        "PLATFORM_NORMLAB_DECISIONS_MODEL": "gpt-6-luna",
        **(settings or {}),
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
                for helper in ("normlab-inference-gateway", "normlab-inference-egress"):
                    self.assertEqual(
                        services[helper]["command"][:2], ["/bin/sh", "-ec"]
                    )
                    self.assertIn(
                        "test -f server/inference-endpoints.ts; exec ",
                        services[helper]["command"][2],
                    )
                    # The NormLab image declares VOLUME /var/lib/normlab; without this
                    # mask Docker attaches a writable anonymous volume to read-only helpers.
                    self.assertIn(
                        "/var/lib/normlab:size=64k,mode=0500", services[helper]["tmpfs"]
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
                for setting, expected in {
                    "NORMLAB_OPENAI_BASE_URL": "https://api.openai.com/v1",
                    "NORMLAB_TYPESAFE_BASE_URL": "https://api.typesafe.ai/v1",
                }.items():
                    self.assertEqual(gateway["environment"][setting], expected)
                    self.assertEqual(
                        services["normlab-inference-egress"]["environment"][setting],
                        expected,
                    )

    def test_coreinfra_route_is_shared_by_gateway_and_egress_without_exposing_keys(
        self,
    ):
        settings = {
            "PLATFORM_NORMLAB_OPENAI_BASE_URL": "https://hub.coreinfra.ai/codex/api/v1",
            "PLATFORM_NORMLAB_TYPESAFE_BASE_URL": "https://jev.provider.example/proxy/v1",
        }
        for overlays in [("inference",), ("inference", "typesafe")]:
            with self.subTest(overlays=overlays):
                services = render(*overlays, settings=settings)["services"]
                gateway = services["normlab-inference-gateway"]["environment"]
                egress = services["normlab-inference-egress"]["environment"]
                for setting, base in settings.items():
                    name = setting.removeprefix("PLATFORM_")
                    self.assertEqual(gateway[name], base)
                    self.assertEqual(egress[name], base)
                    self.assertNotIn(name, services["normlab"]["environment"])
                self.assertFalse(services["normlab-inference-egress"].get("secrets"))
                self.assertFalse(services["normlab-inference-egress"].get("ports"))

    def test_decisions_classifier_is_operator_selected_without_new_secrets_or_hosts(
        self,
    ):
        settings = {
            "PLATFORM_NORMLAB_INFERENCE_CLASSIFIER": "decisions",
            "PLATFORM_NORMLAB_DECISIONS_MODEL": "provider/luna-alias",
            "PLATFORM_NORMLAB_OPENAI_BASE_URL": "https://hub.coreinfra.ai/codex/api/v1",
        }
        services = render("inference", settings=settings)["services"]
        gateway = services["normlab-inference-gateway"]
        self.assertEqual(
            gateway["environment"]["NORMLAB_INFERENCE_CLASSIFIER"], "decisions"
        )
        self.assertEqual(
            gateway["environment"]["NORMLAB_DECISIONS_MODEL"], "provider/luna-alias"
        )
        self.assertEqual(
            {secret["source"] for secret in gateway["secrets"]},
            {"normlab_inference_token", "normlab_openai_api_key"},
        )
        self.assertEqual(
            services["normlab-inference-egress"]["environment"][
                "NORMLAB_OPENAI_BASE_URL"
            ],
            settings["PLATFORM_NORMLAB_OPENAI_BASE_URL"],
        )
        self.assertNotIn("NORMLAB_DECISIONS_MODEL", services["normlab"]["environment"])
        self.assertNotIn(
            "NORMLAB_INFERENCE_CLASSIFIER", services["normlab"]["environment"]
        )
        self.assertEqual(
            render("inference", "typesafe", settings=settings)["services"][
                "normlab-inference-gateway"
            ]["environment"]["NORMLAB_INFERENCE_CLASSIFIER"],
            "typesafe",
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

    @unittest.skipUnless(os.geteuid() == 0, "needs root to create a foreign-owned dir")
    def test_provisioning_rejects_a_directory_owned_by_another_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "secrets"
            folder.mkdir(mode=0o700)
            os.chown(folder, 1000, 1000)
            with self.assertRaises(ValueError):
                install_secret(
                    "openai", "synthetic-fixture-key-not-for-a-provider-00000", folder
                )
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
