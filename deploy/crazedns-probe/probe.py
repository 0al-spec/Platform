"""Bounded, stateless HTTP connectivity probe; no Platform data or credentials."""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = "crazedns-connectivity-probe"
MAX_BODY = 8192


def secret_value(name: str) -> str:
    filename = os.environ.get(name + "_FILE")
    return Path(filename).read_text().strip() if filename else os.environ.get(name, "")


@dataclass(frozen=True)
class Config:
    role: str
    token: str
    password: str = ""
    home_url: str = ""

    def __post_init__(self) -> None:
        if self.role not in {"home", "client"}:
            raise ValueError("PROBE_ROLE must be home or client")
        if len(self.token) < 32:
            raise ValueError("PROBE_TOKEN must contain at least 32 characters")
        if self.role == "client":
            if len(self.password) < 32:
                raise ValueError("PROBE_OPERATOR_PASSWORD must contain at least 32 characters")
            parsed = urllib.parse.urlsplit(self.home_url)
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
            ):
                raise ValueError("PROBE_HOME_URL must be HTTPS (HTTP is allowed on loopback only)")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_home(config: Config) -> dict:
    """Only fixed paths, small synthetic payloads, no redirects, five-second calls."""
    nonce = secrets.token_hex(16)
    cases = [
        ("no_token", "GET", "/v1/probe", None, None, 401),
        ("wrong_token", "GET", "/v1/probe", None, "incorrect-probe-token", 401),
        ("get", "GET", "/v1/probe?nonce=" + nonce, None, config.token, 200),
        ("post_json", "POST", "/v1/probe", {"nonce": nonce, "message": "hello from Timeweb"}, config.token, 200),
        ("state_prefix", "POST", "/specspace-state/v1/probe", {"nonce": nonce, "message": "state prefix"}, config.token, 200),
    ]
    checks = []
    opener = urllib.request.build_opener(NoRedirect())
    for name, method, path, payload, token, expected in cases:
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            config.home_url.rstrip("/") + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        started = time.monotonic()
        status, body, error = None, {}, None
        try:
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status = response.code
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise ValueError("response too large")
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError("response is not a JSON object")
        except (OSError, ValueError, urllib.error.URLError):
            error = "transport_tls_or_json_error"
        passed = error is None and status == expected and body.get("application") == APP
        if expected == 200:
            passed = passed and body.get("role") == "home" and body.get("method") == method
            passed = passed and body.get("nonce") == nonce and body.get("authenticated") is True
            if payload is not None:
                passed = passed and body.get("payload") == payload
        checks.append({"name": name, "ok": passed, "http_status": status,
                       "elapsed_ms": round((time.monotonic() - started) * 1000), "error": error})
    return {"application": APP, "ok": all(check["ok"] for check in checks),
            "nonce": nonce, "checks": checks}


PAGE = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Timeweb → Home</title>
<style>body{font:18px system-ui;max-width:800px;margin:60px auto;padding:20px}
button{font:inherit;padding:12px 20px}pre{font-size:14px;white-space:pre-wrap}</style>
<h1>Timeweb → CrazeDNS → Home</h1>
<p>Проверка соединения с тестовым приложением. Рабочие данные не используются.</p>
<button id="run">Проверить соединение</button><pre id="result"></pre>
<script>document.getElementById('run').onclick=async()=>{
const b=document.getElementById('run'),r=document.getElementById('result');
b.disabled=true;r.textContent='Проверка…';try{
const response=await fetch('/api/probe',{method:'POST',credentials:'same-origin'});
r.textContent=JSON.stringify(await response.json(),null,2);
}catch(e){r.textContent='Не удалось получить результат';}finally{b.disabled=false;}};</script>
</html>"""


def make_server(config: Config, address=("0.0.0.0", 8080)) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ConnectivityProbe"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_):
            pass  # Never log credentials, query strings, or user payloads.

        def reply(self, status: int, body, *, html=False, challenge=False):
            data = body.encode() if html else json.dumps({"application": APP, **body}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if challenge:
                self.send_header("WWW-Authenticate", 'Basic realm="Connectivity probe", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if self.command == "GET" and path == "/health":
                self.reply(200, {"ok": True, "role": config.role})
                return
            expected = "Bearer " + config.token if config.role == "home" else "Basic " + base64.b64encode(
                ("operator:" + config.password).encode()).decode()
            received = self.headers.get("Authorization", "")
            if not hmac.compare_digest(received.encode(), expected.encode()):
                self.reply(401, {"ok": False, "error": "unauthorized"}, challenge=config.role == "client")
                return
            if config.role == "client":
                if self.command == "GET" and path == "/":
                    self.reply(200, PAGE, html=True)
                elif self.command == "POST" and path == "/api/probe":
                    origin = self.headers.get("Origin")
                    if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
                        self.reply(403, {"ok": False, "error": "origin_mismatch"})
                    elif not lock.acquire(blocking=False):
                        self.reply(429, {"ok": False, "error": "probe_already_running"})
                    else:
                        try:
                            report = check_home(config)
                            self.reply(200 if report["ok"] else 502, report)
                        finally:
                            lock.release()
                else:
                    self.reply(404, {"ok": False, "error": "not_found"})
                return
            if path not in {"/v1/probe", "/specspace-state/v1/probe"}:
                self.reply(404, {"ok": False, "error": "not_found"})
                return
            payload = None
            if self.command == "POST":
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                        self.reply(413, {"ok": False, "error": "invalid_body_size"})
                        return
                    if self.headers.get_content_type() != "application/json":
                        self.reply(415, {"ok": False, "error": "json_required"})
                        return
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("incomplete body")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object required")
                except (ValueError, OSError):
                    self.reply(400, {"ok": False, "error": "invalid_json"})
                    return
            nonce = payload.get("nonce") if payload is not None else urllib.parse.parse_qs(parsed.query).get("nonce", [None])[0]
            self.reply(200, {"ok": True, "role": "home", "method": self.command,
                             "authenticated": True, "nonce": nonce, "payload": payload})

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    configuration = Config(os.environ.get("PROBE_ROLE", "client"), secret_value("PROBE_TOKEN"),
                           secret_value("PROBE_OPERATOR_PASSWORD"), os.environ.get("PROBE_HOME_URL", ""))
    print(json.dumps({"application": APP, "role": configuration.role, "listening": 8080}), flush=True)
    make_server(configuration).serve_forever()
