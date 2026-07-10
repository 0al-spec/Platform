"""Durable queue primitives for hosted Platform managed operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable, Protocol

try:
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operations as contracts


AUTO_RETRY_POLICIES = frozenset(
    {
        "read_only_replay_allowed",
        "same_request_dry_run_only",
    }
)
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "timed_out", "quarantined", "rejected"}
)


class QueueContractError(ValueError):
    """The queue request or state violates the managed-operation contract."""


@dataclass(frozen=True)
class LeasedOperation:
    request_id: str
    request: dict[str, Any]
    attempt: int
    lease_owner: str
    lease_expires_at: float


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    output_reports: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()


class ManagedOperationExecutor(Protocol):
    def execute(self, leased: LeasedOperation) -> ExecutionResult: ...


class ManagedOperationQueue(Protocol):
    def health(self) -> bool: ...

    def enqueue(
        self,
        request: dict[str, Any],
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]: ...

    def lease_next(
        self,
        *,
        worker_id: str,
        now_epoch: float,
        now_iso: str,
        lease_seconds: int,
    ) -> LeasedOperation | None: ...

    def complete(
        self,
        leased: LeasedOperation,
        result: ExecutionResult,
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]: ...

    def mark_running(
        self,
        leased: LeasedOperation,
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...

    def get(self, request_id: str) -> dict[str, Any] | None: ...

    def events(self, request_id: str) -> list[dict[str, Any]]: ...

    def expired_requests(self, *, now_epoch: float) -> list[dict[str, Any]]: ...

    def recover_expired(
        self,
        *,
        now_epoch: float,
        now_iso: str,
        max_attempts: int = 3,
    ) -> list[dict[str, Any]]: ...


def open_managed_operation_queue(
    *,
    adapter: str,
    database: str | Path,
) -> ManagedOperationQueue:
    if adapter == "sqlite":
        return SQLiteManagedOperationQueue(Path(database).resolve())
    if adapter == "postgresql":
        try:
            from scripts import hosted_managed_operation_postgres
        except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
            import hosted_managed_operation_postgres

        return hosted_managed_operation_postgres.PostgreSQLManagedOperationQueue(
            str(database)
        )
    raise QueueContractError("managed-operation queue adapter is unsupported")


def canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _operation_lock_scopes(request: dict[str, Any]) -> tuple[str, ...]:
    operation = request.get("operation")
    operation = operation if isinstance(operation, dict) else {}
    workspace = request.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    operation_id = str(operation.get("operation_id") or "")
    workspace_id = str(workspace.get("workspace_id") or "")
    scopes = operation.get("lock_scopes")
    if not isinstance(scopes, list):
        return ()
    return tuple(
        str(scope).format(
            operation_id=operation_id,
            workspace_id=workspace_id,
        )
        for scope in scopes
    )


def _validate_output_reports(
    request: dict[str, Any],
    reports: tuple[dict[str, Any], ...],
) -> list[str]:
    diagnostics: list[str] = []
    expected = request.get("expected_output_reports")
    expected = expected if isinstance(expected, list) else []
    refs: list[str] = []
    for index, report in enumerate(reports):
        if set(report) != {"logical_ref", "sha256"}:
            diagnostics.append(f"output report {index} does not match the receipt contract")
            continue
        ref = report.get("logical_ref")
        if not contracts.safe_artifact_ref(ref):
            diagnostics.append(f"output report {index} has an unsafe logical ref")
        elif isinstance(ref, str):
            refs.append(ref)
        if not contracts.SHA256_RE.fullmatch(str(report.get("sha256") or "")):
            diagnostics.append(f"output report {index} has an invalid digest")
    workspace = request.get("workspace")
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_id = str(workspace.get("workspace_id") or "")

    def matches(pattern: str, ref: str) -> bool:
        escaped = re.escape(pattern).replace(
            re.escape("<workspace-id>"), re.escape(workspace_id)
        )
        escaped = escaped.replace(re.escape("<request-id>"), r"[a-zA-Z0-9._-]+")
        return re.fullmatch(escaped, ref) is not None

    if len(refs) != len(expected) or any(
        not any(matches(pattern, ref) for ref in refs) for pattern in expected
    ):
        diagnostics.append("succeeded execution must pin every expected Platform output report")
    return diagnostics


class SQLiteManagedOperationQueue:
    """Single-database durable adapter used by local and integration workers."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def health(self) -> bool:
        return self.connection.execute("SELECT 1").fetchone()[0] == 1

    def initialize(self) -> None:
        self.connection.executescript(
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
                available_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                receipt_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS managed_operation_jobs_ready
              ON managed_operation_jobs(status, available_at, created_at);
            CREATE TABLE IF NOT EXISTS managed_operation_locks (
                lock_scope TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                lease_owner TEXT NOT NULL,
                lease_expires_at REAL NOT NULL,
                FOREIGN KEY(request_id) REFERENCES managed_operation_jobs(request_id)
                  ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS managed_operation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES managed_operation_jobs(request_id)
                  ON DELETE CASCADE
            );
            """
        )

    def _record_event(
        self,
        request_id: str,
        status: str,
        attempt: int,
        now_iso: str,
        receipt: dict[str, Any],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO managed_operation_events
              (request_id, status, attempt, recorded_at, receipt_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (request_id, status, attempt, now_iso, json.dumps(receipt, sort_keys=True)),
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
            raise QueueContractError("; ".join(diagnostics))
        request_id = str(request["request_id"])
        idempotency_key = str(request["idempotency_key"])
        operation_id = str(request["operation"]["operation_id"])
        workspace_id = str(request["workspace"]["workspace_id"])
        request_digest = canonical_sha256(request)
        receipt = contracts.build_receipt(
            request=request,
            status="queued",
            generated_at=now_iso,
            attempt=0,
        )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self.connection.execute(
                "SELECT * FROM managed_operation_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_id"] != operation_id
                    or existing["workspace_id"] != workspace_id
                ):
                    raise QueueContractError(
                        "idempotency key is already owned by another operation"
                    )
                self.connection.execute("COMMIT")
                return json.loads(existing["receipt_json"])
            self.connection.execute(
                """
                INSERT INTO managed_operation_jobs (
                  request_id, idempotency_key, operation_id, workspace_id,
                  request_sha256, request_json, status, attempt, available_at,
                  receipt_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    idempotency_key,
                    operation_id,
                    workspace_id,
                    request_digest,
                    json.dumps(request, sort_keys=True),
                    now_epoch,
                    json.dumps(receipt, sort_keys=True),
                    now_iso,
                    now_iso,
                ),
            )
            self._record_event(request_id, "queued", 0, now_iso, receipt)
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return receipt

    def _try_acquire_locks(
        self,
        request: dict[str, Any],
        *,
        request_id: str,
        worker_id: str,
        lease_expires_at: float,
        now_epoch: float,
    ) -> bool:
        scopes = _operation_lock_scopes(request)
        if not scopes:
            return False
        placeholders = ",".join("?" for _ in scopes)
        conflict = self.connection.execute(
            f"SELECT lock_scope FROM managed_operation_locks WHERE lock_scope IN ({placeholders}) LIMIT 1",
            scopes,
        ).fetchone()
        if conflict is not None:
            return False
        for scope in scopes:
            self.connection.execute(
                """
                INSERT INTO managed_operation_locks
                  (lock_scope, request_id, lease_owner, lease_expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (scope, request_id, worker_id, lease_expires_at),
            )
        return True

    def lease_next(
        self,
        *,
        worker_id: str,
        now_epoch: float,
        now_iso: str,
        lease_seconds: int,
    ) -> LeasedOperation | None:
        if not worker_id or lease_seconds < 1:
            raise QueueContractError("worker id and positive lease duration are required")
        lease_expires_at = now_epoch + lease_seconds
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self.connection.execute(
                """
                SELECT * FROM managed_operation_jobs
                WHERE status = 'queued' AND available_at <= ?
                ORDER BY created_at, request_id
                """,
                (now_epoch,),
            ).fetchall()
            selected: sqlite3.Row | None = None
            selected_request: dict[str, Any] | None = None
            for row in rows:
                request = json.loads(row["request_json"])
                if self._try_acquire_locks(
                    request,
                    request_id=row["request_id"],
                    worker_id=worker_id,
                    lease_expires_at=lease_expires_at,
                    now_epoch=now_epoch,
                ):
                    selected = row
                    selected_request = request
                    break
            if selected is None or selected_request is None:
                self.connection.execute("COMMIT")
                return None
            attempt = int(selected["attempt"]) + 1
            receipt = contracts.build_receipt(
                request=selected_request,
                status="leased",
                generated_at=now_iso,
                attempt=attempt,
            )
            self.connection.execute(
                """
                UPDATE managed_operation_jobs
                SET status = 'leased', attempt = ?, lease_owner = ?,
                    lease_expires_at = ?, receipt_json = ?, updated_at = ?
                WHERE request_id = ? AND status = 'queued'
                """,
                (
                    attempt,
                    worker_id,
                    lease_expires_at,
                    json.dumps(receipt, sort_keys=True),
                    now_iso,
                    selected["request_id"],
                ),
            )
            self._record_event(selected["request_id"], "leased", attempt, now_iso, receipt)
            self.connection.execute("COMMIT")
            return LeasedOperation(
                request_id=selected["request_id"],
                request=selected_request,
                attempt=attempt,
                lease_owner=worker_id,
                lease_expires_at=lease_expires_at,
            )
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def mark_running(
        self,
        leased: LeasedOperation,
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
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._owned_lease(leased, now_epoch=now_epoch)
            if row["status"] != "leased":
                raise QueueContractError("operation must be leased before it starts running")
            self.connection.execute(
                """
                UPDATE managed_operation_jobs
                SET status = 'running', receipt_json = ?, updated_at = ?
                WHERE request_id = ? AND lease_owner = ? AND status = 'leased'
                """,
                (
                    json.dumps(receipt, sort_keys=True),
                    now_iso,
                    row["request_id"],
                    leased.lease_owner,
                ),
            )
            self._record_event(
                leased.request_id, "running", leased.attempt, now_iso, receipt
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return receipt

    def heartbeat(
        self,
        leased: LeasedOperation,
        *,
        now_epoch: float,
        lease_seconds: int,
    ) -> float:
        expires_at = now_epoch + lease_seconds
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._owned_lease(leased, now_epoch=now_epoch)
            self.connection.execute(
                """
                UPDATE managed_operation_jobs SET lease_expires_at = ?
                WHERE request_id = ? AND lease_owner = ? AND status IN ('leased', 'running')
                """,
                (expires_at, leased.request_id, leased.lease_owner),
            )
            self.connection.execute(
                """
                UPDATE managed_operation_locks SET lease_expires_at = ?
                WHERE request_id = ? AND lease_owner = ?
                """,
                (expires_at, leased.request_id, leased.lease_owner),
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return expires_at

    def _owned_lease(self, leased: LeasedOperation, *, now_epoch: float) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM managed_operation_jobs WHERE request_id = ?",
            (leased.request_id,),
        ).fetchone()
        if row is None:
            raise QueueContractError("leased operation no longer exists")
        if row["lease_owner"] != leased.lease_owner or row["status"] not in {"leased", "running"}:
            raise QueueContractError("worker does not own the active operation lease")
        if row["lease_expires_at"] is None or float(row["lease_expires_at"]) <= now_epoch:
            raise QueueContractError("operation lease has expired")
        return row

    def complete(
        self,
        leased: LeasedOperation,
        result: ExecutionResult,
        *,
        now_epoch: float,
        now_iso: str,
    ) -> dict[str, Any]:
        if result.status not in {"succeeded", "failed", "timed_out", "quarantined"}:
            raise QueueContractError("executor returned an unsupported terminal status")
        diagnostics = list(result.diagnostics)
        if result.status == "succeeded":
            diagnostics.extend(_validate_output_reports(leased.request, result.output_reports))
            if diagnostics:
                raise QueueContractError("; ".join(diagnostics))
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
            raise QueueContractError("; ".join(receipt_diagnostics))
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._owned_lease(leased, now_epoch=now_epoch)
            self.connection.execute(
                """
                UPDATE managed_operation_jobs
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    receipt_json = ?, updated_at = ?
                WHERE request_id = ? AND lease_owner = ?
                  AND status IN ('leased', 'running')
                """,
                (
                    result.status,
                    json.dumps(receipt, sort_keys=True),
                    now_iso,
                    leased.request_id,
                    leased.lease_owner,
                ),
            )
            self.connection.execute(
                "DELETE FROM managed_operation_locks WHERE request_id = ? AND lease_owner = ?",
                (leased.request_id, leased.lease_owner),
            )
            self._record_event(
                leased.request_id,
                result.status,
                leased.attempt,
                now_iso,
                receipt,
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return receipt

    def recover_expired(
        self,
        *,
        now_epoch: float,
        now_iso: str,
        max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self.connection.execute(
                """
                SELECT * FROM managed_operation_jobs
                WHERE status IN ('leased', 'running') AND lease_expires_at <= ?
                ORDER BY request_id
                """,
                (now_epoch,),
            ).fetchall()
            for row in rows:
                request = json.loads(row["request_json"])
                operation = request.get("operation")
                operation = operation if isinstance(operation, dict) else {}
                replay_policy = str(operation.get("replay_policy") or "")
                retry = replay_policy in AUTO_RETRY_POLICIES and int(row["attempt"]) < max_attempts
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
                self.connection.execute(
                    """
                    UPDATE managed_operation_jobs
                    SET status = ?, available_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, receipt_json = ?, updated_at = ?
                    WHERE request_id = ?
                    """,
                    (
                        status,
                        now_epoch,
                        json.dumps(receipt, sort_keys=True),
                        now_iso,
                        row["request_id"],
                    ),
                )
                self.connection.execute(
                    "DELETE FROM managed_operation_locks WHERE request_id = ?",
                    (row["request_id"],),
                )
                self._record_event(
                    row["request_id"], status, int(row["attempt"]), now_iso, receipt
                )
                recovered.append(receipt)
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return recovered

    def expired_requests(self, *, now_epoch: float) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT request_id, attempt, request_json
            FROM managed_operation_jobs
            WHERE status IN ('leased', 'running') AND lease_expires_at <= ?
            ORDER BY request_id
            """,
            (now_epoch,),
        ).fetchall()
        return [
            {
                "request_id": row["request_id"],
                "attempt": int(row["attempt"]),
                "request": json.loads(row["request_json"]),
            }
            for row in rows
        ]

    def get(self, request_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM managed_operation_jobs WHERE request_id = ?",
            (request_id,),
        ).fetchone()
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
            "receipt": json.loads(row["receipt_json"]),
        }

    def events(self, request_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT status, attempt, recorded_at, receipt_json
            FROM managed_operation_events
            WHERE request_id = ? ORDER BY event_id
            """,
            (request_id,),
        ).fetchall()
        return [
            {
                "status": row["status"],
                "attempt": row["attempt"],
                "recorded_at": row["recorded_at"],
                "receipt": json.loads(row["receipt_json"]),
            }
            for row in rows
        ]


class HostedManagedOperationWorker:
    def __init__(
        self,
        queue: ManagedOperationQueue,
        executor: ManagedOperationExecutor,
        *,
        worker_id: str,
        lease_seconds: int = 600,
        monotonic_clock: Callable[[], float] = time.monotonic,
        allowed_operation_ids: frozenset[str] | None = None,
    ) -> None:
        self.queue = queue
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.monotonic_clock = monotonic_clock
        self.allowed_operation_ids = contracts.normalize_operation_allowlist(
            allowed_operation_ids
        )

    def run_once(
        self,
        *,
        now_epoch: float | None = None,
        now_iso: str | None = None,
        completion_epoch: float | None = None,
        completion_iso: str | None = None,
    ) -> dict[str, Any] | None:
        if now_epoch is None:
            now_epoch = time.time()
        if now_iso is None:
            now_iso = datetime.now(timezone.utc).isoformat()
        started_at = self.monotonic_clock()
        leased = self.queue.lease_next(
            worker_id=self.worker_id,
            now_epoch=now_epoch,
            now_iso=now_iso,
            lease_seconds=self.lease_seconds,
        )
        if leased is None:
            return None
        self.queue.mark_running(leased, now_epoch=now_epoch, now_iso=now_iso)
        try:
            operation_id = str(leased.request.get("operation", {}).get("operation_id") or "")
            if operation_id not in self.allowed_operation_ids:
                result = ExecutionResult(
                    status="quarantined",
                    diagnostics=("worker operation allowlist rejected request",),
                )
            else:
                result = self.executor.execute(leased)
        except Exception as exc:
            result = ExecutionResult(
                status="failed",
                diagnostics=(f"executor failed: {type(exc).__name__}",),
            )
        elapsed_seconds = max(0.0, self.monotonic_clock() - started_at)
        if completion_epoch is None:
            completion_epoch = now_epoch + elapsed_seconds
        if completion_iso is None:
            completion_iso = _advance_iso(now_iso, elapsed_seconds)
        return self.queue.complete(
            leased,
            result,
            now_epoch=completion_epoch,
            now_iso=completion_iso,
        )


def _advance_iso(value: str, elapsed_seconds: float) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return (
        (parsed + timedelta(seconds=elapsed_seconds))
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
