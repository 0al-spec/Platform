"""Versioned private state contract and SQLite adapter for SpecSpace."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any, Protocol


CONTRACT_REF = "platform.specspace-state.record.v1"
SERVICE_CONTRACT_REF = "platform.specspace-state.service.v1"
EXPORT_CONTRACT_REF = "platform.specspace-state.export.v1"
WORKSPACE_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])?")
OPERATION_ID_RE = re.compile(r"[a-z][a-z0-9_]{2,63}")
IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{15,255}")
LIFECYCLE_STATES = frozenset({"active", "consumed", "superseded", "deleted"})
STATE_RECORD_KEYS = frozenset(
    {
        "hosted_managed_operation_requests.json",
        "idea_to_spec_candidate_approval_intents.json",
        "idea_to_spec_intake_clarification_answers.json",
        "idea_to_spec_repair_drafts.json",
        "idea_to_spec_repair_rerun_requests.json",
        "ontology_owner_decision_acknowledgements.json",
        "product_workspace_creation_requests.json",
        "project_local_ontology_review_decisions.json",
        "real_idea_answer_continuation_execution_requests.json",
        "real_idea_entry_requests.json",
        "real_idea_intake_execution_requests.json",
    }
)


class StateStoreError(ValueError):
    pass


class StateConflictError(StateStoreError):
    pass


class StateNotFoundError(StateStoreError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StateStoreError("state content must be JSON serializable") from exc


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def validate_workspace_id(value: Any) -> str:
    if not isinstance(value, str) or not WORKSPACE_ID_RE.fullmatch(value):
        raise StateStoreError("workspace_id is invalid")
    return value


def validate_record_key(value: Any, *, workspace_id: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise StateStoreError("record_key is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StateStoreError("record_key is not a safe relative path")
    if "\\" in value or any(ord(char) < 32 for char in value):
        raise StateStoreError("record_key contains unsafe characters")
    if value in STATE_RECORD_KEYS:
        return value
    parts = path.parts
    if (
        len(parts) == 4
        and parts[0] == "confirmations"
        and parts[1] == workspace_id
        and OPERATION_ID_RE.fullmatch(parts[2])
        and parts[3].endswith(".json")
        and len(parts[3]) <= 128
        and all(char.isalnum() or char in "._-" for char in parts[3])
    ):
        return value
    raise StateStoreError("record_key is outside the SpecSpace state allowlist")


def validate_idempotency_key(value: Any) -> str:
    if not isinstance(value, str) or not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise StateStoreError("idempotency_key is invalid")
    return value


def validate_lifecycle_state(value: Any) -> str:
    if not isinstance(value, str) or value not in LIFECYCLE_STATES:
        raise StateStoreError("lifecycle_state is invalid")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def record_projection(row: dict[str, Any], *, include_content: bool) -> dict[str, Any]:
    projection = {
        "contract_ref": CONTRACT_REF,
        "workspace_id": row["workspace_id"],
        "record_key": row["record_key"],
        "revision": int(row["revision"]),
        "content_sha256": row["content_sha256"],
        "lifecycle_state": row["lifecycle_state"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "consumed_at": row.get("consumed_at"),
        "superseded_at": row.get("superseded_at"),
        "deleted_at": row.get("deleted_at"),
    }
    if include_content and row["lifecycle_state"] != "deleted":
        projection["content"] = _mapping(row.get("content"))
    return projection


@dataclass(frozen=True)
class StateMutation:
    workspace_id: str
    record_key: str
    expected_revision: int
    idempotency_key: str
    lifecycle_state: str
    content: dict[str, Any]
    supplied_content_sha256: str | None = None

    def validate(self) -> "StateMutation":
        workspace_id = validate_workspace_id(self.workspace_id)
        validate_record_key(self.record_key, workspace_id=workspace_id)
        if not isinstance(self.expected_revision, int) or isinstance(
            self.expected_revision, bool
        ) or self.expected_revision < 0:
            raise StateStoreError("expected_revision must be a non-negative integer")
        validate_idempotency_key(self.idempotency_key)
        validate_lifecycle_state(self.lifecycle_state)
        if not isinstance(self.content, dict):
            raise StateStoreError("content must be a JSON object")
        digest = content_sha256(self.content)
        if (
            self.supplied_content_sha256 is not None
            and self.supplied_content_sha256 != digest
        ):
            raise StateStoreError("content_sha256 does not match canonical content")
        if self.lifecycle_state == "deleted" and self.content:
            raise StateStoreError("deleted records must use empty content")
        return self


class SpecSpaceStateStore(Protocol):
    def close(self) -> None: ...

    def health(self) -> bool: ...

    def get(
        self,
        workspace_id: str,
        record_key: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None: ...

    def list_records(
        self,
        *,
        workspace_id: str | None = None,
        record_key: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]: ...

    def history(
        self,
        workspace_id: str,
        record_key: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def mutate(self, mutation: StateMutation, *, now_iso: str) -> dict[str, Any]: ...

    def prune_versions(self, *, retain_latest: int) -> int: ...


class SQLiteSpecSpaceStateStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def health(self) -> bool:
        return self.connection.execute("SELECT 1").fetchone() is not None

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS specspace_state_records (
                workspace_id TEXT NOT NULL,
                record_key TEXT NOT NULL,
                revision INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                content_json TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                consumed_at TEXT,
                superseded_at TEXT,
                deleted_at TEXT,
                PRIMARY KEY (workspace_id, record_key)
            );
            CREATE TABLE IF NOT EXISTS specspace_state_versions (
                workspace_id TEXT NOT NULL,
                record_key TEXT NOT NULL,
                revision INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                content_json TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, record_key, revision)
            );
            CREATE INDEX IF NOT EXISTS specspace_state_versions_recorded
              ON specspace_state_versions(recorded_at);
            """
        )
        self.connection.commit()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["content"] = json.loads(str(payload.pop("content_json")))
        return payload

    def get(
        self,
        workspace_id: str,
        record_key: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        workspace_id = validate_workspace_id(workspace_id)
        record_key = validate_record_key(record_key, workspace_id=workspace_id)
        row = self.connection.execute(
            """
            SELECT * FROM specspace_state_records
            WHERE workspace_id = ? AND record_key = ?
            """,
            (workspace_id, record_key),
        ).fetchone()
        if row is None:
            return None
        decoded = self._decode(row)
        if decoded["lifecycle_state"] == "deleted" and not include_deleted:
            return None
        return decoded

    def list_records(
        self,
        *,
        workspace_id: str | None = None,
        record_key: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            values.append(validate_workspace_id(workspace_id))
        if record_key is not None:
            if workspace_id is None and record_key not in STATE_RECORD_KEYS:
                raise StateStoreError(
                    "listing dynamic record keys requires workspace_id"
                )
            clauses.append("record_key = ?")
            values.append(
                validate_record_key(
                    record_key,
                    workspace_id=workspace_id or "placeholder",
                )
            )
        if not include_deleted:
            clauses.append("lifecycle_state <> 'deleted'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.connection.execute(
            "SELECT * FROM specspace_state_records"
            + where
            + " ORDER BY workspace_id, record_key",
            values,
        ).fetchall()
        return [self._decode(row) for row in rows]

    def history(
        self,
        workspace_id: str,
        record_key: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        workspace_id = validate_workspace_id(workspace_id)
        record_key = validate_record_key(record_key, workspace_id=workspace_id)
        limit = max(1, min(int(limit), 500))
        rows = self.connection.execute(
            """
            SELECT workspace_id, record_key, revision, content_sha256, content_json,
                   lifecycle_state, idempotency_key, recorded_at
            FROM specspace_state_versions
            WHERE workspace_id = ? AND record_key = ?
            ORDER BY revision DESC
            LIMIT ?
            """,
            (workspace_id, record_key, limit),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def mutate(self, mutation: StateMutation, *, now_iso: str) -> dict[str, Any]:
        mutation.validate()
        digest = content_sha256(mutation.content)
        encoded = canonical_json_bytes(mutation.content).decode("utf-8")
        with self.connection:
            existing_idempotency = self.connection.execute(
                """
                SELECT * FROM specspace_state_versions WHERE idempotency_key = ?
                """,
                (mutation.idempotency_key,),
            ).fetchone()
            if existing_idempotency is not None:
                replay = self._decode(existing_idempotency)
                if (
                    replay["workspace_id"] != mutation.workspace_id
                    or replay["record_key"] != mutation.record_key
                    or replay["content_sha256"] != digest
                    or replay["lifecycle_state"] != mutation.lifecycle_state
                ):
                    raise StateConflictError(
                        "idempotency_key is already owned by another state mutation"
                    )
                current = self.get(
                    mutation.workspace_id,
                    mutation.record_key,
                    include_deleted=True,
                )
                if current is None or current["revision"] != replay["revision"]:
                    raise StateConflictError(
                        "idempotent replay no longer names the current revision"
                    )
                return current

            current_row = self.connection.execute(
                """
                SELECT * FROM specspace_state_records
                WHERE workspace_id = ? AND record_key = ?
                """,
                (mutation.workspace_id, mutation.record_key),
            ).fetchone()
            current = self._decode(current_row) if current_row is not None else None
            current_revision = int(current["revision"]) if current is not None else 0
            if current_revision != mutation.expected_revision:
                raise StateConflictError(
                    f"state revision conflict: expected {mutation.expected_revision}, "
                    f"current {current_revision}"
                )
            revision = current_revision + 1
            created_at = (
                str(current["created_at"]) if current is not None else now_iso
            )
            consumed_at = (
                now_iso
                if mutation.lifecycle_state == "consumed"
                else current.get("consumed_at")
                if current is not None
                else None
            )
            superseded_at = (
                now_iso
                if mutation.lifecycle_state == "superseded"
                else current.get("superseded_at")
                if current is not None
                else None
            )
            deleted_at = now_iso if mutation.lifecycle_state == "deleted" else None
            self.connection.execute(
                """
                INSERT INTO specspace_state_versions (
                    workspace_id, record_key, revision, content_sha256, content_json,
                    lifecycle_state, idempotency_key, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mutation.workspace_id,
                    mutation.record_key,
                    revision,
                    digest,
                    encoded,
                    mutation.lifecycle_state,
                    mutation.idempotency_key,
                    now_iso,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO specspace_state_records (
                    workspace_id, record_key, revision, content_sha256, content_json,
                    lifecycle_state, idempotency_key, created_at, updated_at,
                    consumed_at, superseded_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, record_key) DO UPDATE SET
                    revision = excluded.revision,
                    content_sha256 = excluded.content_sha256,
                    content_json = excluded.content_json,
                    lifecycle_state = excluded.lifecycle_state,
                    idempotency_key = excluded.idempotency_key,
                    updated_at = excluded.updated_at,
                    consumed_at = excluded.consumed_at,
                    superseded_at = excluded.superseded_at,
                    deleted_at = excluded.deleted_at
                """,
                (
                    mutation.workspace_id,
                    mutation.record_key,
                    revision,
                    digest,
                    encoded,
                    mutation.lifecycle_state,
                    mutation.idempotency_key,
                    created_at,
                    now_iso,
                    consumed_at,
                    superseded_at,
                    deleted_at,
                ),
            )
        result = self.get(
            mutation.workspace_id,
            mutation.record_key,
            include_deleted=True,
        )
        if result is None:  # pragma: no cover - transaction invariant
            raise StateStoreError("state mutation did not produce a current record")
        return result

    def prune_versions(self, *, retain_latest: int) -> int:
        if not isinstance(retain_latest, int) or isinstance(retain_latest, bool):
            raise StateStoreError("retain_latest must be an integer")
        if retain_latest < 1:
            raise StateStoreError("retain_latest must be at least one")
        with self.connection:
            cursor = self.connection.execute(
                """
                DELETE FROM specspace_state_versions
                WHERE (workspace_id, record_key, revision) IN (
                    SELECT workspace_id, record_key, revision
                    FROM (
                        SELECT workspace_id, record_key, revision,
                               ROW_NUMBER() OVER (
                                   PARTITION BY workspace_id, record_key
                                   ORDER BY revision DESC
                               ) AS row_number
                        FROM specspace_state_versions
                    ) ranked
                    WHERE row_number > ?
                )
                """,
                (retain_latest,),
            )
        return max(0, int(cursor.rowcount))


def open_state_store(*, adapter: str, database: str) -> SpecSpaceStateStore:
    if adapter == "sqlite":
        return SQLiteSpecSpaceStateStore(Path(database))
    if adapter == "postgresql":
        if __package__:
            from scripts import specspace_state_postgres
        else:  # Direct execution adds scripts/ to sys.path.
            import specspace_state_postgres

        return specspace_state_postgres.PostgreSQLSpecSpaceStateStore(database)
    raise StateStoreError("unknown SpecSpace state adapter")
