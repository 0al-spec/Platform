from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts import hosted_managed_compose_smoke as compose_smoke


class HostedManagedComposeSmokeTests(unittest.TestCase):
    def test_wait_allows_running_services_to_finish_startup(self) -> None:
        inspect_count = 0

        def runner(command, **_kwargs):
            nonlocal inspect_count
            if command[:2] == ["docker", "inspect"]:
                inspect_count += 1
                health = "starting" if inspect_count <= len(compose_smoke.SERVICES) else "healthy"
                return json.dumps(
                    {
                        "Status": "running",
                        "Health": {"Status": health},
                    }
                )
            if "ps" in command and "--quiet" in command:
                return "container-id\n"
            raise AssertionError(f"unexpected command: {command}")

        with (
            mock.patch.object(compose_smoke, "_run", side_effect=runner),
            mock.patch.object(compose_smoke.time, "monotonic", return_value=0),
            mock.patch.object(compose_smoke.time, "sleep"),
        ):
            compose_smoke._wait_for_service_health(
                ["docker", "compose"],
                environment={},
                timeout_seconds=1,
            )

        self.assertEqual(inspect_count, len(compose_smoke.SERVICES) * 2)

    def test_wait_fails_immediately_for_terminal_container(self) -> None:
        def runner(command, **_kwargs):
            if command[:2] == ["docker", "inspect"]:
                return json.dumps(
                    {
                        "Status": "exited",
                        "Health": {"Status": "unhealthy"},
                    }
                )
            if "ps" in command and "--quiet" in command:
                return "container-id\n"
            raise AssertionError(f"unexpected command: {command}")

        with (
            mock.patch.object(compose_smoke, "_run", side_effect=runner),
            mock.patch.object(compose_smoke.time, "monotonic", return_value=0),
        ):
            with self.assertRaisesRegex(RuntimeError, "entered terminal state"):
                compose_smoke._wait_for_service_health(
                    ["docker", "compose"],
                    environment={},
                    timeout_seconds=1,
                )


if __name__ == "__main__":
    unittest.main()
