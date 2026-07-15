"""Stream one private hosted backup into an encrypted off-host archive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

try:
    from scripts.hosted_managed_runtime_backup import BACKUP_ID_PATTERN
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    from hosted_managed_runtime_backup import BACKUP_ID_PATTERN


DEFAULT_REMOTE_BACKUP_ROOT = "/srv/0al/backups"
DEFAULT_OUTPUT_DIR = Path.home() / "Backups" / "0AL" / "Platform"
SSH_TARGET_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}@)?"
    r"(?:[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}|\[[0-9a-fA-F:]+\])$"
)
MINIMUM_HOST_PYTHON = (3, 12)
MAXIMUM_HOST_PYTHON = (3, 15)
MAXIMUM_REMOTE_REPORT_BYTES = 16 * 1024 * 1024


class OffsiteBackupError(RuntimeError):
    """The private backup cannot be exported without weakening its contract."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
PopenFactory = Callable[..., subprocess.Popen[bytes]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_supported_python(version_info: tuple[int, ...] | Any) -> None:
    version = tuple(version_info[:2])
    if not MINIMUM_HOST_PYTHON <= version < MAXIMUM_HOST_PYTHON:
        raise OffsiteBackupError(
            "off-host backup export requires Python 3.12, 3.13, or 3.14"
        )


def _validate_regular_file(path: Path, *, label: str) -> None:
    if not path.is_absolute():
        raise OffsiteBackupError(f"{label} must be absolute")
    if path.is_symlink() or not path.is_file():
        raise OffsiteBackupError(f"{label} must be a regular file")


def _ssh_prefix(*, ssh_bin: str, ssh_target: str, ssh_identity: Path) -> list[str]:
    return [
        ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        str(ssh_identity),
        "--",
        ssh_target,
    ]


def _preflight_remote_backup(
    *,
    ssh_prefix: list[str],
    backup_id: str,
    remote_backup_root: str,
    runner: Runner,
) -> None:
    backup_dir = f"{remote_backup_root}/{backup_id}"
    command = [
        *ssh_prefix,
        "test",
        "-d",
        backup_dir,
        "-a",
        "!",
        "-L",
        backup_dir,
        "-a",
        "-f",
        f"{backup_dir}/backup-report.json",
        "-a",
        "!",
        "-L",
        f"{backup_dir}/backup-report.json",
        "-a",
        "-f",
        f"{backup_dir}/restore-smoke-report.json",
        "-a",
        "!",
        "-L",
        f"{backup_dir}/restore-smoke-report.json",
    ]
    completed = runner(
        command, capture_output=True, text=True, check=False, timeout=30
    )
    if completed.returncode != 0:
        raise OffsiteBackupError(
            "remote backup or isolated restore-smoke evidence is unavailable"
        )
    backup_report = _load_remote_report(
        ssh_prefix=ssh_prefix,
        report_path=f"{backup_dir}/backup-report.json",
        runner=runner,
        label="backup",
    )
    restore_report = _load_remote_report(
        ssh_prefix=ssh_prefix,
        report_path=f"{backup_dir}/restore-smoke-report.json",
        runner=runner,
        label="restore smoke",
    )
    backup_summary = backup_report.get("summary")
    if (
        backup_report.get("artifact_kind")
        != "platform_hosted_managed_runtime_backup_report"
        or backup_report.get("contract_ref")
        != "platform.hosted-managed.runtime-backup.v1"
        or backup_report.get("ok") is not True
        or backup_report.get("backup_id") != backup_id
        or not isinstance(backup_summary, dict)
        or backup_summary.get("status") != "backup_ready"
    ):
        raise OffsiteBackupError("remote backup report is not ready")
    restore_summary = restore_report.get("summary")
    if (
        restore_report.get("artifact_kind")
        != "platform_hosted_managed_runtime_restore_smoke_report"
        or restore_report.get("contract_ref")
        != "platform.hosted-managed.runtime-restore-smoke.v1"
        or restore_report.get("ok") is not True
        or restore_report.get("backup_id") != backup_id
        or not isinstance(restore_summary, dict)
        or restore_summary.get("status") != "restore_smoke_passed"
        or restore_summary.get("database_row_counts_verified") is not True
        or restore_summary.get("artifact_inventory_verified") is not True
        or restore_summary.get("temporary_database_removed") is not True
    ):
        raise OffsiteBackupError("remote restore-smoke report is not ready")


def _load_remote_report(
    *,
    ssh_prefix: list[str],
    report_path: str,
    runner: Runner,
    label: str,
) -> dict[str, Any]:
    completed = runner(
        [*ssh_prefix, "cat", report_path],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if (
        completed.returncode != 0
        or len(completed.stdout.encode("utf-8")) > MAXIMUM_REMOTE_REPORT_BYTES
    ):
        raise OffsiteBackupError(f"remote {label} report is unavailable")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OffsiteBackupError(f"remote {label} report is invalid") from exc
    if not isinstance(report, dict):
        raise OffsiteBackupError(f"remote {label} report must be an object")
    return report


def _stream_encrypted_archive(
    *,
    ssh_command: list[str],
    age_command: list[str],
    temporary_output: Path,
    popen: PopenFactory,
) -> tuple[str, int]:
    plaintext_digest = hashlib.sha256()
    ssh_process = popen(
        ssh_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    age_process: subprocess.Popen[bytes] | None = None
    try:
        age_process = popen(
            age_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ssh_process.stdout is None or age_process.stdin is None:
            raise OffsiteBackupError("backup export pipeline is unavailable")
        broken_pipe: BrokenPipeError | None = None
        try:
            while chunk := ssh_process.stdout.read(1024 * 1024):
                plaintext_digest.update(chunk)
                age_process.stdin.write(chunk)
            age_process.stdin.close()
        except BrokenPipeError as exc:
            broken_pipe = exc
            if ssh_process.poll() is None:
                ssh_process.terminate()
        ssh_returncode = ssh_process.wait()
        age_returncode = age_process.wait()
        if broken_pipe is not None:
            if age_returncode != 0:
                raise OffsiteBackupError("age encryption failed") from broken_pipe
            raise OffsiteBackupError("encrypted backup stream failed") from broken_pipe
        if ssh_returncode != 0:
            raise OffsiteBackupError("remote backup stream failed")
        if age_returncode != 0:
            raise OffsiteBackupError("age encryption failed")
    except (BrokenPipeError, OSError) as exc:
        raise OffsiteBackupError("encrypted backup stream failed") from exc
    finally:
        if ssh_process.poll() is None:
            ssh_process.terminate()
            ssh_process.wait()
        if age_process is not None and age_process.poll() is None:
            age_process.terminate()
            age_process.wait()
        for stream in (ssh_process.stdout,):
            if stream is not None:
                stream.close()
        if age_process is not None:
            for stream in (age_process.stdin,):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except OSError:
                        pass
    return plaintext_digest.hexdigest(), temporary_output.stat().st_size


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_offsite_backup(
    *,
    backup_id: str,
    ssh_target: str,
    ssh_identity: Path,
    age_recipient_file: Path,
    output_dir: Path,
    remote_backup_root: str = DEFAULT_REMOTE_BACKUP_ROOT,
    ssh_bin: str = "ssh",
    age_bin: str = "age",
    runner: Runner = subprocess.run,
    popen: PopenFactory = subprocess.Popen,
) -> dict[str, Any]:
    if not BACKUP_ID_PATTERN.fullmatch(backup_id):
        raise OffsiteBackupError("backup id is invalid")
    if not SSH_TARGET_PATTERN.fullmatch(ssh_target):
        raise OffsiteBackupError("SSH target is invalid")
    if remote_backup_root != DEFAULT_REMOTE_BACKUP_ROOT:
        raise OffsiteBackupError("remote backup root is not allowlisted")
    _validate_regular_file(ssh_identity, label="SSH identity")
    _validate_regular_file(age_recipient_file, label="age recipient file")
    if not output_dir.is_absolute() or output_dir.is_symlink():
        raise OffsiteBackupError("output directory must be an absolute regular path")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = output_dir / f"{backup_id}.tar.age"
    temporary = output_dir / f".{backup_id}.tar.age.tmp-{os.getpid()}"
    if output.exists() or temporary.exists():
        raise OffsiteBackupError("encrypted backup output already exists")

    ssh_prefix = _ssh_prefix(
        ssh_bin=ssh_bin,
        ssh_target=ssh_target,
        ssh_identity=ssh_identity,
    )
    _preflight_remote_backup(
        ssh_prefix=ssh_prefix,
        backup_id=backup_id,
        remote_backup_root=remote_backup_root,
        runner=runner,
    )
    ssh_command = [
        *ssh_prefix,
        "tar",
        "--create",
        "--gzip",
        "--directory",
        remote_backup_root,
        "--",
        backup_id,
    ]
    age_command = [
        age_bin,
        "--recipients-file",
        str(age_recipient_file),
        "--output",
        str(temporary),
    ]
    try:
        plaintext_sha256, encrypted_size = _stream_encrypted_archive(
            ssh_command=ssh_command,
            age_command=age_command,
            temporary_output=temporary,
            popen=popen,
        )
        temporary.chmod(0o600)
        with temporary.open("rb") as stream:
            age_header = stream.read(21)
        if age_header != b"age-encryption.org/v1":
            raise OffsiteBackupError("encrypted backup has an invalid age header")
        encrypted_sha256 = _sha256_file(temporary)
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "artifact_kind": "platform_hosted_managed_offsite_backup_report",
        "contract_ref": "platform.hosted-managed.offsite-backup.v1",
        "generated_at": _now_iso(),
        "ok": True,
        "backup_id": backup_id,
        "encrypted_archive_name": output.name,
        "plaintext_tar_stream_sha256": plaintext_sha256,
        "encrypted_archive_sha256": encrypted_sha256,
        "encrypted_size_bytes": encrypted_size,
        "summary": {"status": "offsite_backup_ready"},
        "privacy_boundary": {
            "public_safe": True,
            "includes_backup_payload": False,
            "includes_secret_values": False,
            "includes_private_key": False,
            "includes_local_paths": False,
            "includes_remote_host": False,
        },
        "authority_boundary": {
            "may_restore_production_database": False,
            "may_decrypt_backup": False,
            "may_read_private_key": False,
            "may_enqueue_operations": False,
            "may_execute_managed_operations": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--ssh-identity", required=True, type=Path)
    parser.add_argument("--age-recipient-file", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    _require_supported_python(sys.version_info)
    resolved_output_dir = args.output_dir.expanduser().resolve()
    if args.output is not None:
        report_output = args.output.expanduser().resolve()
        archive_output = resolved_output_dir / f"{args.backup_id}.tar.age"
        if report_output == archive_output:
            parser.error("--output must differ from the encrypted archive path")
    try:
        report = export_offsite_backup(
            backup_id=args.backup_id,
            ssh_target=args.ssh_target,
            ssh_identity=args.ssh_identity.expanduser().resolve(),
            age_recipient_file=args.age_recipient_file.expanduser().resolve(),
            output_dir=resolved_output_dir,
        )
    except OffsiteBackupError as exc:
        report = {
            "artifact_kind": "platform_hosted_managed_offsite_backup_report",
            "contract_ref": "platform.hosted-managed.offsite-backup.v1",
            "generated_at": _now_iso(),
            "ok": False,
            "backup_id": args.backup_id,
            "diagnostics": [str(exc)],
            "summary": {"status": "offsite_backup_blocked"},
        }
    except OSError:
        report = {
            "artifact_kind": "platform_hosted_managed_offsite_backup_report",
            "contract_ref": "platform.hosted-managed.offsite-backup.v1",
            "generated_at": _now_iso(),
            "ok": False,
            "backup_id": args.backup_id,
            "diagnostics": ["off-host backup filesystem operation failed"],
            "summary": {"status": "offsite_backup_blocked"},
        }
    if args.output is not None:
        report_output.parent.mkdir(parents=True, exist_ok=True)
        report_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
