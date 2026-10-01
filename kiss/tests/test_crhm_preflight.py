"""Installed CRHM discovery and startup must reflect the actual platform."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


PATH = Path(__file__).resolve().parents[2] / "models/CRHM/preflight_check.py"
SPEC = importlib.util.spec_from_file_location("crhm_preflight_test", PATH)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_native_binary_prefers_windows_install_and_keeps_linux(tmp_path):
    windows = tmp_path / "crhm/bin/crhm.exe"
    linux = tmp_path / "crhmcode/crhmcode/build/crhm"
    for path in (windows, linux):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert preflight.native_binary(tmp_path, "win32") == windows
    assert preflight.native_binary(tmp_path, "linux") == linux
    windows.unlink()
    assert preflight.native_binary(tmp_path, "win32") == linux


def test_missing_windows_binary_reports_expected_install_path(tmp_path):
    assert preflight.native_binary(tmp_path, "win32") == tmp_path / "crhm/bin/crhm.exe"


@pytest.mark.parametrize("code,output,expected", [
    (0, "crhm [options] PROJECT_FILE", True),
    (1, "crhm [options] PROJECT_FILE", True),
    (0, "", False),
    (2, "crhm [options] PROJECT_FILE", False),
    (0xC0000005, "crhm [options] PROJECT_FILE", False),
    (-1073741819, "crhm [options] PROJECT_FILE", False),
    (-11, "crhm [options] PROJECT_FILE", False),
])
def test_help_rejects_crashes_even_after_banner(monkeypatch, code, output, expected):
    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=code, stdout=output, stderr=""))
    monkeypatch.setattr(preflight, "checks", [])
    assert preflight.check_binary_starts() is expected
    assert preflight.checks[-1]["status"] == ("pass" if expected else "fail")
