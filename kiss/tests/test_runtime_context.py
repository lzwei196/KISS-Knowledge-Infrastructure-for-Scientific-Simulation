"""Cross-OS readiness cannot be imported into a different service binding."""
import json
from types import SimpleNamespace
import pytest
from kiss_cli import firstrun, paths, runtime_context, software_verification
from kiss_cli import project_verification as pv
from .test_project_verification import case


@pytest.fixture(autouse=True)
def reset_identity():
    clear = runtime_context.identity.cache_clear
    clear()
    yield
    clear()


def test_backend_change_invalidates_real_signed_project_receipt(case, monkeypatch):
    project, ki, man, cfg, _ = case
    monkeypatch.setattr(runtime_context, "binding", lambda: {"kind": "native", "platform": "Windows"})
    result = pv.verify(project, ki, man)
    assert result["ok"]
    before = software_verification.runtime_identity(cfg)
    monkeypatch.setattr(runtime_context, "binding", lambda: {"kind": "wsl", "distro": "Ubuntu", "id": "new"})
    assert software_verification.runtime_identity(cfg) != before
    assert not pv.status(project, ki, man)["can_run"]
    with pytest.raises(ValueError):
        pv.require_current(project, ki.name, ki.root)


def test_nonce_is_endpoint_identity_not_persistent_binding(monkeypatch):
    monkeypatch.setattr(runtime_context, "identity", lambda: {"kind": "wsl", "id": "same", "nonce": "first"})
    first = runtime_context.binding()
    monkeypatch.setattr(runtime_context, "identity", lambda: {"kind": "wsl", "id": "same", "nonce": "next"})
    assert runtime_context.binding() == first


def test_linux_identity_rejected_in_windows_service(monkeypatch):
    monkeypatch.setenv("GEOFORGE_RUNTIME_IDENTITY", json.dumps(dict(id="test", distro="Ubuntu", user="test", workspace="/home/test/runtime", source_hash="a"*64, nonce="random")))
    monkeypatch.setattr(runtime_context.platform, "system", lambda: "Windows")
    with pytest.raises(ValueError, match="must run in Linux"):
        runtime_context.identity()


def test_incomplete_identity_does_not_fall_back_to_native(monkeypatch):
    monkeypatch.setenv("GEOFORGE_RUNTIME_IDENTITY", '{"id":"untrusted"}')
    with pytest.raises(ValueError):
        runtime_context.identity()


def test_private_profile_override_is_explicit_and_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_APP_DATA_DIR", str(tmp_path / "private"))
    assert firstrun.data_dir() == tmp_path / "private"
    assert not firstrun.data_dir().exists()
    monkeypatch.setenv("GEOFORGE_APP_DATA_DIR", "../other")
    with pytest.raises(ValueError):
        firstrun.data_dir()
