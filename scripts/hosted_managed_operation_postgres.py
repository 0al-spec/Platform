"""PostgreSQL queue adapter for production hosted managed operations."""

from __future__ import annotations

import json
from typing import Any

try:
    from scripts import hosted_managed_operation_queue as queue_module
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operation_queue as queue_module
    import hosted_managed_operations as contracts


class PostgreSQLDependencyError(RuntimeError):
    pass


def _driver() -> tuple[Any, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise PostgreSQLDependencyError(
            "PostgreSQL managed-operation queues require psycopg[binary]>=3.2"
        ) from exc
    return psycopg, dict_row


class PostgreSQLManagedOperationQueue:
    """Multi-worker queue using row leases and explicit workspace locks."""

    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise queue_module.QueueContractError(
                "PostgreSQL queue URL must use postgresql:// or postgres://"
            )
        psycopg, dict_row = _driver()
        self.connection = psycopg.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
        )
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def health(self) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            row = cursor.fetchone()
        return row is not None and row["ready"] == 1

    def initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS managed_operation_jobs (
                request_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                operation_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                available_at DOUBLE PRECISION NOT NULL,
                lease_owner TEXT,
                lease_expires_at DOUBLE PRECISION,
                receipt_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS managed_operation_jobs_ready
              ON managed_operation_jobs(status, available_at, created_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS managed_operation_locks (
                lock_scope TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES managed_operation_jobs(request_id)
                  ON DELETE CASCADE,
                lease_owner TEXT NOT NULL,
                lease_expires_at DOUBLE PRECISION NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS managed_operation_events (
                event_id BIGSERIAL PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES managed_operation_jobs(request_id)
                  ON DELETE CASCADE,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                receipt_json TEXT NOT NULL
            )
            """,
        )
        with self.connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    @staticmethod
    def _loads(value: Any) -> dict[str, Any]:
        payload = json.loads(str(value))
        if not isinstance(payload, dict):
            raise queue_module.QueueContractError("queue JSON payload is not an object")
        return payload

    @staticmethod
    def _dumps(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def _record_event(
        self,
        cursor: Any,
        request_id: str,
        status: str,
        attempt: int,
        now_iso: str,
        receipt: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO managed_operation_events
              (request_id, status, attempt, recorded_at, receipt_json)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (request_id, status, attempt, now_iso, self._dumps(receipt)),
        )

    def enqueue(
        self,
        request: dict[str, Any],
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]:
        diagnostics = contracts.request_diagnostics(request)
        if diagnostics:
            raise queue_module.QueueContractError("; ".join(diagnostics))
        request_id = str(request["request_id"])
        idempotency_key = str(request["idempotency_key"])
        operation_id = str(request["operation"]["operation_id"])
        workspace_id = str(request["workspace"]["workspace_id"])
        receipt = contracts.build_receipt(
            request=request,
            status="queued",
            generated_at=now_iso,
            attempt=0,
        )
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO managed_operation_jobs (
                      request_id, idempotency_key, operation_id, workspace_id,
                      request_sha256, request_json, status, attempt, available_at,
                      receipt_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'queued', 0, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING request_id
                    """,
                    (
                        request_id,
                        idempotency_key,
                        operation_id,
                        workspace_id,
                        queue_module.canonical_sha256(request),
                        self._dumps(request),
                        now_epoch,
                        self._dumps(receipt),
                        now_iso,
                        now_iso,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is not None:
                    self._record_event(
                        cursor, request_id, "queued", 0, now_iso, receipt
                    )
                    return receipt
                cursor.execute(
                    """
                    SELECT request_id, idempotency_key, operation_id, workspace_id,
                           receipt_json
                    FROM managed_operation_jobs
                    WHERE request_id = %s OR idempotency_key = %s
                    FOR UPDATE
                    """,
                    (request_id, idempotency_key),
                )
                matches = cursor.fetchall()
                if len(matches) != 1:
                    raise queue_module.QueueContractError(
                        "managed operation request identity conflicts with queue state"
                    )
                existing = matches[0]
                if (
                    existing["request_id"] != request_id
                    or existing["idempotency_key"] != idempotency_key
                    or existing["operation_id"] != operation_id
                    or existing["workspace_id"] != workspace_id
                ):
                    raise queue_module.QueueContractError(
                        "idempotency key is already owned by another operation"
                    )
                return self._loads(existing["receipt_json"])

    def lease_next(
        self,
        *,
        worker_id: str,
        now_epoch: float,
        now_iso: str,
        lease_seconds: int,
    ) -> queue_module.LeasedOperation | None:
        if not worker_id or lease_seconds < 1:
            raise queue_module.QueueContractError(
                "worker id and positive lease duration are required"
            )
        lease_expires_at = now_epoch + lease_seconds
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM managed_operation_jobs
                    WHERE status = 'queued' AND available_at <= %s
                    ORDER BY created_at, request_id
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now_epoch,),
                )
                for row in cursor.fetchall():
                    request = self._loads(row["request_json"])
                    scopes = queue_module._operation_lock_scopes(request)
                    if not scopes:
                        continue
                    acquired: list[str] = []
                    for scope in scopes:
                        cursor.execute(
                            """
                            INSERT INTO managed_operation_locks
                              (lock_scope, request_id, lease_owner, lease_expires_at)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (lock_scope) DO NOTHING
                            RETURNING lock_scope
                            """,
                            (scope, row["request_id"], worker_id, lease_expires_at),
                        )
                        if cursor.fetchone() is None:
                            break
                        acquired.append(scope)
                    if len(acquired) != len(scopes):
                        if acquired:
                            cursor.execute(
                                """
                                DELETE FROM managed_operation_locks
                                WHERE request_id = %s AND lease_owner = %s
                                """,
                                (row["request_id"], worker_id),
                            )
                        continue
                    attempt = int(row["attempt"]) + 1
                    receipt = contracts.build_receipt(
                        request=request,
                        status="leased",
                        generated_at=now_iso,
                        attempt=attempt,
                    )
                    cursor.execute(
                        """
                        UPDATE managed_operation_jobs
                        SET status = 'leased', attempt = %s, lease_owner = %s,
                            lease_expires_at = %s, receipt_json = %s, updated_at = %s
                        WHERE request_id = %s AND status = 'queued'
                        """,
                        (
                            attempt,
                            worker_id,
                            lease_expires_at,
                            self._dumps(receipt),
                            now_iso,
                            row["request_id"],
                        ),
                    )
                    self._record_event(
                        cursor, row["request_id"], "leased", attempt, now_iso, receipt
                    )
                    return queue_module.LeasedOperation(
                        request_id=row["request_id"],
                        request=request,
                        attempt=attempt,
                        lease_owner=worker_id,
                        lease_expires_at=lease_expires_at,
                    )
        return None

    def _owned_lease(
        self,
        cursor: Any,
        leased: queue_module.LeasedOperation,
        *,
        now_epoch: float,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT * FROM managed_operation_jobs
            WHERE request_id = %s FOR UPDATE
            """,
            (leased.request_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise queue_module.QueueContractError("leased operation no longer exists")
        if row["lease_owner"] != leased.lease_owner or row["status"] not in {
            "leased",
            "running",
        }:
            raise queue_module.QueueContractError(
                "worker does not own the active operation lease"
            )
        if row["lease_expires_at"] is None or float(row["lease_expires_at"]) <= now_epoch:
            raise queue_module.QueueContractError("operation lease has expired")
        return row

    def mark_running(
        self,
        leased: queue_module.LeasedOperation,
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]:
        receipt = contracts.build_receipt(
            request=leased.request,
            status="running",
            generated_at=now_iso,
            attempt=leased.attempt,
        )
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                row = self._owned_lease(cursor, leased, now_epoch=now_epoch)
                if row["status"] != "leased":
                    raise queue_module.QueueContractError(
                        "operation must be leased before it starts running"
                    )
                cursor.execute(
                    """
                    UPDATE managed_operation_jobs
                    SET status = 'running', receipt_json = %s, updated_at = %s
                    WHERE request_id = %s AND lease_owner = %s AND status = 'leased'
                    """,
                    (
                        self._dumps(receipt),
                        now_iso,
                        leased.request_id,
                        leased.lease_owner,
                    ),
                )
                self._record_event(
                    cursor,
                    leased.request_id,
                    "running",
                    leased.attempt,
                    now_iso,
                    receipt,
                )
        return receipt

    def heartbeat(
        self,
        leased: queue_module.LeasedOperation,
        *,
        now_epoch: float,
        lease_seconds: int,
    ) -> float:
        expires_at = now_epoch + lease_seconds
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                self._owned_lease(cursor, leased, now_epoch=now_epoch)
                cursor.execute(
                    """
                    UPDATE managed_operation_jobs SET lease_expires_at = %s
                    WHERE request_id = %s AND lease_owner = %s
                      AND status IN ('leased', 'running')
                    """,
                    (expires_at, leased.request_id, leased.lease_owner),
                )
                cursor.execute(
                    """
                    UPDATE managed_operation_locks SET lease_expires_at = %s
                    WHERE request_id = %s AND lease_owner = %s
                    """,
                    (expires_at, leased.request_id, leased.lease_owner),
                )
        return expires_at

    def complete(
        self,
        leased: queue_module.LeasedOperation,
        result: queue_module.ExecutionResult,
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]:
        if result.status not in {"succeeded", "failed", "timed_out", "quarantined"}:
            raise queue_module.QueueContractError(
                "executor returned an unsupported terminal status"
            )
        diagnostics = list(result.diagnostics)
        if result.status == "succeeded":
            diagnostics.extend(
                queue_module._validate_output_reports(
                    leased.request, result.output_reports
                )
            )
            if diagnostics:
                raise queue_module.QueueContractError("; ".join(diagnostics))
        receipt = contracts.build_receipt(
            request=leased.request,
            status=result.status,
            generated_at=now_iso,
            attempt=leased.attempt,
            output_reports=result.output_reports,
            diagnostics=diagnostics,
        )
        receipt_diagnostics = contracts.receipt_diagnostics(receipt)
        if receipt_diagnostics:
            raise queue_module.QueueContractError("; ".join(receipt_diagnostics))
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                self._owned_lease(cursor, leased, now_epoch=now_epoch)
                cursor.execute(
                    """
                    UPDATE managed_operation_jobs
                    SET status = %s, lease_owner = NULL, lease_expires_at = NULL,
                        receipt_json = %s, updated_at = %s
                    WHERE request_id = %s AND lease_owner = %s
                      AND status IN ('leased', 'running')
                    """,
                    (
                        result.status,
                        self._dumps(receipt),
                        now_iso,
                        leased.request_id,
                        leased.lease_owner,
                    ),
                )
                cursor.execute(
                    """
                    DELETE FROM managed_operation_locks
                    WHERE request_id = %s AND lease_owner = %s
                    """,
                    (leased.request_id, leased.lease_owner),
                )
                self._record_event(
                    cursor,
                    leased.request_id,
                    result.status,
                    leased.attempt,
                    now_iso,
                    receipt,
                )
        return receipt

    def recover_expired(
        self,
        *,
        now_epoch: float,
        now_iso: str,
        max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM managed_operation_jobs
                    WHERE status IN ('leased', 'running') AND lease_expires_at <= %s
                    ORDER BY request_id FOR UPDATE SKIP LOCKED
                    """,
                    (now_epoch,),
                )
                for row in cursor.fetchall():
                    request = self._loads(row["request_json"])
                    operation = request.get("operation")
                    operation = operation if isinstance(operation, dict) else {}
                    retry = (
                        operation.get("replay_policy")
                        in queue_module.AUTO_RETRY_POLICIES
                        and int(row["attempt"]) < max_attempts
                    )
                    status = "queued" if retry else "quarantined"
                    diagnostics = (
                        "expired lease requeued under replay-safe policy",
                    ) if retry else (
                        "expired lease requires reconciliation or a new operator request",
                    )
                    receipt = contracts.build_receipt(
                        request=request,
                        status=status,
                        generated_at=now_iso,
                        attempt=int(row["attempt"]),
                        diagnostics=diagnostics,
                    )
                    cursor.execute(
                        """
                        UPDATE managed_operation_jobs
                        SET status = %s, available_at = %s, lease_owner = NULL,
                            lease_expires_at = NULL, receipt_json = %s, updated_at = %s
                        WHERE request_id = %s
                        """,
                        (
                            status,
                            now_epoch,
                            self._dumps(receipt),
                            now_iso,
                            row["request_id"],
                        ),
                    )
                    cursor.execute(
                        "DELETE FROM managed_operation_locks WHERE request_id = %s",
                        (row["request_id"],),
                    )
                    self._record_event(
                        cursor,
                        row["request_id"],
                        status,
                        int(row["attempt"]),
                        now_iso,
                        receipt,
                    )
                    recovered.append(receipt)
        return recovered

    def expired_requests(self, *, now_epoch: float) -> list[dict[str, Any]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT request_id, attempt, request_json
                FROM managed_operation_jobs
                WHERE status IN ('leased', 'running') AND lease_expires_at <= %s
                ORDER BY request_id
                """,
                (now_epoch,),
            )
            rows = cursor.fetchall()
        return [
            {
                "request_id": row["request_id"],
                "attempt": int(row["attempt"]),
                "request": self._loads(row["request_json"]),
            }
            for row in rows
        ]

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM managed_operation_jobs WHERE request_id = %s",
                (request_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "request_id": row["request_id"],
            "idempotency_key": row["idempotency_key"],
            "operation_id": row["operation_id"],
            "workspace_id": row["workspace_id"],
            "request_sha256": row["request_sha256"],
            "status": row["status"],
            "attempt": row["attempt"],
            "lease_owner": row["lease_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "receipt": self._loads(row["receipt_json"]),
        }

    def events(self, request_id: str) -> list[dict[str, Any]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt, recorded_at, receipt_json
                FROM managed_operation_events
                WHERE request_id = %s ORDER BY event_id
                """,
                (request_id,),
            )
            rows = cursor.fetchall()
        return [
            {
                "status": row["status"],
                "attempt": row["attempt"],
                "recorded_at": row["recorded_at"],
                "receipt": self._loads(row["receipt_json"]),
            }
            for row in rows
        ]
