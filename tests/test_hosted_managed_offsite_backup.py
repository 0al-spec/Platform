from __future__ import annotations

import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import textwrap
import unittest

from scripts import hosted_managed_offsite_backup as offsite


PLAINTEXT_ARCHIVE = b"private hosted backup stream"


class _BrokenPipeInput(io.BytesIO):
    def write(self, data: bytes) -> int:
        raise BrokenPipeError("age exited before consuming input")


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: io.BytesIO | None = None,
        stdin: io.BytesIO | None = None,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stdin = stdin
        self.completed = False

    def poll(self) -> int | None:
        return self.returncode if self.completed else None

    def wait(self) -> int:
        self.completed = True
        return self.returncode

    def terminate(self) -> None:
        self.completed = True


class OffsiteBackupTests(unittest.TestCase):
    def executable(self, root: Path, name: str, source: str) -> Path:
        path = root / name
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)
        return path

    def fixture(self, root: Path) -> dict:
        identity = root / "identity"
        identity.write_text("not-a-real-private-key", encoding="utf-8")
        identity.chmod(0o600)
        recipient = root / "recipient.pub"
        recipient.write_text("ssh-ed25519 public-test", encoding="utf-8")
        ssh = self.executable(
            root,
            "fake-ssh",
            f"""
            #!/usr/bin/env python3
            import json
            import sys
            if any(value.endswith("backup-report.json") for value in sys.argv):
                print(json.dumps({{
                    "artifact_kind": "platform_hosted_managed_runtime_backup_report",
                    "contract_ref": "platform.hosted-managed.runtime-backup.v1",
                    "ok": True,
                    "backup_id": "production-20260714t120000z",
                    "summary": {{"status": "backup_ready"}},
                }}))
            elif any(
                value.endswith("restore-smoke-report.json") for value in sys.argv
            ):
                print(json.dumps({{
                    "artifact_kind": (
                        "platform_hosted_managed_runtime_restore_smoke_report"
                    ),
                    "contract_ref": (
                        "platform.hosted-managed.runtime-restore-smoke.v1"
                    ),
                    "ok": True,
                    "backup_id": "production-20260714t120000z",
                    "summary": {{
                        "status": "restore_smoke_passed",
                        "database_row_counts_verified": True,
                        "state_database_row_counts_verified": True,
                        "state_mirror_record_count_verified": True,
                        "artifact_inventory_verified": True,
                        "temporary_database_removed": True,
                        "temporary_state_mirror_removed": True,
                    }},
                }}))
            elif "tar" in sys.argv:
                sys.stdout.buffer.write({PLAINTEXT_ARCHIVE!r})
            """,
        )
        age = self.executable(
            root,
            "fake-age",
            """
            #!/usr/bin/env python3
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.write_bytes(b"age-encryption.org/v1" + sys.stdin.buffer.read()[::-1])
            """,
        )
        return {
            "backup_id": "production-20260714t120000z",
            "ssh_target": "root@managed.example.test",
            "ssh_identity": identity,
            "age_recipient_file": recipient,
            "output_dir": root / "encrypted",
            "ssh_bin": str(ssh),
            "age_bin": str(age),
        }

    def test_streams_directly_to_age_and_writes_public_safe_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = offsite.export_offsite_backup(**self.fixture(root))

            output = root / "encrypted" / "production-20260714t120000z.tar.age"
            self.assertTrue(report["ok"])
            self.assertEqual(
                report["plaintext_tar_stream_sha256"],
                hashlib.sha256(PLAINTEXT_ARCHIVE).hexdigest(),
            )
            self.assertTrue(output.read_bytes().startswith(b"age-encryption.org/v1"))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertFalse(any(path.suffix == ".tar" for path in root.rglob("*")))
            self.assertNotIn(temp_dir, str(report))
            self.assertNotIn("managed.example.test", str(report))

    def test_ssh_option_terminator_precedes_destination(self) -> None:
        prefix = offsite._ssh_prefix(
            ssh_bin="ssh",
            ssh_target="root@managed.example.test",
            ssh_identity=Path("/private/key"),
        )
        self.assertEqual(prefix[-2:], ["--", "root@managed.example.test"])

    def test_cli_refuses_report_path_that_would_overwrite_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            archive = output_dir / "production-20260714t120000z.tar.age"
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                SystemExit
            ) as raised:
                offsite.main(
                    [
                        "--backup-id",
                        "production-20260714t120000z",
                        "--ssh-target",
                        "root@managed.example.test",
                        "--ssh-identity",
                        "/private/key",
                        "--age-recipient-file",
                        "/public/key",
                        "--output-dir",
                        str(output_dir),
                        "--output",
                        str(archive),
                    ]
                )
            self.assertEqual(raised.exception.code, 2)

    def test_refuses_overwrite_and_unsafe_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            offsite.export_offsite_backup(**fixture)
            with self.assertRaisesRegex(
                offsite.OffsiteBackupError, "already exists"
            ):
                offsite.export_offsite_backup(**fixture)
            fixture["backup_id"] = "../backup"
            with self.assertRaisesRegex(offsite.OffsiteBackupError, "invalid"):
                offsite.export_offsite_backup(**fixture)

    def test_failed_age_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            fixture["age_bin"] = str(
                self.executable(
                    root,
                    "failing-age",
                    """
                    #!/usr/bin/env python3
                    from pathlib import Path
                    import sys
                    output = Path(sys.argv[sys.argv.index("--output") + 1])
                    output.write_bytes(b"partial")
                    raise SystemExit(1)
                    """,
                )
            )
            with self.assertRaisesRegex(offsite.OffsiteBackupError, "age encryption"):
                offsite.export_offsite_backup(**fixture)
            self.assertEqual(list((root / "encrypted").iterdir()), [])

    def test_early_age_exit_is_classified_after_broken_pipe(self) -> None:
        processes = iter(
            (
                _FakeProcess(
                    returncode=0,
                    stdout=io.BytesIO(PLAINTEXT_ARCHIVE),
                ),
                _FakeProcess(
                    returncode=1,
                    stdin=_BrokenPipeInput(),
                ),
            )
        )

        with self.assertRaisesRegex(offsite.OffsiteBackupError, "age encryption"):
            offsite._stream_encrypted_archive(
                ssh_command=["fake-ssh"],
                age_command=["fake-age"],
                temporary_output=Path("unused.tar.age"),
                popen=lambda *args, **kwargs: next(processes),
            )

    def test_remote_failure_keeps_precedence_without_broken_pipe(self) -> None:
        processes = iter(
            (
                _FakeProcess(returncode=1, stdout=io.BytesIO()),
                _FakeProcess(returncode=1, stdin=io.BytesIO()),
            )
        )

        with self.assertRaisesRegex(offsite.OffsiteBackupError, "remote backup"):
            offsite._stream_encrypted_archive(
                ssh_command=["fake-ssh"],
                age_command=["fake-age"],
                temporary_output=Path("unused.tar.age"),
                popen=lambda *args, **kwargs: next(processes),
            )

    def test_failed_restore_smoke_report_blocks_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = self.fixture(root)
            fixture["ssh_bin"] = str(
                self.executable(
                    root,
                    "failed-restore-ssh",
                    """
                    #!/usr/bin/env python3
                    import json
                    import sys
                    if any(
                        value.endswith("backup-report.json") for value in sys.argv
                    ):
                        print(json.dumps({
                            "artifact_kind": (
                                "platform_hosted_managed_runtime_backup_report"
                            ),
                            "contract_ref": (
                                "platform.hosted-managed.runtime-backup.v1"
                            ),
                            "ok": True,
                            "backup_id": "production-20260714t120000z",
                            "summary": {"status": "backup_ready"},
                        }))
                    elif any(
                        value.endswith("restore-smoke-report.json")
                        for value in sys.argv
                    ):
                        print(json.dumps({
                            "artifact_kind": (
                                "platform_hosted_managed_runtime_restore_smoke_report"
                            ),
                            "contract_ref": (
                                "platform.hosted-managed.runtime-restore-smoke.v1"
                            ),
                            "ok": False,
                            "backup_id": "production-20260714t120000z",
                            "summary": {"status": "restore_smoke_failed"},
                        }))
                    """,
                )
            )
            with self.assertRaisesRegex(
                offsite.OffsiteBackupError, "restore-smoke report is not ready"
            ):
                offsite.export_offsite_backup(**fixture)
            self.assertEqual(list((root / "encrypted").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
