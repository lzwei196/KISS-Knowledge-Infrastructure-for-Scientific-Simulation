"""Manager integration tests: real packaging, fake transport, no WSL/models."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import threading
import time

import pytest

from kiss_cli import linux_sidecar as sidecar
from kiss_cli.runtime_backend import RunResult


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    files = {
        "kiss/kiss_cli/cli.py": b"# app\n",
        "kiss/kiss_cli/web/app.html": b"<html>app</html>",
        "kiss/manifests/Sample.yaml": b"model: Sample\n",
        "ki_tools_common/ki_tools_common/__init__.py": b"# helper\n",
        "ki_tools_common/pyproject.toml": b"[project]\nname='sample'\n",
        "models/Sample/SKILL.md": b"# Sample KI\n",
        "models/Sample/test_cases/input.dat": b"test case\n",
        "kiss/data_kis/example/SKILL.md": b"# data KI\n",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def manager(source, tmp_path):
    return sidecar.SidecarManager(source_root=source, models_root=source / "models", host_state=tmp_path / "state")


def private_settings():
    return {"api_keys": {"DEEPSEEK_API_KEY": "test-selected-key", "OPENAI_API_KEY": "not-selected"},
            "default_provider": "api:deepseek", "proxy_mode": "off", "database_token": "never-copy",
            "status": "verified", "flow_keys": "never-copy"}


def wait_for(check, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.01)
    assert check(), "background manager did not reach expected state"


class FakeTransport:
    def __init__(self):
        self.files = {}
        self.calls = []
        self.boot_request = None
        self.started = threading.Event()

    def prepare(self, binding):
        self.calls.append(("prepare", binding))
        return {"identity_sha256": "identity"}

    def write_files(self, binding, files):
        for name, data in files.items():
            assert name not in self.files or self.files[name] == data
            self.files[name] = data
        self.calls.append(("write", tuple(files)))

    def run(self, binding, argv, **kwargs):
        self.calls.append(("run", argv, kwargs))
        if "kiss_cli.cli" in argv:
            self.started.set()
            wait_for(kwargs["stop"], timeout=10)
            return RunResult("stopped", -15, process_started=True)
        if argv[-1].endswith(".py"):
            self.boot_request = json.loads(kwargs["stdin"])
            return RunResult("finished", 0, stdout=json.dumps({"ok": True, "source_hash": self.boot_request["source_hash"]}))
        if sidecar._PYTHON_CHECK in argv:
            return RunResult("finished", 0, stdout=json.dumps({"missing": [], "pip_available": True}))
        if "-c" in argv:
            return RunResult("finished", 0, stdout="[]")
        return RunResult("finished", 0)


@pytest.fixture
def transport(monkeypatch):
    fake = FakeTransport()
    monkeypatch.setattr(sidecar.runtime_backend, "prepare", fake.prepare)
    monkeypatch.setattr(sidecar.runtime_backend, "write_files", fake.write_files)
    monkeypatch.setattr(sidecar.runtime_backend, "run", fake.run)
    monkeypatch.setattr(sidecar, "_wsl_command", lambda *_a, **_k: json.dumps({
        "user": "scientist", "uid": 1000, "home": "/home/scientist", "python_version": [3, 12, 3]}))
    monkeypatch.setattr(sidecar, "_available_port", lambda: 18881)
    return fake


def test_payload_excludes_state_and_caches_but_keeps_model_cases(source):
    for name in ("models/Sample/kiss.toml", "models/Sample/status.json", "models/Sample/.geoforge/approval.json",
                 "kiss/kiss_cli/__pycache__/x.pyc", "ki_tools_common/tests/test_secret.py"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not copy")
    fingerprint, rows, _ = sidecar.source_inventory(source, source / "models")
    assert len(fingerprint) == 64
    assert "library/models/Sample/test_cases/input.dat" in rows
    assert "library/ki_tools_common/pyproject.toml" in rows
    assert not any("approval" in name or "secret" in name or "kiss.toml" in name or "status.json" in name for name in rows)


def test_source_change_revokes_fingerprint(source):
    before = sidecar.source_fingerprint(source, source / "models")
    (source / "kiss/kiss_cli/cli.py").write_text("# changed\n")
    assert sidecar.source_fingerprint(source, source / "models") != before


def test_selected_library_keeps_its_matching_helpers_and_manifests(source, tmp_path):
    library = tmp_path / "latest"
    for name, text in {"models/Sample/SKILL.md": "latest model", "kiss/manifests/Sample.yaml": "latest manifest",
                       "ki_tools_common/ki_tools_common/__init__.py": "latest helper"}.items():
        path = library / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _, _, files = sidecar.source_inventory(source, library / "models")
    assert files["library/ki_tools_common/ki_tools_common/__init__.py"].read_text() == "latest helper"
    assert files["ki_tools_common/ki_tools_common/__init__.py"].read_text() == "# helper\n"
    assert files["library/kiss/manifests/Sample.yaml"].read_text() == "latest manifest"


def test_private_settings_copy_only_selected_key(monkeypatch):
    result = sidecar._provider_settings(private_settings(), "api:deepseek")
    assert result["api_keys"] == {"DEEPSEEK_API_KEY": "test-selected-key"}
    assert "database_token" not in result and "flow_keys" not in result and "status" not in result
    assert "not-selected" not in json.dumps(result)
    automatic = {**private_settings(), "proxy_mode": "auto", "proxy_providers": ["network:github", "cli:codex"]}
    monkeypatch.setattr(sidecar.settings if hasattr(sidecar, "settings") else __import__("kiss_cli.settings", fromlist=["x"]),
                        "detected_system_proxy", lambda: pytest.fail("must not resolve Windows auto proxy"))
    result = sidecar._provider_settings(automatic, "api:deepseek")
    assert result["proxy_mode"] == "auto" and "proxy_url" not in result
    assert result["proxy_providers"] == ["network:github", "network:obs"]


def test_manual_loopback_proxy_requires_a_reachable_linux_setting():
    with pytest.raises(sidecar.SidecarError, match="loopback"):
        sidecar._provider_settings({**private_settings(), "proxy_mode": "manual", "proxy_url": "http://127.0.0.1:7890",
                                    "proxy_providers": ["api:deepseek"]}, "api:deepseek")


def test_stage_is_deterministic_and_contains_only_manifest_bytes(source, tmp_path, transport):
    current = manager(source, tmp_path)
    current._binding = current._select_binding("Ubuntu", "scientist")
    fingerprint, rows, files = sidecar.source_inventory(source, source / "models")
    first, _ = current._stage(fingerprint, rows, files, "first")
    second, _ = current._stage(fingerprint, rows, files, "second")
    assert first == second
    payload = b"".join(transport.files[name] for name in first["parts"])
    assert hashlib.sha256(payload).hexdigest() == first["archive_sha256"]
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        assert set(archive.getnames()) == set(rows)
        for member in archive:
            data = archive.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest() == rows[member.name]["sha256"]


def test_launch_uses_real_dispatch_staging_private_profile_and_identity(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    state = current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    assert state["state"] == "starting" and "url" not in state
    wait_for(lambda: current._view()["state"] in {"ready", "failed"})
    assert current.status()["state"] == "ready", current.status()
    assert "nonce" not in current.status()["runtime_identity"]
    assert "test-selected-key" not in json.dumps(current.status())
    command, env = next((call[1], call[2]["env"]) for call in transport.calls if call[0] == "run" and "kiss_cli.cli" in call[1])
    assert command[command.index("--models") + 1].endswith("/library/models")
    assert command[command.index("--workroot") + 1].endswith("/work")
    assert env["GEOFORGE_APP_DATA_DIR"].endswith("/profile")
    assert "/work/" not in env["GEOFORGE_FLOW_KEYS"]
    assert "API_KEY" not in json.dumps(env)
    assert transport.boot_request["settings"]["api_keys"] == {"DEEPSEEK_API_KEY": "test-selected-key"}
    assert not any("pip" in call[1] for call in transport.calls if call[0] == "run")
    current.stop()
    wait_for(lambda: current._view()["state"] == "stopped")


def test_wrong_port_identity_never_publishes_url(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: {"nonce": "other-server"})
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] == "failed")
    assert "url" not in current.status()
    assert current._stop.is_set()
    wait_for(lambda: not current._server_thread.is_alive())


def test_source_drift_stops_backend_and_revokes_url(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] == "ready")
    (source / "kiss/kiss_cli/cli.py").write_text("# second build\n")
    state = current.status()
    assert state["state"] == "stale" and "url" not in state
    assert current._stop.is_set()
    wait_for(lambda: not current._server_thread.is_alive())


def test_unavailable_identity_can_recover_without_adopting_other_server(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] == "ready")
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: (_ for _ in ()).throw(OSError("offline")))
    assert current.status()["state"] == "unavailable"
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    assert current.status()["state"] == "ready"
    current.stop()
    wait_for(lambda: not current._server_thread.is_alive())


def test_describe_discovers_named_default_user_without_installing(monkeypatch):
    calls = []
    def probe(argv, **_kw):
        calls.append(argv)
        return "Ubuntu\n" if argv == ["--list", "--quiet"] else json.dumps({
            "user": "scientist", "uid": 1000, "home": "/home/scientist", "python_version": [3, 12, 3]})
    monkeypatch.setattr(sidecar, "_wsl_command", probe)
    result = sidecar.describe()
    assert result["available"] and result["distributions"][0]["user"] == "scientist"
    assert not any("install" in arg or "bash" in arg for call in calls for arg in call)


def test_bootstrap_diagnostics_are_actionable_without_private_values(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    original = transport.run
    def fail_bootstrap(binding, argv, **kwargs):
        if argv[-1].endswith(".py"):
            return RunResult("finished", 1, stderr="missing application dependency; test-selected-key")
        return original(binding, argv, **kwargs)
    monkeypatch.setattr(sidecar.runtime_backend, "run", fail_bootstrap)
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] == "failed")
    public = json.dumps(current.status())
    diagnostic = (tmp_path / "state/last-error.json").read_text()
    assert "missing application dependency" in public and "[redacted]" in diagnostic
    assert "test-selected-key" not in public + diagnostic
    assert "stdin" not in diagnostic and "env" not in diagnostic


def test_server_exception_is_reported_and_startup_preserves_cause(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    original = transport.run
    def fail_server(binding, argv, **kwargs):
        if "kiss_cli.cli" in argv:
            raise sidecar.runtime_backend.RuntimeBackendError("server transport rejected this identity")
        return original(binding, argv, **kwargs)
    monkeypatch.setattr(sidecar.runtime_backend, "run", fail_server)
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._thread and not current._thread.is_alive())
    assert current.status()["state"] == "failed"
    assert "server transport rejected this identity" in current.status()["detail"]
    assert "url" not in current.status()
    assert not current._server_thread.is_alive()


def test_missing_ensurepip_reuses_partial_venv_without_installing_present_app_deps(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    original = transport.run
    def no_ensurepip(binding, argv, **kwargs):
        if "venv" in argv:
            assert "--without-pip" in argv and "--system-site-packages" in argv
            assert "--clear" not in argv
        if sidecar._PYTHON_CHECK in argv:
            transport.calls.append(("run", argv, kwargs))
            return RunResult("finished", 0, stdout=json.dumps({"missing": [], "pip_available": False}))
        assert sidecar._PIP_INSTALL not in argv
        return original(binding, argv, **kwargs)
    monkeypatch.setattr(sidecar.runtime_backend, "run", no_ensurepip)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] in {"ready", "failed"})
    assert current.status()["state"] == "ready", current.status()
    current.stop()
    wait_for(lambda: not current._server_thread.is_alive())


def test_missing_app_dependency_installs_through_guarded_venv_pip_only(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    original = transport.run
    installed = []
    def missing_truststore(binding, argv, **kwargs):
        if sidecar._PYTHON_CHECK in argv:
            return RunResult("finished", 0, stdout=json.dumps({"missing": [] if installed else ["truststore"], "pip_available": True}))
        if sidecar._PIP_INSTALL in argv:
            installed.append(argv)
            return RunResult("finished", 0)
        return original(binding, argv, **kwargs)
    monkeypatch.setattr(sidecar.runtime_backend, "run", missing_truststore)
    monkeypatch.setattr(sidecar, "_read_identity", lambda _url: dict(current._identity))
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] in {"ready", "failed"})
    assert current.status()["state"] == "ready", current.status()
    assert len(installed) == 1
    assert installed[0][0].endswith("/appenv/bin/python") and installed[0][1] == "-I"
    assert installed[0][-2:] == [current._binding.workspace + "/appenv", "truststore>=0.10.4"]
    assert "--require-virtualenv" in sidecar._PIP_INSTALL and "--prefix" in sidecar._PIP_INSTALL
    assert "PIP_CONFIG_FILE" in sidecar._PIP_INSTALL
    current.stop()
    wait_for(lambda: not current._server_thread.is_alive())


def test_wrong_python_prefix_blocks_install_and_server(source, tmp_path, transport, monkeypatch):
    current = manager(source, tmp_path)
    original = transport.run
    def wrong_prefix(binding, argv, **kwargs):
        if sidecar._PYTHON_CHECK in argv:
            return RunResult("finished", 1, stderr="Application Python is not the expected isolated virtual environment")
        assert sidecar._PIP_INSTALL not in argv and "kiss_cli.cli" not in argv
        return original(binding, argv, **kwargs)
    monkeypatch.setattr(sidecar.runtime_backend, "run", wrong_prefix)
    current.launch(distro="Ubuntu", user="scientist", provider_settings=private_settings())
    wait_for(lambda: current._view()["state"] == "failed")
    assert "isolated virtual environment" in current.status()["detail"]
