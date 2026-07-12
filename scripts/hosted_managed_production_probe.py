"""Probe a deployed TLS-fronted hosted managed-operation runtime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Callable
from urllib.parse import urlsplit
import urllib.request


EXPECTED_SERVICES = {
    "managed-operation-postgres",
    "managed-operation-service",
    "managed-operation-worker",
    "managed-operation-ingress",
}
READ_ONLY_CANARY_OPERATION = "review_status_execute"


class ProductionProbeError(RuntimeError):
    """The deployed runtime did not provide trustworthy health evidence."""


def _load_json_response(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionProbeError("hosted HTTPS health endpoint is unavailable") from exc
    if not isinstance(payload, dict):
        raise ProductionProbeError("hosted HTTPS health response must be an object")
    return payload


def _compose_rows(output: str) -> list[dict[str, Any]]:
    stripped = output.strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in stripped.splitlines()]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ProductionProbeError("docker compose ps returned an invalid payload")
    return payload


def _run(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ProductionProbeError("docker compose health inspection failed")
    return completed.stdout


def run_probe(
    *,
    service_url: str,
    compose_file: Path,
    project_name: str,
    timeout_seconds: float = 10.0,
    max_heartbeat_age_seconds: float = 30.0,
    now: datetime | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    fetch_health: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parsed = urlsplit(service_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ProductionProbeError("production probe requires a clean HTTPS service URL")
    if not compose_file.is_absolute():
        raise ProductionProbeError("production Compose path must be absolute")
    health_url = f"{service_url.rstrip('/')}/v1/health"
    health = (
        fetch_health(health_url)
        if fetch_health is not None
        else _load_json_response(health_url, timeout=timeout_seconds)
    )
    ps_output = _run(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "--file",
            str(compose_file),
            "ps",
            "--format",
            "json",
        ],
        runner=runner,
    )
    rows = _compose_rows(ps_output)
    service_states: dict[str, dict[str, str]] = {}
    for row in rows:
        service = row.get("Service") or row.get("service")
        if not isinstance(service, str):
            continue
        service_states[service] = {
            "state": str(row.get("State") or row.get("state") or "unknown").lower(),
            "health": str(row.get("Health") or row.get("health") or "unknown").lower(),
        }
    heartbeat_output = _run(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "--file",
            str(compose_file),
            "exec",
            "-T",
            "managed-operation-worker",
            "cat",
            "/tmp/managed-operation-worker-health.json",
        ],
        runner=runner,
    )
    try:
        heartbeat = json.loads(heartbeat_output)
    except json.JSONDecodeError as exc:
        raise ProductionProbeError("worker heartbeat is invalid") from exc
    if not isinstance(heartbeat, dict):
        raise ProductionProbeError("worker heartbeat must be an object")

    diagnostics: list[str] = []
    if health.get("ok") is not True or health.get("adapter") != "postgresql":
        diagnostics.append("service_health_not_postgresql_ready")
    enabled = health.get("enabled_operation_ids")
    if enabled != [READ_ONLY_CANARY_OPERATION]:
        diagnostics.append("service_allowlist_not_read_only_canary")
    if set(service_states) != EXPECTED_SERVICES:
        diagnostics.append("compose_service_set_mismatch")
    for service in sorted(EXPECTED_SERVICES):
        state = service_states.get(service, {})
        if state.get("state") != "running" or state.get("health") != "healthy":
            diagnostics.append(f"{service}_not_healthy")
    if heartbeat.get("ok") is not True or heartbeat.get("adapter") != "postgresql":
        diagnostics.append("worker_heartbeat_not_postgresql_ready")
    generated_at = heartbeat.get("generated_at")
    heartbeat_age: float | None = None
    if isinstance(generated_at, str):
        try:
            timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            current = now or datetime.now(timezone.utc)
            heartbeat_age = max(0.0, (current - timestamp).total_seconds())
        except ValueError:
            pass
    if heartbeat_age is None or heartbeat_age > max_heartbeat_age_seconds:
        diagnostics.append("worker_heartbeat_stale")

    diagnostics = sorted(set(diagnostics))
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    origin = f"{parsed.scheme}://{host}"
    if parsed.port is not None:
        origin = f"{origin}:{parsed.port}"
    return {
        "artifact_kind": "platform_hosted_managed_production_probe_report",
        "contract_ref": "platform.hosted-managed.production-probe.v1",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "ok": not diagnostics,
        "service": {
            "origin": origin,
            "adapter": health.get("adapter"),
            "enabled_operation_ids": enabled if isinstance(enabled, list) else [],
        },
        "worker": {
            "adapter": heartbeat.get("adapter"),
            "heartbeat_sequence": heartbeat.get("heartbeat_sequence"),
            "heartbeat_age_seconds": heartbeat_age,
            "last_cycle_status": heartbeat.get("last_cycle_status"),
        },
        "services": service_states,
        "summary": {
            "status": "healthy" if not diagnostics else "unhealthy",
            "healthy_service_count": sum(
                value.get("state") == "running" and value.get("health") == "healthy"
                for value in service_states.values()
            ),
            "expected_service_count": len(EXPECTED_SERVICES),
            "read_only_allowlist": enabled == [READ_ONLY_CANARY_OPERATION],
        },
        "diagnostics": diagnostics,
        "privacy_boundary": {
            "public_safe": True,
            "includes_secret_values": False,
            "includes_local_paths": False,
        },
        "authority_boundary": {
            "may_enqueue_operations": False,
            "may_execute_platform": False,
            "may_mutate_specs": False,
            "may_create_git_review": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-url", required=True)
    parser.add_argument(
        "--compose-file",
        default=str(
            Path(__file__).resolve().parents[1]
            / "docker-compose.hosted-managed-production.example.yml"
        ),
    )
    parser.add_argument("--project-name", default="platform-managed-production")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-heartbeat-age", type=float, default=30.0)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        report = run_probe(
            service_url=args.service_url,
            compose_file=Path(args.compose_file).resolve(),
            project_name=args.project_name,
            timeout_seconds=args.timeout,
            max_heartbeat_age_seconds=args.max_heartbeat_age,
        )
    except ProductionProbeError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_production_probe_report",
            "ok": False,
            "summary": {"status": "unhealthy"},
            "diagnostics": [str(exc)],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
