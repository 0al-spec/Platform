"""Create and restore-verify private hosted managed-operation backups."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any
from urllib.parse import urlsplit, urlunsplit


BACKUP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
QUEUE_TABLES = (
    "managed_operation_jobs",
    "managed_operation_events",
    "managed_operation_locks",
)
STATE_TABLES = (
    "specspace_state_records",
    "specspace_state_versions",
)
TABLE_COLUMNS = {
    "managed_operation_jobs": (
        "request_id",
        "idempotency_key",
        "operation_id",
        "workspace_id",
        "request_sha256",
        "request_json",
        "status",
        "attempt",
        "available_at",
        "lease_owner",
        "lease_expires_at",
        "receipt_json",
        "created_at",
        "updated_at",
    ),
    "managed_operation_events": (
        "event_id",
        "request_id",
        "status",
        "attempt",
        "recorded_at",
        "receipt_json",
    ),
    "managed_operation_locks": (
        "lock_scope",
        "request_id",
        "lease_owner",
        "lease_expires_at",
    ),
}
STATE_TABLE_COLUMNS = {
    "specspace_state_records": (
        "workspace_id",
        "record_key",
        "revision",
        "content_sha256",
        "content_json",
        "lifecycle_state",
        "idempotency_key",
        "created_at",
        "updated_at",
        "consumed_at",
        "superseded_at",
        "deleted_at",
    ),
    "specspace_state_versions": (
        "workspace_id",
        "record_key",
        "revision",
        "content_sha256",
        "content_json",
        "lifecycle_state",
        "idempotency_key",
        "recorded_at",
    ),
}


class HostedBackupError(RuntimeError):
    """Backup or restore verification failed without mutating production state."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_url(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise HostedBackupError("database URL secret file is unavailable") from exc
    if not value.startswith(("postgresql://", "postgres://")):
        raise HostedBackupError("database URL must use PostgreSQL")
    return value


def _driver() -> tuple[Any, Any]:
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise HostedBackupError("psycopg is required for hosted backup") from exc
    return psycopg, sql


def _row_counts(database_url: str) -> dict[str, int]:
    psycopg, sql = _driver()
    counts: dict[str, int] = {}
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for table in QUEUE_TABLES:
                cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                row = cursor.fetchone()
                counts[table] = int(row[0])
    return counts


def _state_row_counts(database_url: str) -> dict[str, int]:
    psycopg, sql = _driver()
    counts: dict[str, int] = {}
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for table in STATE_TABLES:
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}").format(
                        sql.Identifier(table)
                    )
                )
                row = cursor.fetchone()
                counts[table] = int(row[0])
    return counts


def _replace_database(database_url: str, database: str) -> str:
    parsed = urlsplit(database_url)
    if not parsed.path.lstrip("/"):
        raise HostedBackupError("database URL must include a database name")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )


def _database_export(database_url: str) -> dict[str, Any]:
    psycopg, sql = _driver()
    tables: dict[str, list[dict[str, Any]]] = {}
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for table in QUEUE_TABLES:
                columns = TABLE_COLUMNS[table]
                cursor.execute(
                    sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.Identifier(table),
                        sql.Identifier(columns[0]),
                    )
                )
                tables[table] = [
                    dict(zip(columns, row, strict=True)) for row in cursor.fetchall()
                ]
        connection.commit()
    return {
        "artifact_kind": "platform_hosted_managed_queue_backup",
        "schema_version": 1,
        "tables": tables,
    }


def _state_database_export(database_url: str) -> dict[str, Any]:
    psycopg, sql = _driver()
    tables: dict[str, list[dict[str, Any]]] = {}
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            for table in STATE_TABLES:
                columns = STATE_TABLE_COLUMNS[table]
                cursor.execute(
                    sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.Identifier(table),
                        sql.SQL(", ").join(
                            map(
                                sql.Identifier,
                                ("workspace_id", "record_key", "revision"),
                            )
                        ),
                    )
                )
                tables[table] = [
                    dict(zip(columns, row, strict=True))
                    for row in cursor.fetchall()
                ]
        connection.commit()
    return {
        "artifact_kind": "platform_specspace_state_database_backup",
        "schema_version": 1,
        "tables": tables,
    }


def _initialize_queue_schema(database_url: str) -> None:
    try:
        from scripts import hosted_managed_operation_postgres as postgres_module
    except ImportError:
        import hosted_managed_operation_postgres as postgres_module
    queue = postgres_module.PostgreSQLManagedOperationQueue(database_url)
    queue.close()


def _initialize_state_schema(database_url: str) -> None:
    try:
        from scripts import specspace_state_postgres as state_postgres
    except ImportError:
        import specspace_state_postgres as state_postgres
    store = state_postgres.PostgreSQLSpecSpaceStateStore(database_url)
    store.close()


def _rebuild_state_mirror(
    database_url: str,
    mirror_root: Path,
) -> dict[str, int]:
    try:
        from scripts import specspace_state_postgres as state_postgres
        from scripts import specspace_state_service as state_service
    except ImportError:
        import specspace_state_postgres as state_postgres
        import specspace_state_service as state_service
    service = state_service.SpecSpaceStateService(
        store_factory=lambda: state_postgres.PostgreSQLSpecSpaceStateStore(
            database_url
        ),
        adapter="postgresql",
        mirror_root=mirror_root,
        now_iso=lambda: datetime.now(timezone.utc).isoformat(),
    )
    return service.mirror_summary


def _restore_database_export(database_url: str, export: dict[str, Any]) -> None:
    if export.get("artifact_kind") != "platform_hosted_managed_queue_backup":
        raise HostedBackupError("queue backup artifact kind is invalid")
    if export.get("schema_version") != 1:
        raise HostedBackupError("queue backup schema version is unsupported")
    tables = export.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(QUEUE_TABLES):
        raise HostedBackupError("queue backup table set is invalid")
    _initialize_queue_schema(database_url)
    psycopg, sql = _driver()
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for table in QUEUE_TABLES:
                rows = tables[table]
                columns = TABLE_COLUMNS[table]
                if not isinstance(rows, list):
                    raise HostedBackupError("queue backup rows must be arrays")
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise HostedBackupError("queue backup row shape is invalid")
                    cursor.execute(
                        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table),
                            sql.SQL(", ").join(map(sql.Identifier, columns)),
                            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                        ),
                        [row[column] for column in columns],
                    )
            events = tables["managed_operation_events"]
            if events:
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence('managed_operation_events', "
                    "'event_id'), (SELECT MAX(event_id) FROM managed_operation_events))"
                )


def _restore_state_database_export(
    database_url: str,
    export: dict[str, Any],
) -> None:
    if export.get("artifact_kind") != "platform_specspace_state_database_backup":
        raise HostedBackupError("SpecSpace state backup artifact kind is invalid")
    if export.get("schema_version") != 1:
        raise HostedBackupError("SpecSpace state backup schema version is unsupported")
    tables = export.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(STATE_TABLES):
        raise HostedBackupError("SpecSpace state backup table set is invalid")
    _initialize_state_schema(database_url)
    psycopg, sql = _driver()
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for table in STATE_TABLES:
                rows = tables[table]
                columns = STATE_TABLE_COLUMNS[table]
                if not isinstance(rows, list):
                    raise HostedBackupError(
                        "SpecSpace state backup rows must be arrays"
                    )
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise HostedBackupError(
                            "SpecSpace state backup row shape is invalid"
                        )
                    content = row["content_json"]
                    if not isinstance(content, dict):
                        raise HostedBackupError(
                            "SpecSpace state backup content must be an object"
                        )
                    encoded_content = json.dumps(
                        content,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if (
                        hashlib.sha256(encoded_content.encode("utf-8")).hexdigest()
                        != row["content_sha256"]
                    ):
                        raise HostedBackupError(
                            "SpecSpace state backup content digest mismatch"
                        )
                    values = [
                        encoded_content if column == "content_json" else row[column]
                        for column in columns
                    ]
                    placeholders = [
                        (
                            sql.SQL("{}::jsonb").format(sql.Placeholder())
                            if column == "content_json"
                            else sql.Placeholder()
                        )
                        for column in columns
                    ]
                    cursor.execute(
                        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table),
                            sql.SQL(", ").join(map(sql.Identifier, columns)),
                            sql.SQL(", ").join(placeholders),
                        ),
                        values,
                    )


def _artifact_inventory(artifact_root: Path) -> list[dict[str, Any]]:
    runs_root = artifact_root / "runs"
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise HostedBackupError("artifact root must contain a regular runs directory")
    inventory: list[dict[str, Any]] = []
    for path in sorted(runs_root.rglob("*")):
        if path.is_symlink():
            raise HostedBackupError("artifact backup refuses symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(artifact_root).as_posix()
        inventory.append(
            {
                "logical_ref": relative,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return inventory


def _write_artifact_archive(
    *, artifact_root: Path, inventory: list[dict[str, Any]], output: Path
) -> None:
    with tarfile.open(output, "w:gz") as archive:
        for item in inventory:
            logical_ref = str(item["logical_ref"])
            archive.add(
                artifact_root / logical_ref,
                arcname=logical_ref,
                recursive=False,
            )


def create_backup(
    *,
    database_url_file: Path,
    state_database_url_file: Path,
    artifact_root: Path,
    backup_root: Path,
    backup_id: str,
) -> dict[str, Any]:
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise HostedBackupError("backup id is invalid")
    if not backup_root.is_absolute() or backup_root.is_symlink():
        raise HostedBackupError("backup root must be an absolute regular directory")
    database_url = _database_url(database_url_file)
    state_database_url = _database_url(state_database_url_file)
    if database_url == state_database_url:
        raise HostedBackupError(
            "SpecSpace state database must be isolated from the queue database"
        )
    backup_root.mkdir(parents=True, exist_ok=True)
    destination = backup_root / backup_id
    if destination.exists():
        raise HostedBackupError("backup destination already exists")
    destination.mkdir(mode=0o700)
    dump_path = destination / "managed-operations.json"
    state_dump_path = destination / "specspace-state.json"
    archive_path = destination / "workspace-artifacts.tar.gz"
    try:
        database_export = _database_export(database_url)
        state_database_export = _state_database_export(state_database_url)
        exported_tables = database_export["tables"]
        status_counts: dict[str, int] = {}
        for row in exported_tables["managed_operation_jobs"]:
            status = str(row["status"])
            status_counts[status] = status_counts.get(status, 0) + 1
        active_count = sum(
            status_counts.get(status, 0) for status in ("queued", "leased", "running")
        )
        if active_count or exported_tables["managed_operation_locks"]:
            raise HostedBackupError("backup requires a drained queue without active locks")
        dump_path.write_text(
            json.dumps(database_export, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        state_dump_path.write_text(
            json.dumps(state_database_export, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        counts = {table: len(rows) for table, rows in exported_tables.items()}
        state_counts = {
            table: len(rows)
            for table, rows in state_database_export["tables"].items()
        }
        inventory = _artifact_inventory(artifact_root)
        _write_artifact_archive(
            artifact_root=artifact_root,
            inventory=inventory,
            output=archive_path,
        )
        _verify_artifact_archive(archive_path, inventory)
        if _artifact_inventory(artifact_root) != inventory:
            raise HostedBackupError("artifact tree changed during backup")
        report = {
            "artifact_kind": "platform_hosted_managed_runtime_backup_report",
            "contract_ref": "platform.hosted-managed.runtime-backup.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ok": True,
            "backup_id": backup_id,
            "summary": {
                "status": "backup_ready",
                "database_export_sha256": sha256_file(dump_path),
                "database_backup_schema_version": 1,
                "state_database_export_sha256": sha256_file(state_dump_path),
                "state_database_backup_schema_version": 1,
                "artifact_archive_sha256": sha256_file(archive_path),
                "artifact_file_count": len(inventory),
                "database_row_counts": counts,
                "state_database_row_counts": state_counts,
            },
            "artifact_inventory": inventory,
            "privacy_boundary": {
                "public_safe": False,
                "contains_private_workspace_artifacts": True,
                "contains_database_rows": True,
                "contains_private_specspace_state": True,
                "contains_secret_values": False,
            },
            "authority_boundary": {
                "may_restore_production_database": False,
                "may_execute_managed_operations": False,
                "may_mutate_specs": False,
                "may_create_git_review": False,
            },
        }
        report_path = destination / "backup-report.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    except Exception:
        for path in destination.iterdir():
            path.unlink()
        destination.rmdir()
        raise


def _load_backup(backup_root: Path, backup_id: str) -> tuple[Path, dict[str, Any]]:
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise HostedBackupError("backup id is invalid")
    destination = backup_root / backup_id
    report_path = destination / "backup-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HostedBackupError("backup report is unavailable or invalid") from exc
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise HostedBackupError("backup report is not ready")
    return destination, report


def _verify_artifact_archive(
    archive_path: Path, inventory: list[dict[str, Any]]
) -> None:
    expected = {str(item["logical_ref"]): item for item in inventory}
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise HostedBackupError("artifact archive inventory mismatch")
        for member in members:
            logical = PurePosixPath(member.name)
            if logical.is_absolute() or ".." in logical.parts or not member.isfile():
                raise HostedBackupError("artifact archive contains unsafe member")
            stream = archive.extractfile(member)
            if stream is None:
                raise HostedBackupError("artifact archive member is unreadable")
            content = stream.read()
            if hashlib.sha256(content).hexdigest() != expected[member.name]["sha256"]:
                raise HostedBackupError("artifact archive digest mismatch")


def restore_smoke(
    *,
    database_url_file: Path,
    state_database_url_file: Path,
    backup_root: Path,
    backup_id: str,
) -> dict[str, Any]:
    destination, backup = _load_backup(backup_root, backup_id)
    dump_path = destination / "managed-operations.json"
    state_dump_path = destination / "specspace-state.json"
    archive_path = destination / "workspace-artifacts.tar.gz"
    summary = backup.get("summary")
    inventory = backup.get("artifact_inventory")
    if not isinstance(summary, dict) or not isinstance(inventory, list):
        raise HostedBackupError("backup report contract is incomplete")
    if sha256_file(dump_path) != summary.get("database_export_sha256"):
        raise HostedBackupError("database export digest mismatch")
    if sha256_file(state_dump_path) != summary.get(
        "state_database_export_sha256"
    ):
        raise HostedBackupError("SpecSpace state database export digest mismatch")
    if sha256_file(archive_path) != summary.get("artifact_archive_sha256"):
        raise HostedBackupError("artifact archive digest mismatch")
    _verify_artifact_archive(archive_path, inventory)

    source_url = _database_url(database_url_file)
    state_source_url = _database_url(state_database_url_file)
    if source_url == state_source_url:
        raise HostedBackupError(
            "SpecSpace state database must be isolated from the queue database"
        )
    psycopg, sql = _driver()
    parsed = urlsplit(source_url)
    source_database = parsed.path.lstrip("/")
    if not source_database:
        raise HostedBackupError("database URL must include a database name")
    restore_database = f"platform_restore_smoke_{os.getpid()}"
    state_restore_database = f"specspace_state_restore_smoke_{os.getpid()}"
    admin_url = _replace_database(source_url, "postgres")
    restore_url = _replace_database(source_url, restore_database)
    state_admin_url = _replace_database(state_source_url, "postgres")
    state_restore_url = _replace_database(
        state_source_url,
        state_restore_database,
    )
    created = False
    state_created = False
    state_mirror_root: Path | None = None
    state_mirror_record_count = 0
    state_mirror_removed = False
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_database))
                )
                created = True
        try:
            database_export = json.loads(dump_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HostedBackupError("database export is invalid") from exc
        if not isinstance(database_export, dict):
            raise HostedBackupError("database export must be an object")
        _restore_database_export(
            restore_url,
            database_export,
        )
        restored_counts = _row_counts(restore_url)
        expected_counts = summary.get("database_row_counts")
        if restored_counts != expected_counts:
            raise HostedBackupError("restored database row counts differ from backup")
        with psycopg.connect(state_admin_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(state_restore_database)
                    )
                )
                state_created = True
        try:
            state_database_export = json.loads(
                state_dump_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise HostedBackupError(
                "SpecSpace state database export is invalid"
            ) from exc
        if not isinstance(state_database_export, dict):
            raise HostedBackupError(
                "SpecSpace state database export must be an object"
            )
        _restore_state_database_export(
            state_restore_url,
            state_database_export,
        )
        restored_state_counts = _state_row_counts(state_restore_url)
        expected_state_counts = summary.get("state_database_row_counts")
        if restored_state_counts != expected_state_counts:
            raise HostedBackupError(
                "restored SpecSpace state row counts differ from backup"
            )
        state_mirror_root = Path(
            tempfile.mkdtemp(prefix="specspace-state-restore-smoke-")
        )
        mirror_summary = _rebuild_state_mirror(
            state_restore_url,
            state_mirror_root,
        )
        expected_mirror_count = sum(
            1
            for row in state_database_export["tables"][
                "specspace_state_records"
            ]
            if row["lifecycle_state"] != "deleted"
        )
        if (
            mirror_summary.get("database_record_count")
            != restored_state_counts["specspace_state_records"]
            or mirror_summary.get("materialized_record_count")
            != expected_mirror_count
        ):
            raise HostedBackupError(
                "restored SpecSpace state mirror differs from backup"
            )
        state_mirror_record_count = expected_mirror_count
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(restore_database)
                        )
                    )
        if state_created:
            with psycopg.connect(state_admin_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(state_restore_database)
                        )
                    )
        if state_mirror_root is not None:
            shutil.rmtree(state_mirror_root)
            state_mirror_removed = not state_mirror_root.exists()

    return {
        "artifact_kind": "platform_hosted_managed_runtime_restore_smoke_report",
        "contract_ref": "platform.hosted-managed.runtime-restore-smoke.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "backup_id": backup_id,
        "summary": {
            "status": "restore_smoke_passed",
            "database_row_counts_verified": True,
            "state_database_row_counts_verified": True,
            "state_mirror_record_count_verified": True,
            "state_mirror_record_count": state_mirror_record_count,
            "artifact_inventory_verified": True,
            "artifact_file_count": len(inventory),
            "temporary_database_removed": True,
            "temporary_state_mirror_removed": state_mirror_removed,
        },
        "privacy_boundary": {
            "public_safe": True,
            "contains_secret_values": False,
            "contains_local_paths": False,
            "contains_workspace_artifact_content": False,
        },
        "authority_boundary": {
            "may_restore_production_database": False,
            "may_execute_managed_operations": False,
            "may_mutate_specs": False,
            "may_create_git_review": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore-smoke"):
        command = subcommands.add_parser(name)
        command.add_argument("--database-url-file", required=True)
        command.add_argument("--state-database-url-file", required=True)
        command.add_argument("--backup-root", required=True)
        command.add_argument("--backup-id", required=True)
        command.add_argument("--output")
        if name == "backup":
            command.add_argument("--artifact-root", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            report = create_backup(
                database_url_file=Path(args.database_url_file),
                state_database_url_file=Path(args.state_database_url_file),
                artifact_root=Path(args.artifact_root),
                backup_root=Path(args.backup_root),
                backup_id=args.backup_id,
            )
        else:
            report = restore_smoke(
                database_url_file=Path(args.database_url_file),
                state_database_url_file=Path(args.state_database_url_file),
                backup_root=Path(args.backup_root),
                backup_id=args.backup_id,
            )
    except (HostedBackupError, OSError, tarfile.TarError) as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_runtime_maintenance_error",
            "ok": False,
            "diagnostics": [str(exc)],
        }
    except Exception:
        report = {
            "artifact_kind": "platform_hosted_managed_runtime_maintenance_error",
            "ok": False,
            "diagnostics": ["hosted runtime maintenance operation failed"],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
