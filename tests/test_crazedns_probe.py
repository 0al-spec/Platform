"""Exercise the actual HTTP boundary and the cloud-to-home diagnostic client."""

import base64
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request

spec = importlib.util.spec_from_file_location(
    "crazedns_probe", Path(__file__).resolve().parents[1] / "deploy/crazedns-probe/probe.py"
)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)
TOKEN = "test-home-token-" + "a" * 40
PASSWORD = "test-operator-password-" + "b" * 40


@contextmanager
def running(config):
    server = probe.make_server(config, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url, *, auth=None, data=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.code, response.read()


class ConnectivityProbeTests(unittest.TestCase):
    def test_authenticated_roundtrip_and_both_prefixes(self):
        with running(probe.Config("home", TOKEN)) as home:
            report = probe.check_home(probe.Config("client", TOKEN, PASSWORD, home))
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["checks"]), 5)
        self.assertEqual([item["http_status"] for item in report["checks"]], [401, 401, 200, 200, 200])
        self.assertNotIn(TOKEN, json.dumps(report))

    def test_wrong_secret_fails_instead_of_reporting_connectivity_success(self):
        with running(probe.Config("home", TOKEN)) as home:
            report = probe.check_home(probe.Config("client", "wrong-" + TOKEN, PASSWORD, home))
        self.assertFalse(report["ok"])
        self.assertTrue(all(not item["ok"] for item in report["checks"][2:]))

    def test_home_json_errors_and_request_bound(self):
        with running(probe.Config("home", TOKEN)) as home:
            self.assertEqual(request(home + "/health")[0], 200)
            self.assertEqual(request(home + "/v1/probe")[0], 401)
            self.assertEqual(request(home + "/v1/probe", auth="Bearer " + TOKEN, data=b"[]")[0], 400)
            self.assertEqual(request(home + "/v1/probe", auth="Bearer " + TOKEN, data=b"x" * 8193)[0], 413)
            self.assertEqual(request(home + "/unrelated", auth="Bearer " + TOKEN)[0], 404)

    def test_cloud_operator_boundary_and_origin(self):
        auth = "Basic " + base64.b64encode(("operator:" + PASSWORD).encode()).decode()
        with running(probe.Config("home", TOKEN)) as home:
            with running(probe.Config("client", TOKEN, PASSWORD, home)) as cloud:
                self.assertEqual(request(cloud + "/health")[0], 200)
                self.assertEqual(request(cloud + "/")[0], 401)
                self.assertEqual(request(cloud + "/api/probe", auth=auth, data=b"", origin="https://other.example")[0], 403)
                status, raw = request(cloud + "/api/probe", auth=auth, data=b"")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(raw)["ok"])
                self.assertNotIn(TOKEN.encode(), raw)
                self.assertNotIn(PASSWORD.encode(), raw)

    def test_configuration_rejects_insecure_or_credential_urls(self):
        for url in ["http://192.168.1.161", "https://user:secret@example.com", "https://example.com/?token=x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.Config("client", TOKEN, PASSWORD, url)

    def test_configuration_requires_secrets(self):
        with self.assertRaises(ValueError):
            probe.Config("home", "")
        with self.assertRaises(ValueError):
            probe.Config("client", TOKEN, "", "https://example.com")
