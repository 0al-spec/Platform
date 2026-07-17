"""Authenticated HTTP service for private, durable SpecSpace state."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
import urllib.parse

if __package__:
    from scripts import specspace_state_store as contracts
else:  # Direct execution adds scripts/ to sys.path.
    import specspace_state_store as contracts


MAX_REQUEST_BYTES = 2 * 1024 * 1024
MUTATION_FIELDS = frozenset(
    {
        "workspace_id",
        "record_key",
        "expected_revision",
        "idempotency_key",
        "lifecycle_state",
        "content",
        "content_sha256",
    }
)
DELETE_FIELDS = frozenset(
    {"workspace_id", "record_key", "expected_revision", "idempotency_key"}
)


class StateServiceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
        code: str = "state_request_invalid",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def authority_boundary() -> dict[str, bool]:
    return {
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


class SpecSpaceStateService:
    def __init__(
        self,
        *,
        store_factory: Callable[[], contracts.SpecSpaceStateStore],
        adapter: str,
        mirror_root: Path,
        now_iso: Callable[[], str],
    ) -> None:
        self.store_factory = store_factory
        self.adapter = adapter
        self.mirror_root = mirror_root.resolve()
        self.now_iso = now_iso
        self.mirror_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _store(self) -> contracts.SpecSpaceStateStore:
        return self.store_factory()

    def _mirror_path(self, workspace_id: str, record_key: str) -> Path:
        workspace_id = contracts.validate_workspace_id(workspace_id)
        record_key = contracts.validate_record_key(
            record_key,
            workspace_id=workspace_id,
        )
        path = (self.mirror_root / workspace_id / record_key).resolve()
        try:
            path.relative_to(self.mirror_root)
        except ValueError as exc:  # pragma: no cover - validated path invariant
            raise StateServiceError(
                "state mirror path escaped its configured root",
                status=HTTPStatus.CONFLICT,
                code="state_mirror_path_invalid",
            ) from exc
        return path

    def _materialize(self, record: dict[str, Any]) -> None:
        path = self._mirror_path(record["workspace_id"], record["record_key"])
        if record["lifecycle_state"] == "deleted":
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        content = record.get("content")
        if not isinstance(content, dict):
            raise StateServiceError(
                "stored state content is unavailable",
                status=HTTPStatus.CONFLICT,
                code="state_content_unavailable",
            )
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = (
            json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def health(self) -> dict[str, Any]:
        store: contracts.SpecSpaceStateStore | None = None
        try:
            store = self._store()
            ready = store.health()
            mirror_ready = self.mirror_root.is_dir() and os.access(
                self.mirror_root, os.W_OK
            )
        except Exception:
            ready = False
            mirror_ready = False
        finally:
            if store is not None:
                store.close()
        ok = ready and mirror_ready
        return {
            "artifact_kind": "platform_specspace_state_service_health",
            "schema_version": 1,
            "contract_ref": contracts.SERVICE_CONTRACT_REF,
            "ok": ok,
            "status": "ready" if ok else "state_backend_unavailable",
            "adapter": self.adapter,
            "record_contract_ref": contracts.CONTRACT_REF,
            "workspace_scoped": True,
            "cas_required": True,
            "mirror_ready": mirror_ready,
            "authority_boundary": authority_boundary(),
        }

    def get_record(
        self,
        *,
        workspace_id: str,
        record_key: str,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        store = self._store()
        try:
            record = store.get(
                workspace_id,
                record_key,
                include_deleted=include_deleted,
            )
        finally:
            store.close()
        if record is None:
            raise StateServiceError(
                "state record was not found",
                status=HTTPStatus.NOT_FOUND,
                code="state_record_not_found",
            )
        return {
            "artifact_kind": "platform_specspace_state_record_report",
            "schema_version": 1,
            "ok": True,
            "record": contracts.record_projection(record, include_content=True),
            "authority_boundary": authority_boundary(),
        }

    def list_records(
        self,
        *,
        workspace_id: str | None,
        record_key: str | None,
        include_deleted: bool,
        include_content: bool,
    ) -> dict[str, Any]:
        store = self._store()
        try:
            records = store.list_records(
                workspace_id=workspace_id,
                record_key=record_key,
                include_deleted=include_deleted,
            )
        finally:
            store.close()
        if len(records) > 1000:
            raise StateServiceError(
                "state record query exceeds the bounded result limit",
                status=HTTPStatus.CONFLICT,
                code="state_record_limit_exceeded",
            )
        return {
            "artifact_kind": "platform_specspace_state_record_collection",
            "schema_version": 1,
            "ok": True,
            "records": [
                contracts.record_projection(
                    record,
                    include_content=include_content,
                )
                for record in records
            ],
            "summary": {
                "record_count": len(records),
                "content_included": include_content,
            },
            "authority_boundary": authority_boundary(),
        }

    def history(
        self,
        *,
        workspace_id: str,
        record_key: str,
        limit: int,
    ) -> dict[str, Any]:
        store = self._store()
        try:
            history = store.history(workspace_id, record_key, limit=limit)
        finally:
            store.close()
        return {
            "artifact_kind": "platform_specspace_state_history_report",
            "schema_version": 1,
            "ok": True,
            "workspace_id": workspace_id,
            "record_key": record_key,
            "versions": [
                {
                    "contract_ref": contracts.CONTRACT_REF,
                    "workspace_id": item["workspace_id"],
                    "record_key": item["record_key"],
                    "revision": int(item["revision"]),
                    "content_sha256": item["content_sha256"],
                    "lifecycle_state": item["lifecycle_state"],
                    "idempotency_key": item["idempotency_key"],
                    "recorded_at": item["recorded_at"],
                }
                for item in history
            ],
            "summary": {"version_count": len(history)},
            "authority_boundary": authority_boundary(),
        }

    @staticmethod
    def _mutation(payload: dict[str, Any]) -> contracts.StateMutation:
        unknown = sorted(set(payload) - MUTATION_FIELDS)
        if unknown:
            raise StateServiceError(
                "state mutation contains fields outside the contract"
            )
        required = MUTATION_FIELDS - {"content_sha256"}
        if any(field not in payload for field in required):
            raise StateServiceError("state mutation is missing required fields")
        return contracts.StateMutation(
            workspace_id=payload["workspace_id"],
            record_key=payload["record_key"],
            expected_revision=payload["expected_revision"],
            idempotency_key=payload["idempotency_key"],
            lifecycle_state=payload["lifecycle_state"],
            content=payload["content"],
            supplied_content_sha256=payload.get("content_sha256"),
        )

    def mutate(self, payload: dict[str, Any]) -> dict[str, Any]:
        mutation = self._mutation(payload)
        store = self._store()
        try:
            record = store.mutate(mutation, now_iso=self.now_iso())
        except contracts.StateConflictError as exc:
            raise StateServiceError(
                str(exc),
                status=HTTPStatus.CONFLICT,
                code="state_revision_conflict",
            ) from exc
        finally:
            store.close()
        self._materialize(record)
        return {
            "artifact_kind": "platform_specspace_state_mutation_report",
            "schema_version": 1,
            "ok": True,
            "record": contracts.record_projection(record, include_content=False),
            "summary": {
                "status": "specspace_state_record_persisted",
                "workspace_id": record["workspace_id"],
                "record_key": record["record_key"],
                "revision": int(record["revision"]),
                "lifecycle_state": record["lifecycle_state"],
            },
            "authority_boundary": authority_boundary(),
        }

    def delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(payload) - DELETE_FIELDS)
        if unknown or any(field not in payload for field in DELETE_FIELDS):
            raise StateServiceError("state delete request is invalid")
        return self.mutate(
            {
                **payload,
                "lifecycle_state": "deleted",
                "content": {},
            }
        )

    def export(self) -> dict[str, Any]:
        store = self._store()
        try:
            records = store.list_records(include_deleted=True)
        finally:
            store.close()
        return {
            "artifact_kind": "platform_specspace_state_export",
            "schema_version": 1,
            "contract_ref": contracts.EXPORT_CONTRACT_REF,
            "generated_at": self.now_iso(),
            "records": [
                contracts.record_projection(record, include_content=True)
                for record in records
            ],
            "summary": {
                "record_count": len(records),
                "workspace_count": len(
                    {record["workspace_id"] for record in records}
                ),
            },
            "authority_boundary": authority_boundary(),
        }


class SpecSpaceStateHTTPServer(ThreadingHTTPServer):
    service: SpecSpaceStateService
    auth_token: str


class SpecSpaceStateHandler(BaseHTTPRequestHandler):
    server: SpecSpaceStateHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.auth_token}"
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, error: StateServiceError) -> None:
        self._write_json(
            error.status,
            {
                "artifact_kind": "platform_specspace_state_service_error",
                "schema_version": 1,
                "ok": False,
                "error": error.code,
                "message": str(error),
                "authority_boundary": authority_boundary(),
            },
        )

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise StateServiceError("request size is invalid") from exc
        if length < 2 or length > MAX_REQUEST_BYTES:
            raise StateServiceError(
                "request size is invalid",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                code="state_request_size_invalid",
            )
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise StateServiceError(
                "request body is not valid JSON",
                code="state_request_json_invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise StateServiceError("request body must be an object")
        return payload

    @staticmethod
    def _bool(query: dict[str, list[str]], name: str) -> bool:
        return query.get(name, ["false"])[0].lower() == "true"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/v1/health":
            report = self.server.service.health()
            self._write_json(
                HTTPStatus.OK if report["ok"] else HTTPStatus.SERVICE_UNAVAILABLE,
                report,
            )
            return
        if not self._authorized():
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "unauthorized"},
            )
            return
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/v1/specspace-state/record":
                self._write_json(
                    HTTPStatus.OK,
                    self.server.service.get_record(
                        workspace_id=query.get("workspace_id", [""])[0],
                        record_key=query.get("record_key", [""])[0],
                        include_deleted=self._bool(query, "include_deleted"),
                    ),
                )
                return
            if parsed.path == "/v1/specspace-state/records":
                self._write_json(
                    HTTPStatus.OK,
                    self.server.service.list_records(
                        workspace_id=query.get("workspace_id", [None])[0],
                        record_key=query.get("record_key", [None])[0],
                        include_deleted=self._bool(query, "include_deleted"),
                        include_content=self._bool(query, "include_content"),
                    ),
                )
                return
            if parsed.path == "/v1/specspace-state/history":
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError:
                    limit = 100
                self._write_json(
                    HTTPStatus.OK,
                    self.server.service.history(
                        workspace_id=query.get("workspace_id", [""])[0],
                        record_key=query.get("record_key", [""])[0],
                        limit=limit,
                    ),
                )
                return
            if parsed.path == "/v1/specspace-state/export":
                self._write_json(HTTPStatus.OK, self.server.service.export())
                return
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "not_found"},
            )
        except (StateServiceError, contracts.StateStoreError) as exc:
            error = (
                exc
                if isinstance(exc, StateServiceError)
                else StateServiceError(str(exc))
            )
            self._error(error)

    def do_PUT(self) -> None:
        if not self._authorized():
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "unauthorized"},
            )
            return
        if self.path != "/v1/specspace-state/record":
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "not_found"},
            )
            return
        try:
            report = self.server.service.mutate(self._body())
        except (StateServiceError, contracts.StateStoreError) as exc:
            error = (
                exc
                if isinstance(exc, StateServiceError)
                else StateServiceError(str(exc))
            )
            self._error(error)
            return
        self._write_json(HTTPStatus.OK, report)

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._write_json(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": "unauthorized"},
            )
            return
        if self.path != "/v1/specspace-state/record":
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "not_found"},
            )
            return
        try:
            report = self.server.service.delete(self._body())
        except (StateServiceError, contracts.StateStoreError) as exc:
            error = (
                exc
                if isinstance(exc, StateServiceError)
                else StateServiceError(str(exc))
            )
            self._error(error)
            return
        self._write_json(HTTPStatus.OK, report)


def create_server(
    *,
    host: str,
    port: int,
    service: SpecSpaceStateService,
    auth_token: str,
) -> SpecSpaceStateHTTPServer:
    if len(auth_token) < 32:
        raise StateServiceError(
            "SpecSpace state service token must contain at least 32 characters"
        )
    server = SpecSpaceStateHTTPServer((host, port), SpecSpaceStateHandler)
    server.service = service
    server.auth_token = auth_token
    return server
