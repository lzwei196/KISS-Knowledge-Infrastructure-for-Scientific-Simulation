"""One KI-tool execution attempt shared by the direct and CLI adapters.

Adapters retain their tool/argument admission rules, timeout choice and response
format. This module owns fresh Flow checks, environment construction, one launch
and evidence capture. It never retries a scientific tool or changes Flow stage.
Local fixture processes can exercise the same interface without a provider.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import flowgate, paths


@dataclass(frozen=True)
class ExecutionResult:
    """Observed process outcome, separate from recording or scientific validation.

    ``succeeded`` means exit zero only. A missing/failed receipt is not evidence
    of scientific success, nor a reason to automatically launch a second attempt.
    """
    status: str
    exit_code: int | None
    output: str
    receipt: dict | None = None
    receipt_error: str | None = None
    detail: str = ""
    timeout: float | None = None


def _text(value) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def _stop_process(proc) -> tuple[str, str]:
    """Best-effort cleanup of the launched tool, not model-child monitoring.

    The bounded wait is for cleanup only, never a new execution deadline. A
    grandchild retaining a pipe must not hide the original failure indefinitely.
    """
    notes, output = [], ""
    try:
        proc.kill()
    except (Exception, KeyboardInterrupt) as exc:
        notes.append(f"tool cleanup could not send termination ({type(exc).__name__}): {exc}")
    try:
        stdout, stderr = proc.communicate(timeout=5)
        output = _text(stdout) + _text(stderr)
    except (Exception, KeyboardInterrupt) as exc:
        notes.append(f"tool output could not be fully collected: {type(exc).__name__}")
        try:
            proc.wait(timeout=5)
        except (Exception, KeyboardInterrupt) as wait_error:
            notes.append(f"tool termination was not confirmed: {type(wait_error).__name__}")
    return output, "; ".join(notes)


def _fresh_approval(flow, project: Path) -> str:
    if Path(flow.project).resolve() != project:
        raise flowgate.FlowDenied("execution project differs from the approved project")
    flow.ctx = flow.flow.states.FlowContext.load(project)
    flow.reload_artifacts()
    flow.check_tool("run_ki_tool")
    if flow.approval_status() != "OK":
        raise flowgate.FlowDenied("no valid approval — runs happen only in an approved plan")
    doc = flow.approval_doc or {}
    # An approval check reads disk; also prove that our loaded request snapshot
    # is the one it checked, even if a review was completed during these reads.
    if (doc.get("plan_sha256") != flow.flow.plan.sha256(flow.plan)
            or doc.get("data_inventory_sha256") != flow.flow.plan.sha256(flow.inventory)
            or flow.approval_id != flow.flow.approval.approval_id(flow.flow.approval.read(project))):
        raise flowgate.FlowDenied("approval changed while preparing the execution; review the current plan")
    return flow.approval_id


def execute_ki_tool(*, flow, cfg, project: Path, ki: str, ki_root: Path,
                    tool: Path, arguments: list[str], cwd: Path,
                    plan_step_id: str | None, python_tool: bool,
                    timeout: float | None = None, provider_id: str = "") -> ExecutionResult:
    """Attempt a KI tool once, then return outcome and receipt diagnostics.

    Permission failures raise FlowDenied before launch. After launch is attempted,
    process/recording failures are returned separately so adapters retain output.
    ``timeout=None`` preserves the CLI's no-deadline behavior; direct calls pass
    their existing bounded setting. ``flow=None`` supports the existing legacy
    untracked direct route, which cannot obtain an approved execution receipt.
    """
    project, ki_root, tool, cwd = map(lambda p: Path(p).resolve(), (project, ki_root, tool, cwd))
    from ki_tools_common.flow.tools import is_ki_tool
    if not is_ki_tool(ki_root, tool):
        raise flowgate.FlowDenied("execution requires a shipped KI tool or declared model binary")
    if (cwd != project and project not in cwd.parents) or not cwd.is_dir():
        raise flowgate.FlowDenied("execution directory must exist inside the project")
    approved_env, approval_id = {}, None
    if flow is not None:
        approval_id = _fresh_approval(flow, project)
        step = flow.check_step_tool(plan_step_id, ki, tool)
        approved_env = flow.approved_step_environment(step, ki_root)
    child_env = {key: value for key, value in os.environ.items()
                 if not any(secret in key.upper() for secret in
                            ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
    child_env["KISS_ROOT"] = str(project)
    child_env = paths.with_ki_tools_common(cfg, child_env)
    from .calibration import with_framework_env
    child_env = with_framework_env(child_env)
    if provider_id:
        from .settings import with_provider_proxy
        child_env = with_provider_proxy(provider_id, child_env)
    child_env.update(approved_env)
    command = ([str(cfg.python), str(tool)] if python_tool else [str(tool)]) + list(arguments)
    before = flowgate._snapshot(project) if flow is not None else None
    if flow is not None and (flow.approval_status() != "OK" or approval_id !=
                            flow.flow.approval.approval_id(flow.flow.approval.read(project))):
        raise flowgate.FlowDenied("approval changed before execution; no process was launched")
    started = time.time()
    exit_code, process_started, detail, output = None, None, "", ""
    proc = None
    try:
        proc = subprocess.Popen(command, cwd=str(cwd), env=child_env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace")
        process_started = True
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        output = (_text(stdout) + _text(stderr))[-80000:]
        status = "succeeded" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        status = "timed_out"
        output = (_text(exc.stdout) + _text(exc.stderr))[-12000:]
        detail = f"TIMEOUT after {timeout:g}s" if timeout is not None else "KI tool attempt timed out"
    except OSError as exc:
        if proc is None:
            status, process_started = "not_launched", False
            detail = f"Could not launch KI tool: {exc}"
        else:
            status = "outcome_unknown"
            detail = f"KI tool started, but its outcome could not be observed: {exc}"
    except KeyboardInterrupt:
        status = "interrupted"
        detail = "KI tool attempt interrupted; completion was not observed"
    except Exception as exc:
        status = "outcome_unknown"
        detail = f"KI tool outcome unknown ({type(exc).__name__}): {exc}"
    finally:
        if proc is not None:
            if exit_code is None:
                collected, cleanup_note = _stop_process(proc)
                output = (collected or output)[-12000:]
                if cleanup_note:
                    detail += f"\n{cleanup_note}"
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except (Exception, KeyboardInterrupt) as exc:
                        detail += f"\ntool output pipe cleanup failed: {type(exc).__name__}"
    finished = time.time()
    receipt, receipt_error = None, None
    if flow is not None:
        try:
            receipt = flow.record_tool_run(
                ki=ki, ki_root=ki_root, command=command, cwd=cwd,
                started_at=started, finished_at=finished, exit_code=exit_code,
                before=before, plan_step_id=plan_step_id,
                stdout_tail=(output + ("\n" + detail if detail else ""))[-20000:],
                expected_approval_sha256=approval_id,
                execution_status=status, process_started=process_started,
                input_arguments=list(arguments))
        except Exception as exc:
            receipt_error = str(exc) or type(exc).__name__
    return ExecutionResult(status, exit_code, output, receipt, receipt_error, detail, timeout)
