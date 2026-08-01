"""Narrow authenticated client for Platform-owned SpecSpace state claims."""

from __future__ import annotations

import json
import re
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

try:
    from scripts import specspace_state_store as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import specspace_state_store as contracts


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TRUSTED_AUTHORITY_BOUNDARY = {
    "state_service_is_execution_authority": False,
    "executes_managed_operations": False,
    "executes_platform_wrappers": False,
    "mutates_specgraph_artifacts": False,
    "mutates_canonical_specs": False,
    "writes_ontology_packages": False,
    "creates_git_commits": False,
    "opens_pull_requests": False,
    "publishes_read_models": False,
    "persists_private_specspace_state": True,
}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class SpecSpaceStateClientError(RuntimeError):
    """The internal state service was unavailable or returned untrusted data."""


class SpecSpaceStateClientConflict(SpecSpaceStateClientError):
    """The confirmation was stale, consumed by another request, or invalid."""


def _trusted_boundary(payload: dict[str, Any]) -> bool:
    return payload.get("authority_boundary") == TRUSTED_AUTHORITY_BOUNDARY


class SpecSpaceStateClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 5.0,
        allow_insecure_private_http: bool = False,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise SpecSpaceStateClientError("SpecSpace state service URL is invalid")
        if (
            parsed.scheme == "http"
            and parsed.hostname not in LOOPBACK_HOSTS
            and not allow_insecure_private_http
        ):
            raise SpecSpaceStateClientError(
                "plain HTTP SpecSpace state service requires an explicit "
                "private-network opt-in"
            )
        if len(token) < 32:
            raise SpecSpaceStateClientError("SpecSpace state service token is invalid")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise SpecSpaceStateClientError("SpecSpace state service timeout is invalid")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        encoded: bytes | None = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    self.base_url + path,
                    data=encoded,
                    headers=headers,
                    method=method,
                ),
                timeout=self.timeout_seconds,
            ) as response:
                response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = None
            try:
                error_payload = json.loads(exc.read(MAX_RESPONSE_BYTES))
                if isinstance(error_payload, dict):
                    code = error_payload.get("error")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            error = str(code or f"SpecSpace state service HTTP {exc.code}")
            if exc.code == 409:
                raise SpecSpaceStateClientConflict(error) from exc
            raise SpecSpaceStateClientError(error) from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise SpecSpaceStateClientError(
                "SpecSpace state service is unavailable"
            ) from exc
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise SpecSpaceStateClientError("SpecSpace state response is too large")
        try:
            response_payload = json.loads(response_bytes)
        except json.JSONDecodeError as exc:
            raise SpecSpaceStateClientError(
                "SpecSpace state service returned invalid JSON"
            ) from exc
        if not isinstance(response_payload, dict) or not _trusted_boundary(
            response_payload
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace state service returned an untrusted response"
            )
        return response_payload

    @staticmethod
    def _record(
        value: Any,
        *,
        workspace_id: str,
        record_key: str,
        include_content: bool,
    ) -> dict[str, Any]:
        record = value if isinstance(value, dict) else {}
        if (
            record.get("contract_ref") != contracts.CONTRACT_REF
            or record.get("workspace_id") != workspace_id
            or record.get("record_key") != record_key
            or not isinstance(record.get("revision"), int)
            or isinstance(record.get("revision"), bool)
            or record.get("revision") < 1
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(record.get("content_sha256") or "")
            )
            or record.get("lifecycle_state")
            not in {"active", "consumed", "superseded"}
            or (include_content and not isinstance(record.get("content"), dict))
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace state record failed contract validation"
            )
        if include_content and contracts.content_sha256(record["content"]) != record.get(
            "content_sha256"
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace state record content digest is invalid"
            )
        return record

    def get_record(self, *, workspace_id: str, record_key: str) -> dict[str, Any]:
        workspace_id = contracts.validate_workspace_id(workspace_id)
        record_key = contracts.validate_record_key(
            record_key,
            workspace_id=workspace_id,
        )
        query = urllib.parse.urlencode(
            {"workspace_id": workspace_id, "record_key": record_key}
        )
        payload = self._request(f"/v1/specspace-state/confirmation?{query}")
        if (
            payload.get("artifact_kind")
            != "platform_specspace_state_record_report"
            or payload.get("ok") is not True
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace state record report is invalid"
            )
        return self._record(
            payload.get("record"),
            workspace_id=workspace_id,
            record_key=record_key,
            include_content=True,
        )

    def consume_confirmation(
        self,
        *,
        workspace_id: str,
        record_key: str,
        expected_revision: int,
        expected_content_sha256: str,
        request_identity_sha256: str,
    ) -> dict[str, Any]:
        payload = self._request(
            "/v1/specspace-state/confirmation/consume",
            method="POST",
            payload={
                "workspace_id": workspace_id,
                "record_key": record_key,
                "expected_revision": expected_revision,
                "expected_content_sha256": expected_content_sha256,
                "operation_id": "promotion_review_execute",
                "request_identity_sha256": request_identity_sha256,
            },
        )
        if (
            payload.get("artifact_kind")
            != "platform_specspace_state_confirmation_consumption_report"
            or payload.get("ok") is not True
            or payload.get("request_identity_sha256") != request_identity_sha256
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace confirmation consumption report is invalid"
            )
        record = self._record(
            payload.get("record"),
            workspace_id=workspace_id,
            record_key=record_key,
            include_content=False,
        )
        if (
            record.get("lifecycle_state") != "consumed"
            or record.get("content_sha256") != expected_content_sha256
        ):
            raise SpecSpaceStateClientError(
                "SpecSpace confirmation was not consumed for this request"
            )
        return record
