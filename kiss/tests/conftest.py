"""Keep the desktop test suite off the user's real GeoForge Database state.

Without this, a test that reaches ``obs_access.search_catalogue`` would read the
activation token from the macOS Keychain, page the live catalogue, and write the
app-level store under Application Support.
"""
import pytest

from kiss_cli import obs_access


@pytest.fixture(autouse=True)
def _isolated_catalogue_store(tmp_path, monkeypatch):
    # Launcher/setup tests must not overwrite the real user's helper scripts
    # or read saved provider settings merely because they run on Windows.
    home = tmp_path / "user-home"
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setattr(obs_access, "catalogue_store_path",
                        lambda: tmp_path / ".geoforge-test-store" / "catalogue.json")
    monkeypatch.setattr(obs_access.secret_store, "get_secret", lambda *_a, **_k: None)
    obs_access.retry_token_access()
    yield
    obs_access.retry_token_access()
