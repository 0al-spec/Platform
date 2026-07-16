"""Fixed Platform wrapper adapter for hosted managed-operation workers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Protocol

try:
    from scripts import hosted_managed_operation_queue as queue_module
    from scripts import hosted_managed_operations as contracts
except ModuleNotFoundError:  # Direct execution adds scripts/ rather than repo root.
    import hosted_managed_operation_queue as queue_module
    import hosted_managed_operations as contracts


class ExecutorContractError(ValueError):
    """A pinned request cannot be resolved to the configured worker roots."""


class CommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]: ...


BindingValidator = Callable[[dict[str, Any], str], list[str]]


@dataclass(frozen=True)
class ResolvedOperation:
    request: dict[str, Any]
    workspace_id: str
    binding_source_path: Path
    binding: dict[str, Any]
    confirmation_path: Path | None
    input_paths: dict[str, Path]
    output_paths: dict[str, Path]
    output_refs: dict[str, str]


def _default_runner(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ExecutorContractError("artifact ref resolves outside its configured root") from exc
    return candidate


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutorContractError(f"{label} is not a readable JSON object") from exc
    if not isinstance(payload, dict):
        raise ExecutorContractError(f"{label} must be a JSON object")
    return payload


class FilesystemManagedOperationResolver:
    def __init__(
        self,
        *,
        artifact_root: Path,
        state_dir: Path,
        specgraph_dir: Path,
        binding_validator: BindingValidator,
    ) -> None:
        self.artifact_root = artifact_root.resolve()
        self.state_dir = state_dir.resolve()
        self.specgraph_dir = specgraph_dir.resolve()
        self.binding_validator = binding_validator

    def load_binding_source(
        self,
        source_ref: str,
        *,
        workspace_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        if not contracts.safe_artifact_ref(source_ref) or not str(source_ref).startswith("runs/"):
            raise ExecutorContractError("workspace binding source ref is not a safe runs ref")
        source_path = _safe_child(self.artifact_root, str(source_ref))
        if not source_path.is_file():
            raise ExecutorContractError("workspace binding source is missing")
        source = _read_json(source_path, "workspace binding source")
        binding = (
            source
            if source.get("artifact_kind") == "platform_product_workspace_binding"
            else _mapping(source.get("workspace_binding"))
        )
        validation_diagnostics = self.binding_validator(binding, workspace_id)
        if validation_diagnostics:
            raise ExecutorContractError("workspace binding validation failed")
        return source_path, binding

    def _binding_source(self, request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        binding_projection = _mapping(request.get("workspace_binding"))
        source_ref = str(binding_projection.get("source_ref") or "")
        workspace_id = str(_mapping(request.get("workspace")).get("workspace_id") or "")
        source_path, binding = self.load_binding_source(
            source_ref,
            workspace_id=workspace_id,
        )
        digest, _, _, _ = contracts.digest_path(source_path)
        if digest != binding_projection.get("source_sha256"):
            raise ExecutorContractError("workspace binding source digest changed after enqueue")
        if binding.get("binding_id") != binding_projection.get("binding_id"):
            raise ExecutorContractError("workspace binding identity changed after enqueue")
        if binding.get("binding_revision_sha256") != binding_projection.get(
            "binding_revision_sha256"
        ):
            raise ExecutorContractError("workspace binding revision changed after enqueue")
        if binding.get("status") != binding_projection.get("status"):
            raise ExecutorContractError("workspace binding status changed after enqueue")
        return source_path, binding

    def _workspace_runs_dir(self, workspace_id: str) -> Path:
        return _safe_child(self.artifact_root, f"runs/{workspace_id}")

    def resolve_logical_ref(self, logical_ref: str, workspace_id: str) -> Path:
        if logical_ref.startswith("specspace-state://"):
            relative = logical_ref.removeprefix("specspace-state://")
            return _safe_child(self.state_dir, relative)
        if logical_ref.startswith("runs/"):
            relative = logical_ref.removeprefix("runs/")
            relative = relative.replace("<workspace-id>", workspace_id)
            return _safe_child(self._workspace_runs_dir(workspace_id), relative)
        if logical_ref.startswith("dist/"):
            relative = logical_ref.replace("<workspace-id>", workspace_id)
            return _safe_child(self.specgraph_dir, relative)
        raise ExecutorContractError("operation ref uses an unsupported storage namespace")

    @staticmethod
    def _concrete_output_ref(pattern: str, request: dict[str, Any]) -> str:
        workspace_id = str(_mapping(request.get("workspace")).get("workspace_id") or "")
        request_fragment = str(request.get("idempotency_key") or "")[:24]
        return pattern.replace("<workspace-id>", workspace_id).replace(
            "<request-id>", request_fragment
        )

    def resolve(self, request: dict[str, Any]) -> ResolvedOperation:
        diagnostics = contracts.request_diagnostics(request)
        if diagnostics:
            raise ExecutorContractError("managed operation request is no longer valid")
        workspace_id = str(_mapping(request.get("workspace")).get("workspace_id") or "")
        binding_source_path, binding = self._binding_source(request)
        confirmation_path: Path | None = None
        confirmation = request.get("confirmation")
        if isinstance(confirmation, dict):
            confirmation_ref = str(confirmation.get("logical_ref") or "")
            confirmation_path = self.resolve_logical_ref(
                confirmation_ref, workspace_id
            )
            try:
                confirmation_digest, _, _, _ = contracts.digest_path(
                    confirmation_path
                )
            except (OSError, ValueError) as exc:
                raise ExecutorContractError(
                    "digest-pinned confirmation evidence is missing or unreadable"
                ) from exc
            if confirmation_digest != confirmation.get("sha256"):
                raise ExecutorContractError(
                    "digest-pinned confirmation evidence changed after enqueue"
                )
        input_paths: dict[str, Path] = {}
        for record in request["inputs"]:
            logical_ref = str(record["logical_ref"])
            path = self.resolve_logical_ref(logical_ref, workspace_id)
            try:
                digest, size, media_type, artifact_kind = contracts.digest_path(path)
            except (OSError, ValueError) as exc:
                raise ExecutorContractError(
                    f"pinned input is missing or unreadable: {logical_ref}"
                ) from exc
            if digest != record.get("sha256") or size != record.get("size_bytes"):
                raise ExecutorContractError(f"pinned input changed after enqueue: {logical_ref}")
            if media_type != record.get("media_type") or artifact_kind != record.get(
                "artifact_kind"
            ):
                raise ExecutorContractError(f"pinned input type changed after enqueue: {logical_ref}")
            input_paths[logical_ref] = path

        output_paths: dict[str, Path] = {}
        output_refs: dict[str, str] = {}
        for pattern in request["expected_output_reports"]:
            concrete_ref = self._concrete_output_ref(pattern, request)
            path = self.resolve_logical_ref(concrete_ref, workspace_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            output_paths[pattern] = path
            output_refs[pattern] = concrete_ref
        return ResolvedOperation(
            request=request,
            workspace_id=workspace_id,
            binding_source_path=binding_source_path,
            binding=binding,
            confirmation_path=confirmation_path,
            input_paths=input_paths,
            output_paths=output_paths,
            output_refs=output_refs,
        )


class PlatformManagedOperationExecutor:
    def __init__(
        self,
        *,
        resolver: FilesystemManagedOperationResolver,
        platform_script: Path,
        python_executable: str = sys.executable,
        runner: CommandRunner = _default_runner,
        maximum_timeout_seconds: int | None = None,
    ) -> None:
        self.resolver = resolver
        self.platform_script = platform_script.resolve()
        self.python_executable = python_executable
        self.runner = runner
        self.maximum_timeout_seconds = maximum_timeout_seconds
        if maximum_timeout_seconds is not None and maximum_timeout_seconds < 1:
            raise ExecutorContractError("maximum executor timeout must be positive")
        if self.platform_script.name != "platform.py" or not self.platform_script.is_file():
            raise ExecutorContractError("worker Platform script is missing or invalid")
        if not (self.resolver.specgraph_dir / "Makefile").is_file():
            raise ExecutorContractError("worker SpecGraph checkout does not contain a Makefile")

    def _base(self) -> list[str]:
        return [self.python_executable, str(self.platform_script)]

    @staticmethod
    def _input(resolved: ResolvedOperation, ref: str) -> Path:
        try:
            return resolved.input_paths[ref]
        except KeyError as exc:
            raise ExecutorContractError(f"required executor input is missing: {ref}") from exc

    @staticmethod
    def _optional_input(resolved: ResolvedOperation, ref: str) -> Path | None:
        return resolved.input_paths.get(ref)

    @staticmethod
    def _output(resolved: ResolvedOperation, ref: str) -> Path:
        try:
            return resolved.output_paths[ref]
        except KeyError as exc:
            raise ExecutorContractError(f"required executor output is missing: {ref}") from exc

    @staticmethod
    def _promotion_paths(path: Path) -> list[str]:
        report = _read_json(path, "promotion gate")
        promotion_request = _mapping(report.get("promotion_request"))
        raw_paths = promotion_request.get("paths")
        paths = [item for item in raw_paths if isinstance(item, str)] if isinstance(raw_paths, list) else []
        if not paths:
            materialized_files = report.get("materialized_files")
            for item in materialized_files if isinstance(materialized_files, list) else []:
                if not isinstance(item, dict):
                    continue
                value = item.get("promotion_path") or item.get("path")
                if isinstance(value, str):
                    paths.append(value)
        safe_paths = [
            item
            for item in paths
            if contracts.safe_artifact_ref(item) and not item.startswith("specspace-state://")
        ]
        if not safe_paths or len(safe_paths) != len(paths):
            raise ExecutorContractError("promotion gate does not contain safe promotion paths")
        return safe_paths

    def build_commands(self, resolved: ResolvedOperation) -> list[list[str]]:
        operation_id = str(_mapping(resolved.request.get("operation")).get("operation_id") or "")
        workspace_id = resolved.workspace_id
        specgraph_dir = self.resolver.specgraph_dir
        binding_source = resolved.binding_source_path
        base = self._base()

        if operation_id == "workspace_initialization_execute":
            return [[
                *base,
                "workspace",
                "execute-requested-initialization",
                "--execution-request",
                str(self._input(resolved, "runs/product_workspace_initialization_execution_request.json")),
                "--output",
                str(self._output(resolved, "runs/platform_product_workspace_initialization_execution_report.json")),
                "--format",
                "json",
            ]]
        if operation_id == "real_idea_intake_execute":
            return [[
                *base,
                "product-real-idea-intake",
                "execute-requested",
                "--execution-request",
                str(self._input(resolved, "specspace-state://real_idea_intake_execution_requests.json")),
                "--specgraph-dir",
                str(specgraph_dir),
                "--entry-requests",
                str(self._input(resolved, "specspace-state://real_idea_entry_requests.json")),
                "--workspace-initialization",
                str(binding_source),
                "--workspace-id",
                workspace_id,
                "--output",
                str(self._output(resolved, "runs/platform_real_idea_entry_intake_execution_report.json")),
                "--format",
                "json",
            ]]
        if operation_id == "real_idea_answer_continuation_execute":
            command = [
                *base,
                "product-real-idea-continuation",
                "execute-requested",
                "--execution-request",
                str(self._input(resolved, "specspace-state://real_idea_answer_continuation_execution_requests.json")),
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                workspace_id,
                "--workspace-initialization",
                str(binding_source),
                "--intake-execution",
                str(self._input(resolved, "runs/platform_real_idea_entry_intake_execution_report.json")),
                "--output",
                str(self._output(resolved, "runs/platform_real_idea_answer_continuation_execution_report.json")),
                "--format",
                "json",
            ]
            answer_state = self._optional_input(
                resolved, "specspace-state://idea_to_spec_intake_clarification_answers.json"
            )
            if answer_state is not None:
                command.extend(["--answer-state", str(answer_state)])
            return [command]
        if operation_id == "repair_rerun_request_gate_execute":
            return [[
                *base,
                "product-repair-rerun",
                "request-gate",
                "--specgraph-dir",
                str(specgraph_dir),
                "--rerun-request",
                str(self._input(resolved, "specspace-state://idea_to_spec_repair_rerun_requests.json")),
                "--import-preview",
                str(self._input(resolved, "runs/specspace_repair_draft_import_preview.json")),
                "--repair-session",
                str(self._input(resolved, "runs/idea_to_spec_repair_session.json")),
                "--workspace-id",
                workspace_id,
                "--workspace-initialization",
                str(binding_source),
                "--output-gate",
                str(self._output(resolved, "runs/specspace_repair_rerun_request_gate.json")),
                "--output",
                str(self._output(resolved, "runs/platform_product_repair_rerun_request_gate_execution_report.json")),
                "--format",
                "json",
            ]]
        if operation_id == "repair_rerun_execute":
            plan_ref = "runs/managed_repair_rerun_plans/<request-id>.platform_product_repair_rerun_execution_plan.json"
            plan_path = self._output(resolved, plan_ref)
            return [
                [
                    *base,
                    "product-repair-rerun",
                    "plan",
                    "--specgraph-dir",
                    str(specgraph_dir),
                    "--rerun-request",
                    str(self._input(resolved, "specspace-state://idea_to_spec_repair_rerun_requests.json")),
                    "--import-preview",
                    str(self._input(resolved, "runs/specspace_repair_draft_import_preview.json")),
                    "--repair-session",
                    str(self._input(resolved, "runs/idea_to_spec_repair_session.json")),
                    "--request-gate",
                    str(self._input(resolved, "runs/specspace_repair_rerun_request_gate.json")),
                    "--workspace-initialization",
                    str(binding_source),
                    "--output",
                    str(plan_path),
                    "--format",
                    "json",
                ],
                [
                    *base,
                    "product-repair-rerun",
                    "execute",
                    "--plan",
                    str(plan_path),
                    "--build-repaired-handoff",
                    "--output",
                    str(self._output(resolved, "runs/platform_product_repair_rerun_execution_report.json")),
                    "--format",
                    "json",
                ],
            ]
        if operation_id == "repair_rerun_publish":
            return [[
                *base,
                "product-repair-rerun",
                "publish",
                "--execution-report",
                str(self._input(resolved, "runs/platform_product_repair_rerun_execution_report.json")),
                "--specgraph-dir",
                str(specgraph_dir),
                "--output",
                str(self._output(resolved, "runs/platform_product_repair_rerun_publication_report.json")),
                "--format",
                "json",
            ]]
        if operation_id == "candidate_approval_execute":
            promotion_gate = self._input(resolved, "runs/repaired_idea_to_spec_promotion_gate.json")
            command = [
                *base,
                "product-candidate-approval",
                "approve",
                "--specgraph-dir",
                str(specgraph_dir),
                "--workspace-id",
                workspace_id,
                "--approval-intents",
                str(self._input(resolved, "specspace-state://idea_to_spec_candidate_approval_intents.json")),
                "--active-candidate",
                str(self._input(resolved, "runs/repaired_active_idea_to_spec_candidate.json")),
                "--repair-session",
                str(self._input(resolved, "runs/repaired_idea_to_spec_repair_session.json")),
                "--promotion-gate",
                str(promotion_gate),
                "--repair-execution",
                str(self._input(resolved, "runs/platform_product_repair_rerun_execution_report.json")),
                "--repair-publication",
                str(self._input(resolved, "runs/platform_product_repair_rerun_publication_report.json")),
                "--workspace-initialization",
                str(binding_source),
                "--gate-output",
                str(self._output(resolved, "runs/platform_candidate_approval_intent_gate_report.json")),
                "--decision-output",
                str(self._output(resolved, "runs/candidate_approval_decision.json")),
                "--output",
                str(self._output(resolved, "runs/platform_candidate_approval_execution_report.json")),
                "--format",
                "json",
            ]
            repaired_handoff = self._optional_input(
                resolved, "runs/repaired_candidate_promotion_handoff_report.json"
            )
            if repaired_handoff is not None:
                command.extend(["--repaired-handoff", str(repaired_handoff)])
            for path in self._promotion_paths(promotion_gate):
                command.extend(["--path", path])
            return [command]
        if operation_id == "promotion_request_execute":
            return [[
                *base,
                "product-candidate-promotion",
                "request",
                "--plan",
                str(self._input(resolved, "runs/graph_repository_execution_plan.json")),
                "--approval-decision",
                str(self._input(resolved, "runs/candidate_approval_decision.json")),
                "--workspace-initialization",
                str(binding_source),
                "--output",
                str(self._output(resolved, "runs/graph_repository_promotion_request.json")),
                "--format",
                "json",
            ]]
        if operation_id in {"promotion_execute_dry_run", "promotion_review_execute"}:
            command = [
                *base,
                "product-candidate-promotion",
                "execute",
                "--promotion-request",
                str(self._input(resolved, "runs/graph_repository_promotion_request.json")),
                "--approval-decision",
                str(self._input(resolved, "runs/candidate_approval_decision.json")),
                "--plan",
                str(self._input(resolved, "runs/graph_repository_execution_plan.json")),
                "--repository-dir",
                str(specgraph_dir),
                "--workspace-dir",
                str(specgraph_dir / ".platform" / "candidates" / workspace_id),
                "--git-service-output",
                str(self._output(resolved, "runs/git_service_promotion_execution_report.json")),
                "--output",
                str(self._output(resolved, "runs/product_candidate_promotion_execution_report.json")),
                "--format",
                "json",
            ]
            if operation_id == "promotion_execute_dry_run":
                command.extend(["--dry-run", "--open-review-dry-run"])
            return [command]
        if operation_id == "review_status_execute":
            command = [
                *base,
                "product-candidate-promotion",
                "review-status",
                "--execution-report",
                str(self._input(resolved, "runs/product_candidate_promotion_execution_report.json")),
                "--output",
                str(self._output(resolved, "runs/product_candidate_promotion_review_status_report.json")),
                "--format",
                "json",
            ]
            review_object_evidence = self._optional_input(
                resolved,
                "runs/product_candidate_promotion_review_object_evidence.json",
            )
            if review_object_evidence is not None:
                command.extend(
                    ["--review-object-evidence", str(review_object_evidence)]
                )
            return [command]
        if operation_id == "read_model_publication_execute":
            return [[
                *base,
                "product-candidate-promotion",
                "publish-read-model",
                "--review-status-report",
                str(self._input(resolved, "runs/product_candidate_promotion_review_status_report.json")),
                "--bundle-dir",
                str(self._input(resolved, "dist/specgraph-public/workspaces/<workspace-id>")),
                "--output-dir",
                str(specgraph_dir / "dist" / "specgraph-read-models" / workspace_id),
                "--output",
                str(self._output(resolved, "runs/product_candidate_promotion_read_model_publication_report.json")),
                "--format",
                "json",
            ]]
        raise ExecutorContractError("managed operation has no fixed Platform executor adapter")

    def execute(
        self,
        leased: queue_module.LeasedOperation,
    ) -> queue_module.ExecutionResult:
        try:
            resolved = self.resolver.resolve(leased.request)
            commands = self.build_commands(resolved)
        except ExecutorContractError as exc:
            return queue_module.ExecutionResult(
                status="quarantined",
                diagnostics=(str(exc),),
            )
        timeout_seconds = int(
            _mapping(leased.request.get("operation")).get("timeout_seconds") or 120
        )
        if self.maximum_timeout_seconds is not None:
            timeout_seconds = min(timeout_seconds, self.maximum_timeout_seconds)
        for index, command in enumerate(commands):
            try:
                completed = self.runner(
                    command,
                    cwd=self.platform_script.parent.parent,
                    timeout_seconds=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                return queue_module.ExecutionResult(
                    status="timed_out",
                    diagnostics=(f"Platform wrapper phase {index + 1} timed out",),
                )
            if completed.returncode != 0:
                return queue_module.ExecutionResult(
                    status="failed",
                    diagnostics=(
                        f"Platform wrapper phase {index + 1} exited with code {completed.returncode}",
                    ),
                )

        reports: list[dict[str, Any]] = []
        for pattern in leased.request["expected_output_reports"]:
            output_path = resolved.output_paths[pattern]
            if not output_path.is_file():
                return queue_module.ExecutionResult(
                    status="failed",
                    diagnostics=("Platform wrapper did not produce every expected report",),
                )
            try:
                payload = _read_json(output_path, "Platform output report")
            except ExecutorContractError:
                return queue_module.ExecutionResult(
                    status="failed",
                    diagnostics=("Platform output report is not valid JSON",),
                )
            if payload.get("ok") is False:
                return queue_module.ExecutionResult(
                    status="failed",
                    diagnostics=("Platform output report records a failed operation",),
                )
            digest, _, _, _ = contracts.digest_path(output_path)
            reports.append(
                {
                    "logical_ref": resolved.output_refs[pattern],
                    "sha256": digest,
                }
            )
        return queue_module.ExecutionResult(
            status="succeeded",
            output_reports=tuple(reports),
        )
