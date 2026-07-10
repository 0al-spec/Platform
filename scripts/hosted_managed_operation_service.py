"""Authenticated HTTP enqueue/status boundary for hosted managed operations."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
from typing import Any, Callable
import urllib.parse

try:
    from scripts import hosted_managed_operation_executor as executor_module
    from scripts import hosted_managed_operation_queue as queue_module
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operation_executor as executor_module
    import hosted_managed_operation_queue as queue_module
    import hosted_managed_operations as contracts


MAX_REQUEST_BYTES = 64 * 1024
ENQUEUE_FIELDS = frozenset(
    {
        "operation_id",
        "workspace_id",
        "workspace_binding_ref",
        "input_refs",
        "operator_ref",
        "confirmation_ref",
    }
)


class HostedServiceError(ValueError):
    def __init__(self, message: str, *, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


class HostedManagedOperationService:
    def __init__(
        self,
        *,
        database_path: Path | None = None,
        queue_factory: Callable[[], queue_module.ManagedOperationQueue] | None = None,
        adapter: str = "sqlite",
        resolver: executor_module.FilesystemManagedOperationResolver,
        now_epoch: Callable[[], float],
        now_iso: Callable[[], str],
    ) -> None:
        if queue_factory is None and database_path is None:
            raise HostedServiceError("hosted service queue storage is not configured")
        self.database_path = database_path.resolve() if database_path is not None else None
        self.queue_factory = queue_factory or (
            lambda: queue_module.SQLiteManagedOperationQueue(self.database_path)
        )
        self.adapter = adapter
        self.resolver = resolver
        self.now_epoch = now_epoch
        self.now_iso = now_iso

    def _queue(self) -> queue_module.ManagedOperationQueue:
        return self.queue_factory()

    def health(self) -> dict[str, Any]:
        queue: queue_module.ManagedOperationQueue | None = None
        try:
            queue = self._queue()
            ready = queue.health()
        except Exception:
            ready = False
        finally:
            if queue is not None:
                queue.close()
        return {
            "artifact_kind": "platform_hosted_managed_operation_service_health",
            "ok": ready,
            "status": "ready" if ready else "queue_unavailable",
            "contract_ref": contracts.REQUEST_CONTRACT_REF,
            "registry_contract_ref": contracts.REGISTRY_CONTRACT_REF,
            "operation_count": len(contracts.MANAGED_OPERATIONS),
            "adapter": self.adapter,
        }

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(payload) - ENQUEUE_FIELDS)
        if unknown:
            raise HostedServiceError(
                "enqueue payload contains fields outside the hosted service contract"
            )
        operation_id = payload.get("operation_id")
        definition = contracts.operation_by_id(
            operation_id if isinstance(operation_id, str) else ""
        )
        if definition is None:
            raise HostedServiceError("operation_id is not allowlisted")
        workspace_id = payload.get("workspace_id")
        if not isinstance(workspace_id, str) or not contracts.WORKSPACE_ID_RE.fullmatch(
            workspace_id
        ):
            raise HostedServiceError("workspace_id is invalid")
        binding_ref = payload.get("workspace_binding_ref")
        if not isinstance(binding_ref, str):
            raise HostedServiceError("workspace_binding_ref is required")
        try:
            binding_path, binding = self.resolver.load_binding_source(
                binding_ref,
                workspace_id=workspace_id,
            )
        except executor_module.ExecutorContractError as exc:
            raise HostedServiceError(str(exc), status=HTTPStatus.CONFLICT) from exc
        binding_digest, _, _, _ = contracts.digest_path(binding_path)

        input_refs = payload.get("input_refs")
        if not isinstance(input_refs, list) or any(
            not isinstance(item, str) for item in input_refs
        ):
            raise HostedServiceError("input_refs must be an array of logical refs")
        if len(input_refs) != len(set(input_refs)):
            raise HostedServiceError("input_refs must not contain duplicates")
        input_paths: dict[str, Path] = {}
        try:
            for logical_ref in input_refs:
                input_paths[logical_ref] = self.resolver.resolve_logical_ref(
                    logical_ref,
                    workspace_id,
                )
        except executor_module.ExecutorContractError as exc:
            raise HostedServiceError(str(exc)) from exc

        confirmation_ref = payload.get("confirmation_ref")
        confirmation_sha256: str | None = None
        if confirmation_ref is not None:
            if not isinstance(confirmation_ref, str):
                raise HostedServiceError("confirmation_ref must be a logical ref")
            try:
                confirmation_path = self.resolver.resolve_logical_ref(
                    confirmation_ref,
                    workspace_id,
                )
                confirmation_sha256, _, _, _ = contracts.digest_path(
                    confirmation_path
                )
            except (executor_module.ExecutorContractError, OSError, ValueError) as exc:
                raise HostedServiceError(
                    "confirmation evidence is missing or unreadable"
                ) from exc

        request = contracts.build_request(
            operation_id=definition.operation_id,
            workspace_binding=binding,
            workspace_binding_ref=binding_ref,
            workspace_binding_source_sha256=binding_digest,
            inputs=input_paths,
            generated_at=self.now_iso(),
            operator_ref=(
                payload.get("operator_ref")
                if isinstance(payload.get("operator_ref"), str)
                else None
            ),
            confirmation_ref=confirmation_ref,
            confirmation_sha256=confirmation_sha256,
        )
        diagnostics = contracts.request_diagnostics(request)
        if diagnostics:
            raise HostedServiceError(
                "; ".join(diagnostics),
                status=HTTPStatus.CONFLICT,
            )
        queue = self._queue()
        try:
            receipt = queue.enqueue(
                request,
                now_epoch=self.now_epoch(),
                now_iso=self.now_iso(),
            )
        except queue_module.QueueContractError as exc:
            raise HostedServiceError(str(exc), status=HTTPStatus.CONFLICT) from exc
        finally:
            queue.close()
        return {
            "artifact_kind": "platform_hosted_managed_operation_enqueue_report",
            "schema_version": 1,
            "ok": True,
            "request": request,
            "receipt": receipt,
            "summary": {
                "status": "hosted_managed_operation_queued",
                "request_id": request["request_id"],
                "operation_id": definition.operation_id,
                "workspace_id": workspace_id,
            },
            "authority_boundary": {
                "enqueue_is_execution_authority": False,
                "queue_status_is_lifecycle_evidence": False,
                "platform_output_reports_are_authoritative": True,
            },
        }

    def status(self, request_id: str, *, include_events: bool = False) -> dict[str, Any]:
        if not isinstance(request_id, str) or not request_id.startswith(
            "managed-operation://"
        ):
            raise HostedServiceError("request_id is invalid")
        queue = self._queue()
        try:
            job = queue.get(request_id)
            events = queue.events(request_id) if include_events and job else []
        finally:
            queue.close()
        if job is None:
            raise HostedServiceError(
                "managed operation request was not found",
                status=HTTPStatus.NOT_FOUND,
            )
        lease_active = job.get("status") in {"leased", "running"}
        projection = {
            key: value
            for key, value in job.items()
            if key not in {"lease_owner", "lease_expires_at"}
        }
        projection["lease_active"] = lease_active
        return {
            "artifact_kind": "platform_hosted_managed_operation_status_report",
            "schema_version": 1,
            "ok": True,
            "job": projection,
            "events": events,
            "summary": {
                "status": job["status"],
                "terminal": job["status"] in queue_module.TERMINAL_STATUSES,
            },
            "authority_boundary": {
                "status_is_execution_authority": False,
                "queue_status_is_lifecycle_evidence": False,
                "platform_output_reports_are_authoritative": True,
            },
        }


class HostedManagedOperationHTTPServer(ThreadingHTTPServer):
    service: HostedManagedOperationService
    auth_token: str


class HostedManagedOperationHandler(BaseHTTPRequestHandler):
    server: HostedManagedOperationHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.auth_token}"
        return hmac.compare_digest(authorization, expected)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, error: HostedServiceError) -> None:
        self._write_json(
            error.status,
            {
                "artifact_kind": "platform_hosted_managed_operation_service_error",
                "ok": False,
                "error": str(error),
                "authority_boundary": {
                    "executes_managed_operations": False,
                    "exposes_secrets": False,
                },
            },
        )

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
            self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if parsed.path != "/v1/managed-operations/status":
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        query = urllib.parse.parse_qs(parsed.query)
        request_id = query.get("request_id", [""])[0]
        include_events = query.get("include_events", ["false"])[0] == "true"
        try:
            self._write_json(
                HTTPStatus.OK,
                self.server.service.status(
                    request_id,
                    include_events=include_events,
                ),
            )
        except HostedServiceError as exc:
            self._error(exc)

    def do_POST(self) -> None:
        if not self._authorized():
            self._write_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if self.path != "/v1/managed-operations":
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length < 1 or content_length > MAX_REQUEST_BYTES:
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "request_size_invalid"},
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "object_required"})
            return
        try:
            report = self.server.service.enqueue(payload)
        except HostedServiceError as exc:
            self._error(exc)
            return
        self._write_json(HTTPStatus.ACCEPTED, report)


def create_server(
    *,
    host: str,
    port: int,
    service: HostedManagedOperationService,
    auth_token: str,
) -> HostedManagedOperationHTTPServer:
    if len(auth_token) < 32:
        raise HostedServiceError("hosted service auth token must contain at least 32 characters")
    server = HostedManagedOperationHTTPServer(
        (host, port), HostedManagedOperationHandler
    )
    server.service = service
    server.auth_token = auth_token
    return server
