"""State commits remain signed/current across Windows sharing and concurrent I/O."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from ki_tools_common.flow import receipts, states


@pytest.fixture
def state_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project = tmp_path / "project"
    project.mkdir()
    ctx = states.FlowContext(project)
    ctx.save()
    return ctx


def sharing_error(code=32):
    error = PermissionError(errno.EACCES, "fixture Windows file sharing conflict")
    error.winerror = code
    return error


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement retry contract")
@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_replace_retries_one_unique_temp_and_publishes_only_after_success(state_case, monkeypatch, code):
    ctx = state_case
    target = ctx._path(ctx.project)
    original_replace = os.replace
    previous = receipts.current_value(ctx.project, "state")
    attempts, waits = [], []
    def replace(source, dest):
        if Path(dest) == target:
            attempts.append(Path(source))
            if len(attempts) < 3:
                assert receipts.current_value(ctx.project, "state") == previous
                raise sharing_error(code)
        return original_replace(source, dest)
    def sleep(delay):
        waits.append(delay)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(states.time, "sleep", sleep)
    ctx.state = states.State.PLANNING
    ctx.save()
    assert len(attempts) == 3 and len(set(attempts)) == 1 and len(waits) == 2
    assert attempts[0].name != f"flow-state.{os.getpid()}.json"
    assert states.FlowContext.load(ctx.project).state == states.State.PLANNING
    assert receipts.current_value(ctx.project, "state") != previous
    assert not list((ctx.project / ".geoforge/tmp").glob("flow-state.*.json"))


@pytest.mark.parametrize("retryable", [True, False])
def test_persistent_or_unrelated_failure_never_replaces_target_or_publishes(state_case, monkeypatch, retryable):
    ctx = state_case
    target = ctx._path(ctx.project)
    before, pointer = target.read_bytes(), receipts.current_value(ctx.project, "state")
    original = os.replace
    attempts = []
    def replace(source, dest):
        if Path(dest) == target:
            attempts.append(Path(source))
            raise sharing_error() if retryable else OSError(errno.ENOSPC, "fixture disk full")
        return original(source, dest)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(states.time, "sleep", lambda _: None)
    with pytest.raises(OSError):
        ctx.save()
    assert len(attempts) == (len(states._REPLACE_DELAYS) + 1 if retryable and os.name == "nt" else 1)
    assert target.read_bytes() == before and receipts.current_value(ctx.project, "state") == pointer
    assert not list((ctx.project / ".geoforge/tmp").glob("flow-state.*.json"))


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement retry contract")
def test_retry_refuses_a_newer_external_state_or_pointer(state_case, monkeypatch):
    ctx = state_case
    target = ctx._path(ctx.project)
    newer = json.loads(target.read_text(encoding="utf-8"))
    newer.update(state="BLOCKED", state_nonce="external-newer", provider="newer")
    newer = receipts.sign(ctx.project, newer)
    original = os.replace
    attempts = []
    def replace(source, dest):
        if Path(dest) == target:
            attempts.append(source)
            # Simulate a non-cooperating external writer during a failed replace.
            # Normal app/CLI writers hold the same cross-process I/O lock.
            target.write_text(json.dumps(newer), encoding="utf-8")
            receipts.publish_current(ctx.project, "state", newer)
            raise sharing_error()
        return original(source, dest)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(states.time, "sleep", lambda _: None)
    with pytest.raises(states.FlowError, match="changed while saving"):
        ctx.save()
    assert len(attempts) == 1
    assert states.FlowContext.load(ctx.project).state == states.State.BLOCKED
    assert json.loads(target.read_text(encoding="utf-8")) == newer


def test_concurrent_writers_have_distinct_temps_and_reader_cannot_see_half_commit(state_case, monkeypatch):
    ctx = state_case
    target = ctx._path(ctx.project)
    original_replace, original_publish = os.replace, receipts.publish_current
    entered, release, reader_started = threading.Event(), threading.Event(), threading.Event()
    temps, results, failures = [], [], []
    def replace(source, dest):
        if Path(dest) == target:
            temps.append(Path(source))
        return original_replace(source, dest)
    def publish(project, kind, doc):
        if kind == "state" and doc.get("provider") == "first":
            entered.set()
            assert release.wait(5)
        return original_publish(project, kind, doc)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(receipts, "publish_current", publish)
    def writer(name):
        try:
            changed = states.FlowContext(ctx.project, provider=name)
            changed.save()
        except BaseException as error:
            failures.append(error)
    def reader():
        reader_started.set()
        try:
            results.append(states.FlowContext.load(ctx.project).provider)
        except BaseException as error:
            failures.append(error)
    first = threading.Thread(target=writer, args=("first",))
    second = threading.Thread(target=writer, args=("second",))
    read = threading.Thread(target=reader)
    first.start()
    try:
        assert entered.wait(5)
        second.start(); read.start()
        assert reader_started.wait(5)
        read.join(.05); second.join(.05)
        assert read.is_alive() and second.is_alive()
    finally:
        release.set()
        first.join(5)
        if second.ident is not None: second.join(5)
        if read.ident is not None: read.join(5)
    assert not failures and results[0] in {"first", "second"}
    assert len(temps) == 2 and len(set(temps)) == 2
    assert states.FlowContext.load(ctx.project).provider == "second"


@pytest.mark.skipif(os.name != "nt", reason="Real Windows deny-delete sharing handle")
def test_real_windows_read_handle_releases_before_bounded_retry(state_case, monkeypatch):
    import ctypes
    from ctypes import wintypes
    ctx = state_case
    target = ctx._path(ctx.project)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    held = [handle]
    errors = []
    original = os.replace
    def replace(source, dest):
        try:
            return original(source, dest)
        except OSError as error:
            if Path(dest) == target: errors.append(error.winerror)
            raise
    def release(_delay):
        if held: assert kernel.CloseHandle(held.pop())
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(states.time, "sleep", release)
    try:
        ctx.provider = "after-sharing-release"
        ctx.save()
    finally:
        release(0)
    assert errors and errors[0] in {5, 32, 33}
    assert states.FlowContext.load(ctx.project).provider == "after-sharing-release"


def test_state_io_lock_also_serializes_another_host_process(state_case):
    ctx = state_case
    script = '''import sys
from pathlib import Path
from ki_tools_common.flow import states
print("started", flush=True)
ctx = states.FlowContext.load(Path(sys.argv[1]))
ctx.provider = "child"
ctx.save()
print("saved", flush=True)
'''
    process = None
    try:
        with states._state_io_lock(ctx.project):
            process = subprocess.Popen([sys.executable, "-c", script, str(ctx.project)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert process.stdout.readline().strip() == "started"
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=.1)
        out, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        assert out.strip() == "saved"
        assert states.FlowContext.load(ctx.project).provider == "child"
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.communicate(timeout=5)
