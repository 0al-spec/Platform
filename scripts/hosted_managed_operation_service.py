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
    from scripts import hosted_managed_promotion_review as promotion_review
    from scripts import specspace_state_client as state_client_module
    from scripts import specspace_state_store as state_contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operation_executor as executor_module
    import hosted_managed_operation_queue as queue_module
    import hosted_managed_operations as contracts
    import hosted_managed_promotion_review as promotion_review
    import specspace_state_client as state_client_module
    import specspace_state_store as state_contracts


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
        allowed_operation_ids: frozenset[str] | None = None,
        state_client: state_client_module.SpecSpaceStateClient | None = None,
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
        self.allowed_operation_ids = contracts.normalize_operation_allowlist(
            allowed_operation_ids
        )
        self.state_client = state_client

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
            "operation_count": len(self.allowed_operation_ids),
            "enabled_operation_ids": sorted(self.allowed_operation_ids),
            "adapter": self.adapter,
        }

    @staticmethod
    def _enqueue_report(
        *,
        request: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        operation = request.get("operation")
        operation = operation if isinstance(operation, dict) else {}
        workspace = request.get("workspace")
        workspace = workspace if isinstance(workspace, dict) else {}
        return {
            "artifact_kind": "platform_hosted_managed_operation_enqueue_report",
            "schema_version": 1,
            "ok": True,
            "request": request,
            "receipt": receipt,
            "summary": {
                "status": "hosted_managed_operation_queued",
                "request_id": request["request_id"],
                "operation_id": operation.get("operation_id"),
                "workspace_id": workspace.get("workspace_id"),
            },
            "authority_boundary": {
                "enqueue_is_execution_authority": False,
                "queue_status_is_lifecycle_evidence": False,
                "platform_output_reports_are_authoritative": True,
            },
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
        if definition.operation_id not in self.allowed_operation_ids:
            raise HostedServiceError(
                "operation_id is disabled by the hosted deployment allowlist",
                status=HTTPStatus.CONFLICT,
            )
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
        confirmation_revision: int | None = None
        confirmation_lifecycle_state: str | None = None
        confirmation_record_key: str | None = None
        confirmation_record: dict[str, Any] | None = None
        confirmation_validation_time: str | None = None
        generated_at = self.now_iso()
        operator_ref = (
            payload.get("operator_ref")
            if isinstance(payload.get("operator_ref"), str)
            else None
        )
        if definition.requires_explicit_confirmation:
            if not isinstance(confirmation_ref, str):
                raise HostedServiceError("confirmation_ref is required")
            if not confirmation_ref.startswith("specspace-state://"):
                raise HostedServiceError("confirmation_ref must use SpecSpace state")
            if self.state_client is None:
                raise HostedServiceError(
                    "semantic confirmation state service is not configured",
                    status=HTTPStatus.CONFLICT,
                )
            confirmation_record_key = confirmation_ref.removeprefix(
                "specspace-state://"
            )
            try:
                confirmation_path = self.resolver.resolve_logical_ref(
                    confirmation_ref,
                    workspace_id,
                )
                mirror_content = json.loads(
                    confirmation_path.read_text(encoding="utf-8")
                )
                if not isinstance(mirror_content, dict):
                    raise ValueError("confirmation mirror must be an object")
                mirror_sha256 = state_contracts.content_sha256(mirror_content)
                confirmation_record = self.state_client.get_record(
                    workspace_id=workspace_id,
                    record_key=confirmation_record_key,
                )
            except (
                executor_module.ExecutorContractError,
                json.JSONDecodeError,
                OSError,
                ValueError,
                state_client_module.SpecSpaceStateClientError,
            ) as exc:
                raise HostedServiceError(
                    "confirmation evidence is missing or unreadable"
                ) from exc
            confirmation_sha256 = str(
                confirmation_record.get("content_sha256") or ""
            )
            if mirror_sha256 != confirmation_sha256:
                raise HostedServiceError(
                    "confirmation state mirror does not match durable state",
                    status=HTTPStatus.CONFLICT,
                )
            current_revision = confirmation_record.get("revision")
            current_lifecycle = confirmation_record.get("lifecycle_state")
            if (
                not isinstance(current_revision, int)
                or isinstance(current_revision, bool)
                or current_lifecycle not in {"active", "consumed"}
            ):
                raise HostedServiceError(
                    "confirmation state cannot be consumed",
                    status=HTTPStatus.CONFLICT,
                )
            confirmation_revision = current_revision + (
                1 if current_lifecycle == "active" else 0
            )
            confirmation_lifecycle_state = "consumed"
            confirmation_validation_time = generated_at
        elif confirmation_ref is not None:
            raise HostedServiceError(
                "operation does not accept confirmation evidence"
            )

        request = contracts.build_request(
            operation_id=definition.operation_id,
            workspace_binding=binding,
            workspace_binding_ref=binding_ref,
            workspace_binding_source_sha256=binding_digest,
            inputs=input_paths,
            generated_at=generated_at,
            operator_ref=operator_ref,
            confirmation_ref=confirmation_ref,
            confirmation_sha256=confirmation_sha256,
            confirmation_revision=confirmation_revision,
            confirmation_lifecycle_state=confirmation_lifecycle_state,
        )
        diagnostics = contracts.request_diagnostics(request)
        if diagnostics:
            raise HostedServiceError(
                "; ".join(diagnostics),
                status=HTTPStatus.CONFLICT,
            )

        queue = self._queue()
        try:
            if definition.requires_explicit_confirmation:
                assert self.state_client is not None
                assert confirmation_record is not None
                assert confirmation_record_key is not None
                expected_consumption_key = (
                    "promotion-review-consume:" + str(request["idempotency_key"])
                )
                current_lifecycle = confirmation_record.get("lifecycle_state")
                if (
                    current_lifecycle == "consumed"
                    and confirmation_record.get("idempotency_key")
                    != expected_consumption_key
                ):
                    raise HostedServiceError(
                        "confirmation was consumed by another request",
                        status=HTTPStatus.CONFLICT,
                    )
                existing = queue.get(str(request["request_id"]))
                if existing is not None:
                    stored_request = existing.get("request")
                    if (
                        current_lifecycle != "consumed"
                        or not isinstance(stored_request, dict)
                        or existing.get("idempotency_key")
                        != request.get("idempotency_key")
                        or existing.get("request_sha256")
                        != queue_module.canonical_sha256(stored_request)
                        or contracts.request_diagnostics(stored_request)
                    ):
                        raise HostedServiceError(
                            "queued promotion review does not match consumed confirmation",
                            status=HTTPStatus.CONFLICT,
                        )
                    receipt = existing.get("receipt")
                    if not isinstance(receipt, dict):
                        raise HostedServiceError(
                            "queued promotion review receipt is invalid",
                            status=HTTPStatus.CONFLICT,
                        )
                    return self._enqueue_report(
                        request=stored_request,
                        receipt=receipt,
                    )
                if current_lifecycle == "consumed":
                    raise HostedServiceError(
                        "consumed confirmation has no matching queue request; "
                        "promotion review reconciliation is required",
                        status=HTTPStatus.CONFLICT,
                    )

                expected_input_digests = {
                    logical_ref: contracts.digest_path(path)[0]
                    for logical_ref, path in input_paths.items()
                }
                try:
                    promotion_review.validate_confirmation(
                        payload=confirmation_record["content"],
                        expected_workspace_id=workspace_id,
                        expected_operator_ref=str(operator_ref or ""),
                        expected_confirmation_ref=str(confirmation_ref or ""),
                        expected_binding={
                            "binding_id": binding.get("binding_id"),
                            "binding_revision_sha256": binding.get(
                                "binding_revision_sha256"
                            ),
                            "source_sha256": binding_digest,
                        },
                        expected_input_digests=expected_input_digests,
                        now_iso=str(confirmation_validation_time or ""),
                        resolve_ref=lambda ref: self.resolver.resolve_logical_ref(
                            ref,
                            workspace_id,
                        ),
                    )
                except promotion_review.PromotionReviewConfirmationError as exc:
                    raise HostedServiceError(
                        str(exc),
                        status=HTTPStatus.CONFLICT,
                    ) from exc

                if current_lifecycle == "active":
                    try:
                        consumed = self.state_client.consume_confirmation(
                            workspace_id=workspace_id,
                            record_key=confirmation_record_key,
                            expected_revision=int(confirmation_record["revision"]),
                            expected_content_sha256=str(
                                confirmation_record["content_sha256"]
                            ),
                            request_identity_sha256=str(request["idempotency_key"]),
                        )
                    except state_client_module.SpecSpaceStateClientConflict as exc:
                        raise HostedServiceError(
                            "confirmation was already consumed by another request",
                            status=HTTPStatus.CONFLICT,
                        ) from exc
                    except state_client_module.SpecSpaceStateClientError as exc:
                        raise HostedServiceError(
                            "confirmation state service is unavailable",
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        ) from exc
                    if consumed.get("revision") != confirmation_revision:
                        raise HostedServiceError(
                            "confirmation consumed revision does not match the request",
                            status=HTTPStatus.CONFLICT,
                        )
            receipt = queue.enqueue(
                request,
                now_epoch=self.now_epoch(),
                now_iso=self.now_iso(),
            )
        except queue_module.QueueContractError as exc:
            raise HostedServiceError(str(exc), status=HTTPStatus.CONFLICT) from exc
        finally:
            queue.close()
        return self._enqueue_report(request=request, receipt=receipt)

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
            if key not in {"lease_owner", "lease_expires_at", "request"}
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
