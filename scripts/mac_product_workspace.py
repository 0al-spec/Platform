#!/usr/bin/env python3
"""Operate the single-operator Mac product-workspace profile."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    from scripts import platform as platform_cli
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import platform as platform_cli  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYCHAIN_SERVICE = "0AL SpecSpace production smoke"
DEFAULT_OPERATOR_USERNAME = "operator"
MAC_RESTART_E2E_WORKSPACE_ID = "mac-specification-marathon"
CHILD_ENVIRONMENT_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "SSH_AUTH_SOCK",
    "TMPDIR",
    "USER",
)


@dataclass(frozen=True)
class MacProductConfig:
    org_root: Path
    platform_dir: Path
    specgraph_dir: Path
    specgraph_runs_dir: Path
    specspace_dir: Path
    dialog_dir: Path
    state_dir: Path
    product_workspace_root_dir: Path
    product_workspace_catalog: Path
    runtime_dir: Path
    api_port: int
    ui_port: int
    operator_username: str
    keychain_service: str

    @property
    def backend_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def ui_url(self) -> str:
        return f"http://127.0.0.1:{self.ui_port}"


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class OwnedProcess:
    process_id: str
    pid: int
    expected_command_tokens: tuple[str, ...]
    log_path: str


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default.resolve()


def config_from_environment(args: argparse.Namespace) -> MacProductConfig:
    org_root = _path_from_env("ORG_ROOT", REPO_ROOT.parent)
    specgraph_dir = _path_from_env("SPECGRAPH_DIR", org_root / "SpecGraph")
    return MacProductConfig(
        org_root=org_root,
        platform_dir=_path_from_env("PLATFORM_DIR", REPO_ROOT),
        specgraph_dir=specgraph_dir,
        specgraph_runs_dir=_path_from_env(
            "SPECGRAPH_RUNS_DIR", specgraph_dir / "runs"
        ),
        specspace_dir=_path_from_env("SPECSPACE_DIR", org_root / "SpecSpace"),
        dialog_dir=_path_from_env(
            "DIALOG_DIR",
            org_root / "ChatGPTDialogs" / "canonical_json",
        ),
        state_dir=_path_from_env(
            "SPECSPACE_STATE_DIR",
            Path.home()
            / "Library"
            / "Application Support"
            / "0AL"
            / "SpecSpace"
            / "state",
        ),
        product_workspace_root_dir=_path_from_env(
            "SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR",
            Path.home()
            / "Library"
            / "Application Support"
            / "0AL"
            / "SpecSpace"
            / "workspaces",
        ),
        product_workspace_catalog=_path_from_env(
            "SPECSPACE_PRODUCT_WORKSPACE_CATALOG",
            Path.home()
            / "Library"
            / "Application Support"
            / "0AL"
            / "SpecSpace"
            / "workspaces.local.yaml",
        ),
        runtime_dir=_path_from_env(
            "SPECSPACE_MAC_PRODUCT_RUNTIME_DIR",
            Path.home()
            / "Library"
            / "Caches"
            / "0AL"
            / "SpecSpace"
            / "mac-product-workspace",
        ),
        api_port=args.api_port,
        ui_port=args.ui_port,
        operator_username=args.operator_auth_username,
        keychain_service=args.operator_auth_keychain_service,
    )


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def readiness_checks(config: MacProductConfig) -> list[ReadinessCheck]:
    checks: list[ReadinessCheck] = []

    def add(check_id: str, ok: bool, detail: str) -> None:
        checks.append(ReadinessCheck(check_id=check_id, ok=ok, detail=detail))

    add("macos", sys.platform == "darwin", "macOS host required")
    for check_id, path in (
        ("platform_checkout", config.platform_dir),
        ("specgraph_checkout", config.specgraph_dir),
        ("specspace_checkout", config.specspace_dir),
        ("dialog_directory", config.dialog_dir),
    ):
        add(check_id, path.is_dir(), str(path))

    platform_python = config.platform_dir / ".venv" / "bin" / "python"
    specspace_server = config.specspace_dir / "viewer" / "server.py"
    graphspace_modules = config.specspace_dir / "graphspace" / "node_modules"
    add("platform_python", platform_python.is_file(), str(platform_python))
    add("specspace_server", specspace_server.is_file(), str(specspace_server))
    add("graphspace_dependencies", graphspace_modules.is_dir(), str(graphspace_modules))
    npm = shutil.which("npm")
    add("command_npm", npm is not None, npm or "npm not found")

    for label, port in (("api", config.api_port), ("ui", config.ui_port)):
        add(
            f"port_{label}_available",
            _port_available(port),
            f"127.0.0.1:{port}",
        )

    state_parent = config.state_dir.parent
    state_parent_ready = state_parent.is_dir() and os.access(state_parent, os.W_OK)
    if not state_parent.exists():
        ancestor = state_parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        state_parent_ready = ancestor.is_dir() and os.access(ancestor, os.W_OK)
    add("state_parent_writable", state_parent_ready, str(state_parent))
    runs_parent = config.specgraph_runs_dir.parent
    runs_parent_ready = runs_parent.is_dir() and os.access(runs_parent, os.W_OK)
    if not runs_parent.exists():
        ancestor = runs_parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        runs_parent_ready = ancestor.is_dir() and os.access(ancestor, os.W_OK)
    add("specgraph_runs_parent_writable", runs_parent_ready, str(runs_parent))
    for check_id, path in (
        ("product_workspace_root_parent_writable", config.product_workspace_root_dir),
        ("product_workspace_catalog_parent_writable", config.product_workspace_catalog),
    ):
        ancestor = path.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        add(
            check_id,
            ancestor.is_dir() and os.access(ancestor, os.W_OK),
            str(path.parent),
        )
    return checks


def _emit(payload: dict[str, object], *, output_format: str) -> int:
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status: {payload['status']}")
        for check in payload.get("checks", []):
            if isinstance(check, dict):
                marker = "ready" if check.get("ok") is True else "blocked"
                print(f"{marker:7} {check.get('check_id')}: {check.get('detail')}")
        for error in payload.get("errors", []):
            print(f"error: {error}")
        if payload.get("ui_url"):
            print(f"ui: {payload['ui_url']}")
        if payload.get("state_dir"):
            print(f"state: {payload['state_dir']}")
        if payload.get("specgraph_runs_dir"):
            print(f"runs: {payload['specgraph_runs_dir']}")
        if payload.get("product_workspace_root_dir"):
            print(f"workspaces: {payload['product_workspace_root_dir']}")
        if payload.get("product_workspace_catalog"):
            print(f"catalog: {payload['product_workspace_catalog']}")
        if payload.get("runtime_dir"):
            print(f"runtime: {payload['runtime_dir']}")
    return 0 if payload.get("ok") is True else 1


def doctor(config: MacProductConfig, *, output_format: str) -> int:
    checks = readiness_checks(config)
    ok = all(check.ok for check in checks)
    return _emit(
        {
            "artifact_kind": "platform_mac_product_workspace_readiness",
            "schema_version": 1,
            "ok": ok,
            "status": "ready" if ok else "blocked",
            "checks": [asdict(check) for check in checks],
            "ui_url": config.ui_url,
            "state_dir": str(config.state_dir),
            "specgraph_runs_dir": str(config.specgraph_runs_dir),
            "product_workspace_root_dir": str(config.product_workspace_root_dir),
            "product_workspace_catalog": str(config.product_workspace_catalog),
            "authority_boundary": {
                "browser_executes_shell": False,
                "specspace_executes_allowlisted_platform_operations": True,
                "direct_canonical_spec_mutation": False,
                "direct_ontology_mutation": False,
            },
        },
        output_format=output_format,
    )


def _runtime_environment(config: MacProductConfig) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in CHILD_ENVIRONMENT_KEYS
        if os.environ.get(key)
    }
    env.update(
        {
            "SPECSPACE_STATE_DIR": str(config.state_dir),
            "SPECGRAPH_RUNS_DIR": str(config.specgraph_runs_dir),
            "SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR": str(
                config.product_workspace_root_dir
            ),
            "SPECSPACE_PRODUCT_WORKSPACE_CATALOG": str(
                config.product_workspace_catalog
            ),
            "SPECSPACE_PLATFORM_DIR": str(config.platform_dir),
            "SPECSPACE_PLATFORM_EXECUTION_ENABLED": "true",
            "SPECSPACE_HOSTED_MANAGED_EXECUTION_ENABLED": "false",
        }
    )
    return env


def _ui_environment(config: MacProductConfig) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in CHILD_ENVIRONMENT_KEYS
        if os.environ.get(key)
    }
    env["SPECSPACE_API_PORT"] = str(config.api_port)
    return env


def _ensure_local_workspace_catalog(config: MacProductConfig) -> None:
    catalog = config.product_workspace_catalog
    catalog.parent.mkdir(parents=True, exist_ok=True)
    if catalog.exists():
        if catalog.is_symlink() or not catalog.is_file():
            raise platform_cli.PlatformError(
                f"product workspace catalog is not a regular file: {catalog}"
            )
        return
    content = (
        "schema_version: 1\n"
        "artifact_kind: platform_workspace_catalog\n"
        f"organization_root: {json.dumps(str(config.product_workspace_root_dir))}\n"
        "workspaces: []\n"
        "registries: []\n"
    )
    try:
        descriptor = os.open(
            catalog,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        if catalog.is_symlink() or not catalog.is_file():
            raise platform_cli.PlatformError(
                f"product workspace catalog is not a regular file: {catalog}"
            )
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _service_healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _process_manifest_path(config: MacProductConfig) -> Path:
    return config.runtime_dir / "processes.json"


def _write_process_manifest(
    config: MacProductConfig,
    processes: list[OwnedProcess],
) -> None:
    payload = {
        "artifact_kind": "platform_mac_product_workspace_processes",
        "schema_version": 1,
        "processes": [
            {
                **asdict(process),
                "expected_command_tokens": list(process.expected_command_tokens),
            }
            for process in processes
        ],
    }
    destination = _process_manifest_path(config)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def _load_process_manifest(config: MacProductConfig) -> list[OwnedProcess]:
    path = _process_manifest_path(config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if (
        not isinstance(payload, dict)
        or payload.get("artifact_kind") != "platform_mac_product_workspace_processes"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("processes"), list)
    ):
        return []
    processes: list[OwnedProcess] = []
    for item in payload["processes"]:
        if not isinstance(item, dict):
            return []
        process_id = item.get("process_id")
        pid = item.get("pid")
        tokens = item.get("expected_command_tokens")
        log_path = item.get("log_path")
        if (
            process_id not in {"backend", "ui"}
            or not isinstance(pid, int)
            or pid <= 1
            or not isinstance(tokens, list)
            or not tokens
            or not all(isinstance(token, str) and token for token in tokens)
            or not isinstance(log_path, str)
        ):
            return []
        processes.append(
            OwnedProcess(
                process_id=process_id,
                pid=pid,
                expected_command_tokens=tuple(tokens),
                log_path=log_path,
            )
        )
    return processes


def _running_command(pid: int) -> str | None:
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    command = completed.stdout.strip()
    return command if completed.returncode == 0 and command else None


def _process_is_zombie(pid: int) -> bool:
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "stat="],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    state = completed.stdout.strip()
    return completed.returncode == 0 and state.startswith("Z")


def _process_is_owned(process: OwnedProcess) -> bool:
    command = _running_command(process.pid)
    if command is None:
        return False
    try:
        if os.getpgid(process.pid) != process.pid:
            return False
    except ProcessLookupError:
        return False
    return all(token in command for token in process.expected_command_tokens)


def _all_manifest_processes_owned(config: MacProductConfig) -> bool:
    processes = _load_process_manifest(config)
    return len(processes) == 2 and all(_process_is_owned(process) for process in processes)


def _stop_owned_processes(config: MacProductConfig) -> tuple[bool, list[str]]:
    processes = _load_process_manifest(config)
    errors: list[str] = []
    owned: list[OwnedProcess] = []
    for process in processes:
        command = _running_command(process.pid)
        if command is None:
            continue
        if not _process_is_owned(process):
            errors.append(
                f"refusing to stop {process.process_id} pid {process.pid}: command ownership mismatch"
            )
            continue
        owned.append(process)
        os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while owned and time.monotonic() < deadline:
        owned = [
            process
            for process in owned
            if _running_command(process.pid) is not None
            and not _process_is_zombie(process.pid)
        ]
        if owned:
            time.sleep(0.1)
    for process in owned:
        if _process_is_zombie(process.pid):
            continue
        if _process_is_owned(process):
            os.killpg(process.pid, signal.SIGKILL)
        else:
            errors.append(
                f"refusing to force-stop {process.process_id} pid {process.pid}: command ownership mismatch"
            )
    if not errors:
        _process_manifest_path(config).unlink(missing_ok=True)
    return not errors, errors


def _wait_for_profile(config: MacProductConfig, *, timeout_seconds: float = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _service_healthy(f"{config.backend_url}/api/v1/health") and _service_healthy(
            config.ui_url
        ):
            return True
        time.sleep(0.25)
    return False


def _wait_for_profile_stopped(
    config: MacProductConfig,
    *,
    timeout_seconds: float = 10,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        backend_healthy = _service_healthy(f"{config.backend_url}/api/v1/health")
        ui_healthy = _service_healthy(config.ui_url)
        ports_available = _port_available(config.api_port) and _port_available(
            config.ui_port
        )
        if not backend_healthy and not ui_healthy and ports_available:
            return True
        time.sleep(0.1)
    return False


def _start_process(
    *,
    process_id: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    expected_command_tokens: tuple[str, ...],
    log_path: Path,
) -> OwnedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab", buffering=0)
    try:
        child = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    return OwnedProcess(
        process_id=process_id,
        pid=child.pid,
        expected_command_tokens=expected_command_tokens,
        log_path=str(log_path),
    )


def _already_running_payload(config: MacProductConfig) -> dict[str, object] | None:
    healthy = _service_healthy(f"{config.backend_url}/api/v1/health") and _service_healthy(
        config.ui_url
    )
    if not healthy:
        return None
    owned = _all_manifest_processes_owned(config)
    return {
        "ok": owned,
        "status": "already_running" if owned else "unowned_services_on_profile_ports",
        "errors": []
        if owned
        else ["profile ports are healthy but their processes are not owned by this runtime"],
        "ui_url": config.ui_url,
        "state_dir": str(config.state_dir),
        "specgraph_runs_dir": str(config.specgraph_runs_dir),
        "product_workspace_root_dir": str(config.product_workspace_root_dir),
        "product_workspace_catalog": str(config.product_workspace_catalog),
    }


def start(config: MacProductConfig, *, output_format: str) -> int:
    running = _already_running_payload(config)
    if running is not None:
        return _emit(running, output_format=output_format)

    if _load_process_manifest(config):
        stopped, errors = _stop_owned_processes(config)
        if not stopped:
            return _emit(
                {
                    "ok": False,
                    "status": "process_ownership_mismatch",
                    "errors": errors,
                    "ui_url": config.ui_url,
                    "state_dir": str(config.state_dir),
                    "specgraph_runs_dir": str(config.specgraph_runs_dir),
                    "product_workspace_root_dir": str(
                        config.product_workspace_root_dir
                    ),
                    "product_workspace_catalog": str(
                        config.product_workspace_catalog
                    ),
                },
                output_format=output_format,
            )

    checks = readiness_checks(config)
    if not all(check.ok for check in checks):
        return doctor(config, output_format=output_format)

    password = platform_cli.specspace_product_smoke_password_from_keychain(
        service=config.keychain_service,
        account=config.operator_username,
    )
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.specgraph_runs_dir.mkdir(parents=True, exist_ok=True)
    config.product_workspace_root_dir.mkdir(parents=True, exist_ok=True)
    _ensure_local_workspace_catalog(config)
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    password_path: Path | None = None
    ready = False
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="operator-auth-",
            dir=config.runtime_dir,
        )
        password_path = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(password)
            handle.write("\n")

        backend_command = [
            str(config.platform_dir / ".venv" / "bin" / "python"),
            "viewer/server.py",
            "--host",
            "127.0.0.1",
            "--port",
            str(config.api_port),
            "--dialog-dir",
            str(config.dialog_dir),
            "--spec-dir",
            str(config.specgraph_dir / "specs" / "nodes"),
            "--specgraph-dir",
            str(config.specgraph_dir),
            "--runs-dir",
            str(config.specgraph_runs_dir),
            "--specspace-state-dir",
            str(config.state_dir),
            "--platform-dir",
            str(config.platform_dir),
            "--product-workspace-root-dir",
            str(config.product_workspace_root_dir),
            "--product-workspace-catalog",
            str(config.product_workspace_catalog),
            "--enable-platform-execution",
            "--enable-operator-auth",
            "--operator-auth-username",
            config.operator_username,
            "--operator-auth-password-file",
            str(password_path),
            "--operator-auth-allowed-origin",
            config.ui_url,
        ]
        npm = shutil.which("npm")
        if npm is None:
            raise platform_cli.PlatformError("npm is unavailable after readiness preflight")
        ui_environment = _ui_environment(config)
        ui_command = [
            npm,
            "run",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(config.ui_port),
        ]
        processes = [
            _start_process(
                process_id="backend",
                command=backend_command,
                cwd=config.specspace_dir,
                env=_runtime_environment(config),
                expected_command_tokens=("viewer/server.py", str(config.api_port)),
                log_path=config.runtime_dir / "logs" / "backend.log",
            )
        ]
        _write_process_manifest(config, processes)
        processes.append(
            _start_process(
                process_id="ui",
                command=ui_command,
                cwd=config.specspace_dir / "graphspace",
                env=ui_environment,
                expected_command_tokens=("npm", "run", "dev", str(config.ui_port)),
                log_path=config.runtime_dir / "logs" / "graphspace.log",
            )
        )
        _write_process_manifest(config, processes)
        ready = _wait_for_profile(config)
    except Exception:
        _stop_owned_processes(config)
        raise
    finally:
        password = ""
        if password_path is not None:
            password_path.unlink(missing_ok=True)

    if not ready:
        _stop_owned_processes(config)
        return _emit(
            {
                "ok": False,
                "status": "start_failed",
                "errors": [f"inspect logs under {config.runtime_dir / 'logs'}"],
                "ui_url": config.ui_url,
                "state_dir": str(config.state_dir),
                "specgraph_runs_dir": str(config.specgraph_runs_dir),
                "product_workspace_root_dir": str(config.product_workspace_root_dir),
                "product_workspace_catalog": str(config.product_workspace_catalog),
            },
            output_format=output_format,
        )
    return _emit(
        {
            "ok": True,
            "status": "running",
            "ui_url": config.ui_url,
            "state_dir": str(config.state_dir),
            "specgraph_runs_dir": str(config.specgraph_runs_dir),
            "product_workspace_root_dir": str(config.product_workspace_root_dir),
            "product_workspace_catalog": str(config.product_workspace_catalog),
            "runtime_dir": str(config.runtime_dir),
        },
        output_format=output_format,
    )


def control(config: MacProductConfig, *, command: str, output_format: str) -> int:
    errors: list[str] = []
    stopped = True
    if command == "stop":
        stopped, errors = _stop_owned_processes(config)
        if stopped and not _wait_for_profile_stopped(config):
            stopped = False
            errors.append("profile services did not stop before the shutdown deadline")
    healthy = _service_healthy(f"{config.backend_url}/api/v1/health") and _service_healthy(
        config.ui_url
    )
    owned = _all_manifest_processes_owned(config)
    expected_healthy = command == "status"
    ok = stopped and (healthy and owned if expected_healthy else not healthy)
    status = "running" if healthy and owned else "stopped"
    if healthy and not owned:
        status = "unowned_services_on_profile_ports"
        errors.append("healthy services are not owned by this runtime")
    return _emit(
        {
            "ok": ok,
            "status": status,
            "errors": errors,
            "ui_url": config.ui_url,
            "state_dir": str(config.state_dir),
            "specgraph_runs_dir": str(config.specgraph_runs_dir),
            "product_workspace_root_dir": str(config.product_workspace_root_dir),
            "product_workspace_catalog": str(config.product_workspace_catalog),
            "runtime_dir": str(config.runtime_dir),
        },
        output_format=output_format,
    )


def _remove_e2e_tree(path: Path, *, parent: Path) -> None:
    if path.is_symlink():
        raise platform_cli.PlatformError(
            f"refusing to clean symlinked E2E path: {path}"
        )
    resolved_parent = parent.resolve()
    resolved_path = path.resolve()
    if resolved_path.parent != resolved_parent:
        raise platform_cli.PlatformError(
            f"refusing to clean E2E path outside its expected parent: {resolved_path}"
        )
    if path.exists():
        if not path.is_dir():
            raise platform_cli.PlatformError(f"E2E path is not a directory: {path}")
        shutil.rmtree(path)


def _e2e_config(config: MacProductConfig) -> tuple[MacProductConfig, Path]:
    artifact_dir = _path_from_env(
        "SPECSPACE_MAC_E2E_ARTIFACT_DIR",
        config.specspace_dir
        / "graphspace"
        / "test-results"
        / "mac-product-workspace-restart",
    )
    profile_dir = artifact_dir / "profile"
    return (
        replace(
            config,
            specgraph_runs_dir=(config.specgraph_dir / "runs").resolve(),
            state_dir=profile_dir / "state",
            product_workspace_root_dir=profile_dir / "workspaces",
            product_workspace_catalog=profile_dir / "workspaces.local.yaml",
            runtime_dir=profile_dir / "runtime",
        ),
        artifact_dir,
    )


def run_restart_e2e(config: MacProductConfig, *, output_format: str) -> int:
    e2e_config, artifact_dir = _e2e_config(config)
    graphspace_dir = e2e_config.specspace_dir / "graphspace"
    run_dir = e2e_config.specgraph_runs_dir / MAC_RESTART_E2E_WORKSPACE_ID
    _remove_e2e_tree(artifact_dir, parent=artifact_dir.parent)
    _remove_e2e_tree(run_dir, parent=e2e_config.specgraph_runs_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    password = platform_cli.specspace_product_smoke_password_from_keychain(
        service=e2e_config.keychain_service,
        account=e2e_config.operator_username,
    )
    playwright_env = _runtime_environment(e2e_config)
    playwright_env.update(
        {
            "API_PORT": str(e2e_config.api_port),
            "UI_PORT": str(e2e_config.ui_port),
            "PLATFORM_DIR": str(e2e_config.platform_dir),
            "SPECGRAPH_DIR": str(e2e_config.specgraph_dir),
            "SPECSPACE_DIR": str(e2e_config.specspace_dir),
            "DIALOG_DIR": str(e2e_config.dialog_dir),
            "SPECSPACE_MAC_PRODUCT_RUNTIME_DIR": str(e2e_config.runtime_dir),
            "SPECSPACE_MAC_RESTART_E2E": "1",
            "SPECSPACE_E2E_BASE_URL": e2e_config.ui_url,
            "SPECSPACE_E2E_OPERATOR_USERNAME": e2e_config.operator_username,
            "SPECSPACE_E2E_OPERATOR_PASSWORD": password,
            "SPECSPACE_E2E_TRACE": "off",
            "SPECSPACE_E2E_VIDEO": "off",
            "SPECSPACE_E2E_OUTPUT_DIR": str(artifact_dir / "playwright"),
            "SPECSPACE_MAC_E2E_ARTIFACT_DIR": str(artifact_dir),
            "SPECSPACE_E2E_PLATFORM_DIR": str(e2e_config.platform_dir),
            "SPECSPACE_E2E_SPECGRAPH_DIR": str(e2e_config.specgraph_dir),
            "SPECGRAPH_RUNS_DIR": str(e2e_config.specgraph_runs_dir),
            "SPECSPACE_STATE_DIR": str(e2e_config.state_dir),
            "SPECSPACE_PRODUCT_WORKSPACE_ROOT_DIR": str(
                e2e_config.product_workspace_root_dir
            ),
            "SPECSPACE_PRODUCT_WORKSPACE_CATALOG": str(
                e2e_config.product_workspace_catalog
            ),
        }
    )
    result = 1
    stop_result = 1
    try:
        started = start(e2e_config, output_format=output_format)
        if started == 0:
            completed = subprocess.run(
                [
                    "npm",
                    "exec",
                    "--",
                    "playwright",
                    "test",
                    "e2e/mac-product-workspace-restart.spec.ts",
                    "--config",
                    "playwright.config.ts",
                    "--workers=1",
                ],
                cwd=graphspace_dir,
                env=playwright_env,
                check=False,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            result = completed.returncode
        else:
            result = started
    finally:
        playwright_env["SPECSPACE_E2E_OPERATOR_PASSWORD"] = ""
        password = ""
        stop_result = control(e2e_config, command="stop", output_format=output_format)
    return result if result != 0 else stop_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the single-operator SpecSpace product profile on macOS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "start", "status", "stop", "e2e"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument(
            "--api-port",
            type=int,
            default=int(os.environ.get("API_PORT", "8001")),
        )
        command_parser.add_argument(
            "--ui-port",
            type=int,
            default=int(os.environ.get("UI_PORT", "5175")),
        )
        command_parser.add_argument(
            "--operator-auth-username",
            default=os.environ.get(
                "SPECSPACE_OPERATOR_AUTH_USERNAME",
                DEFAULT_OPERATOR_USERNAME,
            ),
        )
        command_parser.add_argument(
            "--operator-auth-keychain-service",
            default=os.environ.get(
                "SPECSPACE_OPERATOR_AUTH_KEYCHAIN_SERVICE",
                DEFAULT_KEYCHAIN_SERVICE,
            ),
        )
        command_parser.add_argument(
            "--format",
            choices=("table", "json"),
            default="table",
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = config_from_environment(args)
    if args.command == "doctor":
        return doctor(config, output_format=args.format)
    if args.command == "start":
        return start(config, output_format=args.format)
    if args.command == "e2e":
        return run_restart_e2e(config, output_format=args.format)
    return control(config, command=args.command, output_format=args.format)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except platform_cli.PlatformError as exc:
        print(f"mac product workspace: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
