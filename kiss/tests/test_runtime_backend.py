"""WSL transport contracts and explicitly opted-in disposable guest fixtures.

No compiler/package installation or scientific model runs occur here.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

import pytest

from kiss_cli import runtime_backend as backend


def binding():
    value = uuid.uuid4().hex
    return backend.WSLBinding("Ubuntu", "dministrator",
                             "/home/dministrator/.local/share/geoforge/runtimes/" + value, value)


@pytest.mark.parametrize("field,value", [
    ("user", "root"), ("user", "--root"), ("distro", "--exec"),
    ("distro", "Ubuntu\nother"), ("workspace", "/tmp/anything"),
    ("workspace", "C:/not-linux"), ("python", "/mnt/c/python.exe"),
    ("workspace_id", "../escape"),
])
def test_binding_rejects_unscoped_or_privileged_selection(field, value):
    with pytest.raises(ValueError):
        replace(binding(), **{field: value})


def test_binding_identity_tracks_exact_selection_and_implementation():
    selected = binding()
    assert backend.binding_identity(selected) == backend.binding_identity(selected)
    assert backend.binding_identity(selected) != backend.binding_identity(replace(selected, distro="Other"))


def test_stop_before_launch_does_not_start_transport(monkeypatch):
    monkeypatch.setattr(backend, "_command", lambda *_: pytest.fail("must not launch"))
    selected = binding()
    result = backend.run(selected, ["/usr/bin/true"], cwd=selected.workspace, stop=lambda: True)
    assert result.status == "stopped" and result.process_started is False


def fake_worker(monkeypatch, body):
    source = ("import sys,json\n"
              "q=json.loads(sys.stdin.buffer.readline())\n"
              "b=q['binding']\n"
              "identity={'protocol':q['protocol'],'user':b['user'],'uid':1000,"
              "'workspace':b['workspace'],'workspace_id':b['workspace_id']}\n" + body)
    monkeypatch.setattr(backend, "_command", lambda _b: [sys.executable, "-I", "-S", "-c", source])


def test_wrong_request_response_cannot_be_accepted(monkeypatch):
    fake_worker(monkeypatch, "print(json.dumps({'event':'result','request_id':'0'*32,'ok':True,'identity':identity,'result':{}}))")
    with pytest.raises(backend.RuntimeBackendError, match="another request"):
        backend.inspect(binding())


def test_unannounced_output_and_unknown_messages_are_rejected(monkeypatch):
    fake_worker(monkeypatch, "print(json.dumps({'event':'stdout','data':'YWJj'}))")
    with pytest.raises(backend.RuntimeBackendError, match="preceded"):
        backend.inspect(binding())


def test_disconnect_after_start_preserves_uncertain_started_state(monkeypatch):
    fake_worker(monkeypatch, "print(json.dumps({'event':'started','request_id':q['request_id'],'pid':123,'argv':q['argv'],'cwd':q['cwd']}))")
    selected = binding()
    result = backend.run(selected, ["/usr/bin/true"], cwd=selected.workspace)
    assert result.status == "transport_error" and result.process_started is True
    assert "uncertain" in result.detail


def test_worker_cannot_change_bound_user(monkeypatch):
    fake_worker(monkeypatch, "identity['user']='root'\nprint(json.dumps({'event':'result','request_id':q['request_id'],'ok':True,'identity':identity,'result':identity}))")
    with pytest.raises(backend.RuntimeBackendError, match="bound Linux user"):
        backend.inspect(binding())


def test_staged_proof_must_match_exact_host_file_bytes(monkeypatch):
    monkeypatch.setattr(backend, "_exchange", lambda *_a, **_k:
                        ({"file": {"bytes": 3, "sha256": "0" * 64}}, {}, {}))
    with pytest.raises(backend.RuntimeBackendError, match="host bytes"):
        backend.write_files(binding(), {"file": b"abc"})


def test_read_proof_must_match_exported_bytes(monkeypatch):
    monkeypatch.setattr(backend, "_exchange", lambda *_a, **_k:
                        ({"file": {"data": "YWJj", "bytes": 3, "sha256": "0" * 64}}, {}, {}))
    with pytest.raises(backend.RuntimeBackendError, match="evidence"):
        backend.read_files(binding(), ["file"])


@pytest.fixture(scope="module")
def guest():
    if os.environ.get("GEOFORGE_TEST_WSL") != "1":
        pytest.skip("set GEOFORGE_TEST_WSL=1 only for the authorized disposable WSL fixture")
    selected = binding()
    backend.prepare(selected)
    return selected


def test_guest_identity_is_stable_and_linux_native(guest):
    first, second = backend.inspect(guest), backend.inspect(guest)
    assert first["identity_sha256"] == second["identity_sha256"]
    assert first["uid"] != 0 and first["filesystem"] in {"0xef53", "0x58465342", "0x9123683e"}
    assert first["transport"]["request_id"] != second["transport"]["request_id"]


def test_guest_colon_case_files_roundtrip_without_overwrite(guest):
    files = {"files/Case:00.txt": b"UPPER\r\n", "files/case:00.txt": b"lower\n"}
    proof = backend.write_files(guest, files)
    assert set(proof["files"]) == set(files)
    result = backend.read_files(guest, list(files))
    assert {name: record["data"] for name, record in result.items()} == files
    with pytest.raises(backend.RuntimeBackendError, match="different bytes"):
        backend.write_files(guest, {"files/Case:00.txt": b"replacement"})
    assert backend.read_files(guest, ["files/Case:00.txt"])["files/Case:00.txt"]["data"] == files["files/Case:00.txt"]


@pytest.mark.parametrize("path", ["../escape", "/tmp/escape", "files/../../escape", "files\\escape"])
def test_guest_rejects_path_escape(guest, path):
    with pytest.raises(backend.RuntimeBackendError):
        backend.write_files(guest, {path: b"must not write"})


def test_guest_rejects_symlink_parent(guest):
    code = "import os;os.symlink('/tmp','escape-link')"
    result = backend.run(guest, ["/usr/bin/python3", "-c", code], cwd=guest.workspace)
    assert result.returncode == 0, result.detail
    with pytest.raises(backend.RuntimeBackendError, match="symbolic link"):
        backend.write_files(guest, {"escape-link/forbidden": b"must not write"})


def test_guest_rejects_fifo_without_blocking(guest):
    result = backend.run(guest, ["/usr/bin/python3", "-c", "import os;os.mkfifo('fixture-fifo')"], cwd=guest.workspace)
    assert result.returncode == 0
    with pytest.raises(backend.RuntimeBackendError, match="ordinary"):
        backend.read_files(guest, ["fixture-fifo"])


def test_guest_byte_stdin_streams_and_nonzero(guest):
    payload = b"literal\r\n\xc3\xa9\n"
    code = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.write('diagnostic');raise SystemExit(7)"
    result = backend.run(guest, ["/usr/bin/python3", "-c", code], cwd=guest.workspace,
                         stdin=payload, timeout=10)
    assert result.status == "finished" and result.returncode == 7
    assert result.stdout.encode("utf-8") == payload and result.stderr == "diagnostic"
    assert result.evidence["process"]["group_stopped"]


def test_guest_closed_default_stdin(guest):
    result = backend.run(guest, ["/usr/bin/python3", "-c", "import sys;print(len(sys.stdin.buffer.read()))"],
                         cwd=guest.workspace, timeout=10)
    assert result.returncode == 0 and result.stdout == "0\n"


def test_guest_rejects_shell_and_identity_environment_override(guest):
    result = backend.run(guest, ["/bin/sh", "-c", "echo forbidden"], cwd=guest.workspace)
    assert result.returncode is None and result.process_started is False
    result = backend.run(guest, ["/usr/bin/true"], cwd=guest.workspace, env={"WSL_INTEROP": "forbidden"})
    assert result.returncode is None and result.process_started is False


def test_guest_timeout(guest):
    result = backend.run(guest, ["/usr/bin/python3", "-c", "import time;time.sleep(30)"],
                         cwd=guest.workspace, timeout=.3)
    assert result.status == "timed_out" and result.process_started
    assert result.evidence["process"]["group_stopped"]


def test_guest_cancel_kills_detached_descendant_only(guest):
    code = ("import subprocess,sys,time,pathlib;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);"
            "pathlib.Path('cancel-child.pid').write_text(str(p.pid));time.sleep(60)")
    started = time.monotonic()
    result = backend.run(guest, ["/usr/bin/python3", "-c", code], cwd=guest.workspace, timeout=20,
                         stop=lambda: time.monotonic() - started > 1.5)
    assert result.status == "stopped" and result.evidence["process"]["group_stopped"], result
    child = int(backend.read_files(guest, ["cancel-child.pid"])["cancel-child.pid"]["data"])
    check = backend.run(guest, ["/usr/bin/python3", "-c",
        "import pathlib,sys;sys.exit(pathlib.Path('/proc/'+sys.argv[1]).exists())", str(child)], cwd=guest.workspace)
    assert check.returncode == 0, check
    assert backend.inspect(guest)["user"] == guest.user


def test_guest_cancel_preserves_another_supervisors_process(guest):
    stop = threading.Event()
    result = []
    code = "import os,pathlib,time;pathlib.Path('unrelated.pid').write_text(str(os.getpid()));time.sleep(30)"
    thread = threading.Thread(target=lambda: result.append(backend.run(
        guest, ["/usr/bin/python3", "-c", code], cwd=guest.workspace, timeout=30, stop=stop.is_set)))
    thread.start()
    try:
        time.sleep(.8)
        other = backend.run(guest, ["/usr/bin/python3", "-c", "import time;time.sleep(30)"],
                            cwd=guest.workspace, timeout=.3)
        assert other.status == "timed_out"
        pid = int(backend.read_files(guest, ["unrelated.pid"])["unrelated.pid"]["data"])
        check = backend.run(guest, ["/usr/bin/python3", "-c", "import os,sys;os.kill(int(sys.argv[1]),0)", str(pid)],
                            cwd=guest.workspace)
        assert check.returncode == 0 and thread.is_alive()
    finally:
        stop.set()
        thread.join(timeout=15)
    assert not thread.is_alive() and result[0].status == "stopped"


def test_guest_local_executor_uses_same_identity_without_wsl(guest):
    source = Path(backend.__file__)
    backend.write_files(guest, {"local/runtime_backend.py": source.read_bytes(),
                        "local/_wsl_worker.py": source.with_name("_wsl_worker.py").read_bytes()})
    code = ("import sys,json;sys.path.insert(0,sys.argv[1]);import runtime_backend as b;"
            "v=b.WSLBinding(**json.loads(sys.argv[2]));e=b.LocalExecutor();"
            "r=e.run(v,['/usr/bin/python3','-c','print(42)'],cwd=v.workspace);"
            "assert r.returncode==0 and r.stdout=='42\\n';print(e.inspect(v)['identity_sha256'])")
    result = backend.run(guest, ["/usr/bin/python3", "-c", code, guest.workspace + "/local",
                                json.dumps(asdict(guest))], cwd=guest.workspace, timeout=30)
    assert result.returncode == 0, result
    assert result.stdout.strip() == backend.inspect(guest)["identity_sha256"]

