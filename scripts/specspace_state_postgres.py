"""PostgreSQL adapter for private, versioned SpecSpace state."""

from __future__ import annotations

import json
from typing import Any

if __package__:
    from scripts import specspace_state_store as contracts
else:  # Direct execution adds scripts/ to sys.path.
    import specspace_state_store as contracts


class PostgreSQLDependencyError(RuntimeError):
    pass


def _driver() -> tuple[Any, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise PostgreSQLDependencyError(
            "PostgreSQL SpecSpace state requires psycopg[binary]>=3.2"
        ) from exc
    return psycopg, dict_row


class PostgreSQLSpecSpaceStateStore:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise contracts.StateStoreError(
                "PostgreSQL SpecSpace state URL must use postgresql:// or postgres://"
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
            CREATE TABLE IF NOT EXISTS specspace_state_records (
                workspace_id TEXT NOT NULL,
                record_key TEXT NOT NULL,
                revision BIGINT NOT NULL,
                content_sha256 TEXT NOT NULL,
                content_json JSONB NOT NULL,
                lifecycle_state TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                consumed_at TEXT,
                superseded_at TEXT,
                deleted_at TEXT,
                PRIMARY KEY (workspace_id, record_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS specspace_state_versions (
                workspace_id TEXT NOT NULL,
                record_key TEXT NOT NULL,
                revision BIGINT NOT NULL,
                content_sha256 TEXT NOT NULL,
                content_json JSONB NOT NULL,
                lifecycle_state TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, record_key, revision)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS specspace_state_versions_recorded
              ON specspace_state_versions(recorded_at)
            """,
        )
        with self.connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        content = payload.pop("content_json")
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, dict):
            raise contracts.StateStoreError("stored state content is not an object")
        payload["content"] = content
        return payload

    def get(
        self,
        workspace_id: str,
        record_key: str,
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        workspace_id = contracts.validate_workspace_id(workspace_id)
        record_key = contracts.validate_record_key(
            record_key, workspace_id=workspace_id
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM specspace_state_records
                WHERE workspace_id = %s AND record_key = %s
                """,
                (workspace_id, record_key),
            )
            row = cursor.fetchone()
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
            clauses.append("workspace_id = %s")
            values.append(contracts.validate_workspace_id(workspace_id))
        if record_key is not None:
            if workspace_id is None and record_key not in contracts.STATE_RECORD_KEYS:
                raise contracts.StateStoreError(
                    "listing dynamic record keys requires workspace_id"
                )
            clauses.append("record_key = %s")
            values.append(
                contracts.validate_record_key(
                    record_key,
                    workspace_id=workspace_id or "placeholder",
                )
            )
        if not include_deleted:
            clauses.append("lifecycle_state <> 'deleted'")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM specspace_state_records"
                + where
                + " ORDER BY workspace_id, record_key",
                values,
            )
            rows = cursor.fetchall()
        return [self._decode(row) for row in rows]

    def history(
        self,
        workspace_id: str,
        record_key: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        workspace_id = contracts.validate_workspace_id(workspace_id)
        record_key = contracts.validate_record_key(
            record_key, workspace_id=workspace_id
        )
        limit = max(1, min(int(limit), 500))
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT workspace_id, record_key, revision, content_sha256,
                       content_json, lifecycle_state, idempotency_key, recorded_at
                FROM specspace_state_versions
                WHERE workspace_id = %s AND record_key = %s
                ORDER BY revision DESC
                LIMIT %s
                """,
                (workspace_id, record_key, limit),
            )
            rows = cursor.fetchall()
        return [self._decode(row) for row in rows]

    def mutate(
        self,
        mutation: contracts.StateMutation,
        *,
        now_iso: str,
    ) -> dict[str, Any]:
        mutation.validate()
        digest = contracts.content_sha256(mutation.content)
        encoded = contracts.canonical_json_bytes(mutation.content).decode("utf-8")
        lock_names = sorted(
            (
                f"record:{mutation.workspace_id}:{mutation.record_key}",
                f"idempotency:{mutation.idempotency_key}",
            )
        )
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                for lock_name in lock_names:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (lock_name,),
                    )
                cursor.execute(
                    """
                    SELECT * FROM specspace_state_versions
                    WHERE idempotency_key = %s
                    """,
                    (mutation.idempotency_key,),
                )
                existing_idempotency = cursor.fetchone()
                if existing_idempotency is not None:
                    replay = self._decode(existing_idempotency)
                    if (
                        replay["workspace_id"] != mutation.workspace_id
                        or replay["record_key"] != mutation.record_key
                        or replay["content_sha256"] != digest
                        or replay["lifecycle_state"] != mutation.lifecycle_state
                    ):
                        raise contracts.StateConflictError(
                            "idempotency_key is already owned by another state mutation"
                        )
                    cursor.execute(
                        """
                        SELECT * FROM specspace_state_records
                        WHERE workspace_id = %s AND record_key = %s
                        """,
                        (mutation.workspace_id, mutation.record_key),
                    )
                    current_row = cursor.fetchone()
                    current = (
                        self._decode(current_row)
                        if current_row is not None
                        else None
                    )
                    if current is None or current["revision"] != replay["revision"]:
                        raise contracts.StateConflictError(
                            "idempotent replay no longer names the current revision"
                        )
                    return current

                cursor.execute(
                    """
                    SELECT * FROM specspace_state_records
                    WHERE workspace_id = %s AND record_key = %s
                    FOR UPDATE
                    """,
                    (mutation.workspace_id, mutation.record_key),
                )
                current_row = cursor.fetchone()
                current = (
                    self._decode(current_row) if current_row is not None else None
                )
                current_revision = (
                    int(current["revision"]) if current is not None else 0
                )
                if current_revision != mutation.expected_revision:
                    raise contracts.StateConflictError(
                        f"state revision conflict: expected "
                        f"{mutation.expected_revision}, current {current_revision}"
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
                deleted_at = (
                    now_iso if mutation.lifecycle_state == "deleted" else None
                )
                cursor.execute(
                    """
                    INSERT INTO specspace_state_versions (
                        workspace_id, record_key, revision, content_sha256,
                        content_json, lifecycle_state, idempotency_key, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
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
                cursor.execute(
                    """
                    INSERT INTO specspace_state_records (
                        workspace_id, record_key, revision, content_sha256,
                        content_json, lifecycle_state, idempotency_key,
                        created_at, updated_at, consumed_at, superseded_at, deleted_at
                    ) VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (workspace_id, record_key) DO UPDATE SET
                        revision = EXCLUDED.revision,
                        content_sha256 = EXCLUDED.content_sha256,
                        content_json = EXCLUDED.content_json,
                        lifecycle_state = EXCLUDED.lifecycle_state,
                        idempotency_key = EXCLUDED.idempotency_key,
                        updated_at = EXCLUDED.updated_at,
                        consumed_at = EXCLUDED.consumed_at,
                        superseded_at = EXCLUDED.superseded_at,
                        deleted_at = EXCLUDED.deleted_at
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
            raise contracts.StateStoreError(
                "state mutation did not produce a current record"
            )
        return result

    def prune_versions(self, *, retain_latest: int) -> int:
        if not isinstance(retain_latest, int) or isinstance(retain_latest, bool):
            raise contracts.StateStoreError("retain_latest must be an integer")
        if retain_latest < 1:
            raise contracts.StateStoreError("retain_latest must be at least one")
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                cursor.execute(
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
                        WHERE row_number > %s
                    )
                    """,
                    (retain_latest,),
                )
                deleted = cursor.rowcount
        return max(0, int(deleted))
