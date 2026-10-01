"""One KI-tool execution attempt shared by the direct and CLI adapters.

Adapters retain their tool/argument admission rules, timeout choice and response
format. This module owns fresh Flow checks, environment construction, one launch
and evidence capture. It never retries a scientific tool or changes Flow stage.
Local fixture processes can exercise the same interface without a provider.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import flowgate, paths, project_paths

# Under .geoforge/ (always protected): the agent can neither raise nor suppress a Stop.
# Its presence means the project's current turn was stopped. A new turn rotates
# the generation before clearing it, so old CLI children stay cancelled.
STOP_MARKER = ".geoforge/stop-request"
TURN_FILE = ".geoforge/turn-generation"
TURN_ID_ENV = "GEOFORGE_TURN_ID"
TURN_PROJECT_ENV = "GEOFORGE_TURN_PROJECT"
_POPEN = subprocess.Popen          # a group kill needs a real child we launched in its own session
#: Tool and setup processes running now, so a quitting Desktop can end them.
LIVE_PROCESSES: set = set()
_STOP_GRACE_SECONDS = 5.0
_STOP_THREADS: set[threading.Thread] = set()
_STOP_THREADS_LOCK = threading.Lock()


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


@dataclass(frozen=True)
class ProcessRun:
    """One supervised launch as observed; recording it is the caller's business."""
    status: str             # succeeded failed timed_out stopped interrupted not_launched outcome_unknown
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    detail: str = ""
    process_started: bool | None = None
    error: BaseException | None = None


def _text(value) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def request_stop(project: Path) -> None:
    """The user's Stop for this project's current turn: running attempts end, none start.

    A file, not an in-memory flag: a CLI agent's run-tool can be another process.
    Children also carry their originating generation; clearing this marker for
    a later user turn never grants those old children permission to run again.
    """
    marker = Path(project) / STOP_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def current_turn_id(project: Path) -> str:
    """Read the host-owned generation, never mint one for an agent command."""
    try:
        return (Path(project) / TURN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def begin_turn(project: Path) -> str:
    """Authorize a new user turn without reviving any previous turn's children."""
    path = Path(project) / TURN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    turn_id = uuid.uuid4().hex
    temp = path.with_name(f".{path.name}.{turn_id}.tmp")
    temp.write_text(turn_id, encoding="utf-8")
    for attempt in range(40):
        try:
            temp.replace(path)
            break
        except PermissionError:
            # Windows refuses the rename while a watcher is reading the old
            # file (opened without FILE_SHARE_DELETE); that lasts milliseconds.
            if os.name != "nt" or attempt == 39:
                raise
            time.sleep(0.025)
    (Path(project) / STOP_MARKER).unlink(missing_ok=True)
    return turn_id


def turn_environment(project: Path, turn_id: str | None = None, *, env=None) -> dict[str, str]:
    """Copy an environment and bind its children to this captured Desktop turn.

    No id is minted here: standalone source CLI use remains supported without
    a Desktop turn. A stale id must be preserved, never replaced by today's id.
    """
    result = dict(os.environ if env is None else env)
    if turn_id is None and (result.get(TURN_ID_ENV) or result.get(TURN_PROJECT_ENV)):
        return result                         # inherited identity is never rebound
    captured = current_turn_id(project) if turn_id is None else turn_id
    if captured:
        result[TURN_PROJECT_ENV] = str(Path(project).resolve())
        result[TURN_ID_ENV] = captured
    return result


def stop_requested(project: Path, *, turn_id: str | None = None, env=None) -> bool:
    """Check Stop and the caller's durable generation, not just today's marker.

    An inherited Desktop identity is scoped to its project. Missing, stale or
    mismatched identities fail closed; unbound source CLI calls retain their
    existing approval-gated behavior.
    """
    project = Path(project).resolve()
    if (project / STOP_MARKER).exists():
        return True
    inherited = os.environ if env is None else env
    if turn_id is None:
        turn_id = inherited.get(TURN_ID_ENV)
        owner = inherited.get(TURN_PROJECT_ENV)
        if turn_id or owner:
            if not turn_id or not owner or Path(owner).resolve() != project:
                return True
    return bool(turn_id and current_turn_id(project) != turn_id)


def _tree_groups(pid: int) -> set[int]:
    """Capture the process groups under ``pid`` before any parent is signalled.

    The tree is read once, before anything dies: a dead parent's children are
    reparented and the link is lost. Descendants that started their own session
    (setsid, as agent CLIs do for shell commands) are reached through their own
    group. This process's group is never signalled."""
    rows: dict[int, tuple[int, int]] = {}
    try:
        table = subprocess.run(["ps", "-Ao", "pid=,ppid=,pgid="], capture_output=True,
                               text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        table = ""
    for line in str(table or "").splitlines():
        try:
            child, parent, group = map(int, line.split())
        except ValueError:
            continue
        rows[child] = (parent, group)
    children: dict[int, list[int]] = {}
    for child, (parent, _group) in rows.items():
        children.setdefault(parent, []).append(child)
    tree, todo = [], [pid]
    while todo:
        current = todo.pop()
        tree.append(current)
        todo.extend(c for c in children.get(current, ()) if c not in tree)
    # ponytail: a daemon that double-forked away before this walk is not in the tree.
    return {rows[p][1] if p in rows else p for p in tree} - {os.getpgrp()}


def _signal_groups(groups: set[int], sig: int) -> None:
    for group in groups - {os.getpgrp()}:
        try:
            os.killpg(group, sig)
        except OSError:
            pass


def kill_tree(pid: int, sig: int) -> None:
    """Signal the process group of ``pid`` and of every descendant (POSIX)."""
    _signal_groups(_tree_groups(pid), sig)


def _kill(proc) -> None:
    """The tool, the models it started and anything they moved into new sessions."""
    if isinstance(proc, _POPEN):
        if os.name == "nt":
            # A pre-kill snapshot pinned by creation time: descendants of a root
            # that already exited (a .cmd shim, a build driver) are reached too.
            from .processes import terminate_process_tree
            terminate_process_tree(proc)
        else:
            kill_tree(proc.pid, signal.SIGKILL)
    proc.kill()


def _start_stop_worker(escalate) -> None:
    worker = threading.Thread(target=escalate, daemon=True, name="geoforge-stop-tree")
    with _STOP_THREADS_LOCK:
        _STOP_THREADS.add(worker)
        worker.start()


def _terminate_tree_windows(proc, *, grace: float) -> None:
    """Windows Stop: no SIGTERM reaches a console-less child.

    Everything the root started (the model, the CLI's commands) ends now; the
    root keeps ``grace`` seconds to write its receipt, then it and anything it
    started meanwhile are forced. Identities are pinned by creation time, so a
    recycled PID is never signalled.
    """
    from . import processes
    try:
        root_created = processes._windows_creation_time(proc.pid)
        descendants = processes.windows_descendants(proc.pid)
    except (OSError, TypeError, ValueError):
        root_created, descendants = None, []
    processes.terminate_snapshot(descendants)

    def escalate():
        try:
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if proc.poll() is not None and not processes.any_alive(descendants):
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            late = processes.windows_descendants(proc.pid, root_created=root_created)
            if proc.poll() is None:
                processes.terminate_process_tree(proc)
            processes.terminate_snapshot(descendants + late)
        except Exception:  # noqa: BLE001 — Stop cleanup is best effort
            pass
        finally:
            with _STOP_THREADS_LOCK:
                _STOP_THREADS.discard(threading.current_thread())

    _start_stop_worker(escalate)


def terminate_tree(proc, *, wrapper_grace: bool = False) -> None:
    """End a CLI tree, allowing receipt cleanup before bounded forceful termination.

    Keep the original groups: a parent may exit on SIGTERM while a child in a
    separate session ignores it and is reparented. A second tree walk loses it.
    Stop remains nonblocking; Desktop shutdown joins these workers explicitly.

    ``wrapper_grace`` is for Windows only: the grace period is kept solely for
    GeoForge's own run-tool wrapper, which polls the stop marker. An agent CLI
    root receives no signal there, so a grace would only let it keep working.
    """
    if not isinstance(proc, _POPEN):
        proc.terminate()
        return
    if os.name == "nt":
        _terminate_tree_windows(proc, grace=_STOP_GRACE_SECONDS if wrapper_grace else 0.0)
        return
    groups = _tree_groups(proc.pid)
    if groups is not None:
        _signal_groups(groups, signal.SIGTERM)
    else:
        proc.terminate()

    def escalate():
        try:
            deadline = time.monotonic() + _STOP_GRACE_SECONDS
            while time.monotonic() < deadline:
                if groups is not None:
                    alive = set()
                    for group in groups:
                        try:
                            os.killpg(group, 0)
                            alive.add(group)
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            alive.add(group)
                    if not alive:
                        return
                    # Once an original group disappears, never target that id
                    # again if the operating system later reuses it.
                    groups.intersection_update(alive)
                elif proc.poll() is not None:
                    return
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if groups is not None:
                _signal_groups(groups, signal.SIGKILL)
            elif proc.poll() is None:
                proc.kill()
        finally:
            with _STOP_THREADS_LOCK:
                _STOP_THREADS.discard(threading.current_thread())

    worker = threading.Thread(target=escalate, daemon=True, name="geoforge-stop-tree")
    with _STOP_THREADS_LOCK:
        _STOP_THREADS.add(worker)
        worker.start()


def wait_for_stops() -> None:
    """Let queued CLI escalation finish before a quitting Desktop exits."""
    deadline = time.monotonic() + _STOP_GRACE_SECONDS + 1
    with _STOP_THREADS_LOCK:
        workers = list(_STOP_THREADS)
    for worker in workers:
        worker.join(max(0, deadline - time.monotonic()))


def kill_live_processes() -> None:
    """The Desktop is quitting: no tool or setup process it launched outlives it."""
    for proc in list(LIVE_PROCESSES):
        try:
            _kill(proc)
        except Exception:  # noqa: BLE001 — best effort on the way out
            pass


def _stop_process(proc) -> tuple[str, str, str]:
    """Best-effort cleanup of the launched process and everything under it.

    The bounded wait is for cleanup only, never a new execution deadline. A
    grandchild retaining a pipe must not hide the original failure indefinitely.
    """
    notes, stdout, stderr = [], "", ""
    try:
        _kill(proc)
    except (Exception, KeyboardInterrupt) as exc:
        notes.append(f"tool cleanup could not send termination ({type(exc).__name__}): {exc}")
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            # A detached descendant can keep the pipes open after the tool is
            # gone. Keep what it had already printed; do not wait for EOF.
            stdout, stderr = _text(exc.output), _text(exc.stderr)
        notes.append(f"tool output could not be fully collected: {type(exc).__name__}")
        try:
            proc.wait(timeout=5)
        except (Exception, KeyboardInterrupt) as wait_error:
            notes.append(f"tool termination was not confirmed: {type(wait_error).__name__}")
    return _text(stdout), _text(stderr), "; ".join(notes)


def run_process(command: list[str] | str, *, cwd, env, timeout: float | None,
                project: Path | None = None, stdin=None, stop=None,
                turn_id: str | None = None, graceful_stop: bool = False) -> ProcessRun:
    """Launch once in a session of its own, wait, and leave no process tree behind.

    With ``project``, its stop marker refuses the launch or ends the run. A
    timeout or an unobservable outcome also ends the whole tree. Never retries.
    """
    exit_code, started, detail, stdout, stderr, error = None, None, "", "", "", None
    proc = None
    stopped, done = threading.Event(), threading.Event()
    # Capture once. Even a fast Stop/new-turn between watcher polls cannot
    # revive a process already supervised on behalf of the previous turn.
    captured = turn_id
    if project is not None and captured is None:
        inherited = os.environ if env is None else env
        captured = inherited.get(TURN_ID_ENV) or current_turn_id(project) or None

    def user_stop():
        return bool((stop is not None and stop()) or (project is not None and (
            stop_requested(project, env=env) or
            stop_requested(project, turn_id=captured, env=env))))

    def watch_for_stop():
        while not done.wait(1):
            if user_stop():
                stopped.set()
                try:
                    # A source CLI receipt wrapper must be allowed to finish
                    # its bookkeeping after stopping the model it supervises.
                    terminate_tree(proc, wrapper_grace=True) if graceful_stop else _kill(proc)
                except Exception:  # noqa: BLE001 — the attempt's own cleanup still runs
                    pass
                return

    try:
        if user_stop():
            return ProcessRun("stopped", None, detail="Stopped by the user; no process was launched.",
                              process_started=False)
        # POSIX: a session of its own, so the whole tree can be signalled.
        # Windows: no console window flashes up from the windowed Desktop; the
        # tree is found by PID snapshot instead (see processes.py).
        # Windows also closes stdin unless a caller supplies one: the windowed
        # Desktop has no console to inherit, and a prompting tool must fail
        # rather than wait forever for input nobody can type.
        launch = ({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                  if os.name == "nt" else {"start_new_session": True})
        if os.name == "nt" and stdin is None:
            stdin = subprocess.DEVNULL
        proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=stdin,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace", **launch)
        started = True
        LIVE_PROCESSES.add(proc)
        if project is not None or stop is not None:
            threading.Thread(target=watch_for_stop, daemon=True).start()
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        status = "succeeded" if exit_code == 0 else "failed"
        if stopped.is_set() or (exit_code != 0 and user_stop()):
            status, detail = "stopped", "Stopped by the user; the process and everything it started were signalled."
    except subprocess.TimeoutExpired as exc:
        status = "timed_out"
        stdout, stderr = exc.stdout, exc.stderr
        detail = f"TIMEOUT after {timeout:g}s" if timeout is not None else "KI tool attempt timed out"
    except OSError as exc:
        error = exc
        if proc is None:
            status, started = "not_launched", False
            # Windows' "[WinError 2]" does not name the file; say which one.
            # A str is a whole Windows command line, not a program name.
            shown = command if isinstance(command, str) else command[0]
            detail = f"Could not launch KI tool {shown!r}: {exc}"
        else:
            status = "outcome_unknown"
            detail = f"KI tool started, but its outcome could not be observed: {exc}"
    except KeyboardInterrupt:
        if user_stop():
            status, detail = "stopped", "Stopped by the user; the process and everything it started were signalled."
        else:
            status, detail = "interrupted", "KI tool attempt interrupted; completion was not observed"
    except Exception as exc:
        error = exc
        status = "outcome_unknown"
        detail = f"KI tool outcome unknown ({type(exc).__name__}): {exc}"
    finally:
        done.set()
        if proc is not None:
            if exit_code is None:
                collected_out, collected_err, cleanup_note = _stop_process(proc)
                if collected_out or collected_err:
                    stdout, stderr = collected_out, collected_err
                if cleanup_note:
                    detail += f"\n{cleanup_note}"
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except (Exception, KeyboardInterrupt) as exc:
                        detail += f"\ntool output pipe cleanup failed: {type(exc).__name__}"
            LIVE_PROCESSES.discard(proc)
    return ProcessRun(status, exit_code, _text(stdout), _text(stderr), detail, started, error)


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
                    timeout: float | None = None, provider_id: str = "",
                    stop=None, turn_id: str | None = None) -> ExecutionResult:
    """Attempt a KI tool once, then return outcome and receipt diagnostics.

    Permission failures raise FlowDenied before launch. After launch is attempted,
    process/recording failures are returned separately so adapters retain output.
    ``timeout=None`` preserves the CLI's no-deadline behavior; direct calls pass
    their existing bounded setting. ``flow=None`` supports the existing legacy
    untracked direct route, which cannot obtain an approved execution receipt.
    """
    requested_root = Path(ki_root)
    project, ki_root, tool, cwd = map(lambda p: Path(p).resolve(), (project, ki_root, tool, cwd))
    if (stop is not None and stop()) or stop_requested(project) or stop_requested(project, turn_id=turn_id):
        raise flowgate.FlowDenied("stopped by the user; no process was launched")
    if turn_id is None:
        turn_id = os.environ.get(TURN_ID_ENV) or current_turn_id(project) or None
    from ki_tools_common.flow.tools import is_ki_tool
    if not is_ki_tool(ki_root, tool):
        raise flowgate.FlowDenied("execution requires a shipped KI tool or declared model binary")
    if (cwd != project and project not in cwd.parents) or not cwd.is_dir():
        raise flowgate.FlowDenied("execution directory must exist inside the project")
    approved_env, approval_id = {}, None
    if flow is not None:
        approval_id = _fresh_approval(flow, project)
        step = flow.check_step_tool(plan_step_id, ki, tool)
        # Help/version-only calls do not execute the approved scientific step.
        # Refuse them before launch instead of recording a failed attempt with
        # no outputs, which would supersede that step's successful execution.
        # Do not run an unreceipted probe here: model binaries can ignore these
        # flags and execute normally. Mixed/other arguments remain real attempts.
        if arguments and all(arg in {"--help", "-h", "--version", "-version", "-V"}
                             for arg in arguments):
            raise flowgate.FlowDenied(
                "Help/version probes are not plan-step executions; no process was launched "
                "and no execution receipt was written. Read the KI tool source or its "
                "documentation for usage, then run the approved step with its real inputs.")
        approved_env = flow.approved_step_environment(step, ki_root)
    # The chat config may belong to its first KI; CLI root discovery used to
    # pick the last one. Resolve the actual step's runtime at this common seam.
    selected = getattr(getattr(flow, "ctx", None), "selected_kis", []) or []
    try:
        cfg = project_paths.execution_config(
            project, ki, requested_root, fallback=cfg if len(selected) <= 1 else None)
    except (OSError, ValueError) as exc:
        raise flowgate.FlowDenied(f"cannot resolve runtime for {ki}: {exc}") from exc
    child_env = {key: value for key, value in os.environ.items()
                 if not any(secret in key.upper() for secret in
                            ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
    # KISS_ROOT is the discovery directory used by paths.active(), not cwd.
    # The selected config still declares the scenario project as cfg.root.
    model_home = project / "models" / ki
    child_env["KISS_ROOT"] = str(model_home if (model_home / paths.CONFIG_NAME).is_file() else project)
    child_env = turn_environment(project, turn_id=turn_id, env=child_env)
    child_env = paths.with_ki_tools_common(cfg, child_env)
    child_env = paths.with_python_runtime(cfg.python, child_env)
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
    run = run_process(command, cwd=cwd, env=child_env, timeout=timeout, project=project,
                      stop=stop, turn_id=turn_id)
    if run.status == "stopped" and run.process_started is False:
        # Not an attempt: no receipt, so a step that already passed is not demoted.
        raise flowgate.FlowDenied("stopped by the user; no process was launched")
    exit_code, status, detail = run.returncode, run.status, run.detail
    output = (run.stdout + run.stderr)[-80000 if exit_code is not None else -12000:]
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
                execution_status=status, process_started=run.process_started,
                input_arguments=list(arguments))
        except Exception as exc:
            receipt_error = str(exc) or type(exc).__name__
    return ExecutionResult(status, exit_code, output, receipt, receipt_error, detail, timeout)
