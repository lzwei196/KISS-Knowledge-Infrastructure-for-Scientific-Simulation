"""Standalone setup ownership uses real leases, generations, and harmless children."""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from kiss_cli import execution, install, install_locations, setup_jobs


def _child_job(workroot, root, model, pipe, mode="hold"):
    try:
        job = setup_jobs.start(workroot, model, root, "fixture")
        pipe.send(("started", job.snapshot()))
        if mode == "cancel":
            if not job.handle.stopped.wait(15):
                raise RuntimeError("remote Stop was not delivered")
            pipe.send(("finished", job.finish("completed")))
        elif mode == "idle":
            job.finish("completed")
        else:
            command = pipe.recv()
            if command == "finish":
                pipe.send(("finished", job.finish("completed")))
            elif command == "crash":
                os._exit(23)
    except BaseException as error:
        pipe.send(("error", f"{type(error).__name__}: {error}"))
        raise
    finally:
        pipe.close()


def _child_idle(workroot, root, pipe):
    with setup_jobs.idle_guard(workroot, "Demo", root):
        pipe.send("held")
        pipe.recv()


def _recv(pipe):
    assert pipe.poll(20), "fixture child did not respond"
    result = pipe.recv()
    assert not (isinstance(result, tuple) and result[0] == "error"), result
    return result


@pytest.fixture
def spawn_job():
    children = []

    def spawn(workroot, root, model="Demo", mode="hold"):
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=_child_job,
                              args=(str(workroot), str(root), model, child, mode))
        process.start()
        child.close()
        children.append((process, parent))
        tag, snapshot = _recv(parent)
        assert tag == "started"
        return process, parent, snapshot

    yield spawn
    for process, pipe in children:
        if process.is_alive():
            process.terminate()
        process.join(10)
        pipe.close()


@pytest.fixture(autouse=True)
def finish_local_jobs(monkeypatch):
    # GUI/helper loading can prepend another repository with its own `tests`
    # package. Spawn reconstructs sys.path before unpickling these targets, so
    # explicitly select the checkout that defines this fixture module.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    yield
    for job in list(setup_jobs._LIVE.values()):
        job.finish("cancelled")


def _seed_verified(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "status.json").write_text(json.dumps({
        "ok": True, "verified_at": 5, "verification_identity": "ki",
        "runtime_identity": "runtime", "ki_content_digest": "live"}), encoding="utf-8")
    (root / install_locations.RECORD_FILE).write_text(json.dumps({
        "verified": True, "verified_at": 5}), encoding="utf-8")
    (root / "installation-test.json").write_text(json.dumps({
        "usable": True, "state": "ready"}), encoding="utf-8")


def _assert_revoked(root):
    doc = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert doc["ok"] is False
    for key in ("verified_at", "verification_identity", "runtime_identity", "ki_content_digest"):
        assert doc[key] is None
    receipt = root / install_locations.RECORD_FILE
    if receipt.exists():
        assert json.loads(receipt.read_text(encoding="utf-8"))["verified"] is False
    probe = root / "installation-test.json"
    if probe.exists():
        assert json.loads(probe.read_text(encoding="utf-8"))["usable"] is False


def test_start_snapshot_finish_and_durable_read(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    _seed_verified(root)
    job = setup_jobs.start(workroot, "Demo", root, "api:fixture", installation_only=True)
    snapshot = job.snapshot()
    assert snapshot == setup_jobs.status(workroot, "demo")
    assert snapshot["id"] == job.id
    assert snapshot["state"] == "running"
    assert snapshot["active"] and snapshot["can_stop"]
    assert snapshot["installation_only"]
    assert job.events["_handle"] is job.handle
    assert job.events["_turn_id"] == execution.current_turn_id(root) == job.turn_id
    assert Path(job.events["project"]) == root
    _assert_revoked(root)
    job.update(phase="verifying", detail="A harmless fixture")
    assert setup_jobs.status(workroot, "Demo")["phase"] == "verifying"
    seen = []
    result = job.finish("completed", cleanup=seen.append)
    assert seen == ["completed"]
    assert not result["active"] and not result["can_stop"]
    assert result["ended_at"] == result["finished_at"] >= result["started_at"]
    assert setup_jobs.status(workroot, "Demo") == result
    assert job.finish("failed", cleanup=seen.append) == result
    assert seen == ["completed"]


def test_no_job_and_terminal_poll_do_not_rewrite_files(tmp_path):
    workroot = tmp_path / "work"
    assert setup_jobs.status(workroot, "Demo") is None
    assert not workroot.exists()
    job = setup_jobs.start(workroot, "Demo", tmp_path / "root", "fixture")
    job.finish("waiting_for_user")
    path, _, _ = setup_jobs._paths(workroot, "Demo")
    before = path.stat().st_mtime_ns
    for _ in range(3):
        assert setup_jobs.status(workroot, "Demo")["state"] == "waiting_for_user"
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize("state", sorted(setup_jobs.TERMINAL))
def test_terminal_history_is_bound_to_selected_installation_folder(tmp_path, state):
    workroot, old, selected = tmp_path / "work", tmp_path / "old", tmp_path / "new"
    job = setup_jobs.start(workroot, "Demo", old, "fixture")
    job.finish(state)
    path, _, _ = setup_jobs._paths(workroot, "Demo")
    before = path.read_bytes()
    assert setup_jobs.status(workroot, "Demo", expected_root=selected) is None
    assert not selected.exists(), "displaying new-folder status must not create it"
    assert setup_jobs.status(workroot, "Demo", expected_root=old / "sub" / "..")["id"] == job.id
    assert setup_jobs.status(workroot, "Demo")["state"] == state
    assert path.read_bytes() == before, "old attempt remains available as history"


def test_other_selected_folder_does_not_hide_or_release_active_model_job(tmp_path):
    workroot, old, selected = tmp_path / "work", tmp_path / "old", tmp_path / "new"
    job = setup_jobs.start(workroot, "Demo", old, "fixture")
    visible = setup_jobs.status(workroot, "Demo", expected_root=selected)
    assert visible["id"] == job.id and visible["active"] and visible["can_stop"]
    with pytest.raises(setup_jobs.BusyError):
        setup_jobs.start(workroot, "Demo", selected, "fixture")
    setup_jobs.stop(workroot, "Demo", job.id)
    assert setup_jobs.status(workroot, "Demo", expected_root=selected)["state"] == "stopping"


def test_orphan_is_recovered_in_old_folder_but_not_displayed_for_new_folder(tmp_path, spawn_job):
    workroot, old, selected = tmp_path / "work", tmp_path / "old", tmp_path / "new"
    process, pipe, original = spawn_job(workroot, old)
    pipe.send("crash")
    process.join(10)
    assert process.exitcode == 23
    assert setup_jobs.status(workroot, "Demo", expected_root=selected) is None
    assert not selected.exists()
    recovered = setup_jobs.status(workroot, "Demo", expected_root=old)
    assert recovered["id"] == original["id"] and recovered["state"] == "interrupted"
    _assert_revoked(old)


@pytest.mark.parametrize("same_model,same_root,same_workroot", [
    (True, False, True), (False, True, True), (False, True, False),
])
def test_live_local_leases_cover_model_and_canonical_root(tmp_path, same_model, same_root, same_workroot):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    owner = setup_jobs.start(workroot, "Demo", root, "fixture")
    with pytest.raises(setup_jobs.BusyError) as error:
        setup_jobs.start(workroot if same_workroot else tmp_path / "other-work",
                         "Demo" if same_model else "Other",
                         root / "sub" / ".." if same_root else tmp_path / "other-root", "fixture")
    assert error.value.job["id"] == owner.id
    assert owner.snapshot()["state"] == "running"


def test_cross_process_leases_and_live_status(tmp_path, spawn_job):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    process, pipe, snapshot = spawn_job(workroot, root)
    assert setup_jobs.status(workroot, "Demo")["state"] == "running"
    with pytest.raises(setup_jobs.BusyError):
        setup_jobs.start(workroot, "Demo", tmp_path / "different", "fixture")
    with pytest.raises(setup_jobs.BusyError):
        setup_jobs.start(tmp_path / "other-work", "Other", root, "fixture")
    with pytest.raises(setup_jobs.BusyError):
        with setup_jobs.idle_guard(workroot, "Demo", root):
            pytest.fail("guard acquired live job")
    pipe.send("finish")
    assert _recv(pipe)[1]["state"] == "completed"
    process.join(10)
    replacement = setup_jobs.start(workroot, "Demo", root, "fixture")
    assert replacement.id != snapshot["id"]


def test_cross_process_idle_guard_excludes_start(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    process = ctx.Process(target=_child_idle, args=(str(workroot), str(root), child))
    process.start()
    child.close()
    try:
        assert _recv(parent) == "held"
        with pytest.raises(setup_jobs.BusyError):
            setup_jobs.start(workroot, "Demo", tmp_path / "elsewhere", "fixture")
        with pytest.raises(setup_jobs.BusyError):
            setup_jobs.start(workroot, "Other", root, "fixture")
        parent.send("release")
        process.join(10)
        assert process.exitcode == 0
        setup_jobs.start(workroot, "Demo", root, "fixture")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
        parent.close()


def test_cross_process_stop_signals_owner_and_cancel_dominates_success(tmp_path, spawn_job):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    process, pipe, snapshot = spawn_job(workroot, root, mode="cancel")
    result = setup_jobs.stop(workroot, "Demo", snapshot["id"])
    assert result["state"] == "stopping"
    assert not result["can_stop"]
    assert _recv(pipe)[1]["state"] == "cancelled"
    process.join(10)
    assert process.exitcode == 0
    _assert_revoked(root)


def test_crash_recovery_revokes_stale_pass_and_releases_leases(tmp_path, spawn_job):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    process, pipe, snapshot = spawn_job(workroot, root)
    _seed_verified(root)  # verifier passed immediately before simulated host crash
    pipe.send("crash")
    process.join(10)
    assert process.exitcode == 23
    recovered = setup_jobs.status(workroot, "Demo")
    assert recovered["id"] == snapshot["id"]
    assert recovered["state"] == "interrupted"
    assert execution.stop_requested(root, turn_id=snapshot["turn_id"])
    assert (root / execution.STOP_MARKER).is_file()
    _assert_revoked(root)
    replacement = setup_jobs.start(workroot, "Demo", root, "fixture")
    assert replacement.id != snapshot["id"]
    assert not execution.stop_requested(root, turn_id=replacement.turn_id)
    assert execution.stop_requested(root, turn_id=snapshot["turn_id"])


def test_recovering_old_model_does_not_revoke_new_owner_result(tmp_path, spawn_job):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    process, pipe, _ = spawn_job(workroot, root, model="Old")
    pipe.send("crash")
    process.join(10)
    new = setup_jobs.start(workroot, "New", root, "fixture")
    _seed_verified(root)
    new.finish("completed")
    assert setup_jobs.status(workroot, "Old")["state"] == "interrupted"
    assert json.loads((root / "status.json").read_text())["ok"] is True
    assert setup_jobs.status(workroot, "New")["state"] == "completed"
    assert not execution.stop_requested(root, turn_id=new.turn_id)


def test_start_new_folder_recovers_abandoned_old_folder_first(tmp_path, spawn_job):
    workroot, oldroot = tmp_path / "work", tmp_path / "old"
    process, pipe, _ = spawn_job(workroot, oldroot)
    _seed_verified(oldroot)
    pipe.send("crash")
    process.join(10)
    setup_jobs.start(workroot, "Demo", tmp_path / "new", "fixture")
    _assert_revoked(oldroot)


def test_stale_stop_cannot_cancel_replacement_generation(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    old = setup_jobs.start(workroot, "Demo", root, "fixture")
    old.finish("completed")
    new = setup_jobs.start(workroot, "Demo", root, "fixture")
    with pytest.raises(ValueError, match="attempt changed"):
        setup_jobs.stop(workroot, "Demo", old.id)
    assert not execution.stop_requested(root, turn_id=new.turn_id)
    assert not new.handle.stopped.is_set()
    assert new.snapshot()["state"] == "running"


def test_old_generation_stop_does_not_touch_new_marker(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    later_turn = execution.begin_turn(root)
    setup_jobs.stop(workroot, "Demo", job.id)
    assert not execution.stop_requested(root, turn_id=later_turn)
    assert job.finish("completed")["state"] == "cancelled"


def test_cancel_cleanup_serializes_against_new_start(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    setup_jobs.stop(workroot, "Demo", job.id)
    seen = []

    def cleanup(state):
        seen.append(state)
        with pytest.raises(setup_jobs.BusyError):
            setup_jobs.start(tmp_path / "another-work", "Other", root, "fixture")

    result = job.finish("completed", cleanup=cleanup)
    assert result["state"] == "cancelled"
    assert seen == ["cancelled"]
    setup_jobs.start(workroot, "Demo", root, "fixture")


@pytest.mark.parametrize("state", ["failed", "interrupted", "cancelled"])
def test_failure_finalization_revokes_and_calls_cleanup(tmp_path, state):
    root = tmp_path / "runtime"
    job = setup_jobs.start(tmp_path / "work", "Demo", root, "fixture")
    _seed_verified(root)
    seen = []
    assert job.finish(state, cleanup=seen.append)["state"] == state
    assert seen == [state]
    _assert_revoked(root)


def test_cleanup_exception_fails_closed_and_releases_ownership(tmp_path):
    root, workroot = tmp_path / "root", tmp_path / "work"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    _seed_verified(root)

    def fail_cleanup(state):
        raise RuntimeError("fixture bookkeeping failed")

    result = job.finish("completed", cleanup=fail_cleanup)
    assert result["state"] == "failed"
    assert "fixture bookkeeping failed" in result["detail"]
    _assert_revoked(root)
    setup_jobs.start(workroot, "Demo", root, "fixture")


def test_failed_finish_preserves_authoritative_preflight_reason(tmp_path):
    root = tmp_path / "runtime"
    job = setup_jobs.start(tmp_path / "work", "Demo", root, "fixture")
    error = {"name": "preflight", "detail": "Required soil parameter table is missing."}
    (root / "status.json").write_text(json.dumps({
        "ok": False, "primary_error": error, "runtime_identity": "stale"}), encoding="utf-8")
    job.finish("failed", "Setup did not complete")
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert status["primary_error"] == error
    assert status["runtime_identity"] is None


def test_terminal_failure_replaces_initial_pending_status_in_durable_records(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    _seed_verified(root)
    job = setup_jobs.start(workroot, "Demo", root, "api:fixture")
    initial = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert initial["primary_error"] == {
        "name": "setup-job", "detail": "Setup is running; verification is pending."}
    detail = "PermissionError: fixture lease cannot be read"
    job.finish("failed", detail)

    # Read through the public durable polling route after the job has released
    # its lease, and inspect the separately persisted installation verdict.
    terminal = setup_jobs.status(workroot, "Demo")
    owner = json.loads((root / ".geoforge/setup-job-owner.json").read_text(encoding="utf-8"))
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert terminal["state"] == owner["state"] == "failed"
    assert terminal["detail"] == owner["detail"] == detail
    assert not terminal["active"] and not terminal["can_stop"]
    assert status["primary_error"] == {"name": "setup-job", "detail": detail}
    _assert_revoked(root)


@pytest.mark.parametrize("error", [
    {"name": "preflight", "detail": "Missing mandatory cultivar deck"},
    {"name": "ki-integrity", "detail": "Active KI changed"},
    {"name": "setup-job", "detail": "Provider did not finish required verification"},
    {"name": "preflight", "detail": "Setup is running; verification is pending."},
])
def test_terminal_failure_preserves_all_errors_except_exact_pending_sentinel(tmp_path, error):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    job = setup_jobs.start(workroot, "Demo", root, "api:fixture")
    (root / "status.json").write_text(json.dumps({"ok": False, "primary_error": error}),
                                     encoding="utf-8")
    job.finish("failed", "Later provider error")
    assert setup_jobs.status(workroot, "Demo")["state"] == "failed"
    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert status["primary_error"] == error
    _assert_revoked(root)


def test_finish_commit_and_stop_are_linearized(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "runtime"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    in_cleanup, release = threading.Event(), threading.Event()
    stop_result, finish_result = [], []

    def cleanup(state):
        assert state == "completed"
        in_cleanup.set()
        assert release.wait(5)

    finisher = threading.Thread(target=lambda: finish_result.append(job.finish("completed", cleanup=cleanup)))
    stopper = threading.Thread(target=lambda: stop_result.append(setup_jobs.stop(workroot, "Demo", job.id)))
    finisher.start()
    assert in_cleanup.wait(3)
    stopper.start()
    try:
        # Stop cannot be accepted halfway through the serialized terminal commit.
        assert not execution.stop_requested(root, turn_id=job.turn_id)
    finally:
        release.set()
        finisher.join(5)
        stopper.join(5)
    assert not finisher.is_alive() and not stopper.is_alive()
    assert finish_result[0]["state"] == stop_result[0]["state"] == "completed"
    assert not execution.stop_requested(root, turn_id=job.turn_id)


def test_stop_does_not_wait_for_blocked_http_response_close(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "root"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    closing, release = threading.Event(), threading.Event()

    class Response:
        def close(self):
            closing.set()
            release.wait(10)

    job.handle.attach(Response())
    try:
        before = time.monotonic()
        assert setup_jobs.stop(workroot, "Demo", job.id)["state"] == "stopping"
        assert time.monotonic() - before < 1
        assert closing.wait(3)
        with pytest.raises(install.InstallStopped):
            job.check_cancelled()
    finally:
        release.set()


def test_stop_terminates_owned_silent_cli_process(tmp_path):
    workroot, root = tmp_path / "work", tmp_path / "root"
    job = setup_jobs.start(workroot, "Demo", root, "fixture")
    kwargs = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
              else {"start_new_session": True})
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
    job.events["_process_handle"] = proc
    try:
        setup_jobs.stop(workroot, "Demo", job.id)
        proc.wait(timeout=10)
        assert proc.returncode is not None
        assert job.finish("completed")["state"] == "cancelled"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def test_stop_all_signals_every_local_job(tmp_path):
    jobs = [setup_jobs.start(tmp_path / "work", name, tmp_path / name, "fixture")
            for name in ("One", "Two")]
    setup_jobs.stop_all()
    for job in jobs:
        assert job.handle.stopped.wait(3)
        assert job.finish("completed")["state"] == "cancelled"


def test_shutdown_waits_until_concurrent_cli_termination_is_scheduled(tmp_path, monkeypatch):
    job = setup_jobs.start(tmp_path / "work", "Demo", tmp_path / "root", "fixture")
    entered, release, scheduled, returned = (threading.Event() for _ in range(4))

    class Process:
        def poll(self):
            return None

    def terminate(proc):
        entered.set()
        assert release.wait(5)
        scheduled.set()

    job.events["_process_handle"] = Process()
    monkeypatch.setattr(execution, "terminate_tree", terminate)
    watcher = threading.Thread(target=job._signal)
    watcher.start()
    assert entered.wait(3)

    def shutdown():
        setup_jobs.stop_all()
        assert scheduled.is_set()
        returned.set()

    quitting = threading.Thread(target=shutdown)
    quitting.start()
    try:
        assert not returned.wait(0.1), "shutdown returned before the watcher scheduled termination"
    finally:
        release.set()
        watcher.join(5)
        quitting.join(5)
    assert returned.is_set()
    assert not watcher.is_alive() and not quitting.is_alive()
