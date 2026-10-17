"""The release's real WOFOST KI must survive first setup and GUI projection.

These tests never substitute the small published-preflight fixture for the
model that users receive. The real shared helpers are projected too. Native
model execution and AI providers are outside this static integration check.
"""
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

import pytest

from kiss_cli import ki_adaptations, ki_guard, paths, setup
from kiss_cli.manifest import Manifest


REPO = Path(__file__).resolve().parents[2]
CHECK = runpy.run_path(str(REPO / "tools/windows_release_smoke.py"))["check_wofost_projection"]


@pytest.fixture
def short_workspace():
    # Actual bundled helpers have deep filenames. Keep test scaffolding below
    # Windows MAX_PATH instead of consuming that limit with pytest node names.
    with tempfile.TemporaryDirectory(prefix="gf-wp-") as directory:
        yield Path(directory).resolve()


@pytest.fixture
def isolated_authority(short_workspace, monkeypatch):
    for name, folder in (
        ("GEOFORGE_FLOW_KEYS", "keys"),
        ("GEOFORGE_KI_GUARD_HOME", "guard"),
        ("GEOFORGE_KI_ADAPTATION_HOME", "adaptations"),
        ("GEOFORGE_KI_VERIFICATION_HOME", "verification"),
    ):
        monkeypatch.setenv(name, str(short_workspace / folder))

    def forbid_process(*_args, **_kwargs):
        pytest.fail("Static bundled KI projection must not launch a process")
    monkeypatch.setattr(subprocess, "run", forbid_process)
    monkeypatch.setattr(subprocess, "Popen", forbid_process)


def test_real_bundled_wofost_setup_then_fresh_gui_project_and_reopen(short_workspace, isolated_authority):
    result = CHECK(REPO, short_workspace / "work", Path(sys.executable))
    assert result["passed"]
    assert result["shared_setup_projection"] and result["fresh_gui_project_projection"]
    assert result["retained_project_reopen"] and result["saved_runtime_and_helpers_bound"]
    assert "preflight_check.py" in result["source_files"]
    assert "tools/s3_weather_prep/convert_vic_to_pcse_weather.py" in result["source_files"]
    assert result["source_unchanged"]
    assert not any(result[key] for key in
        ("preflight_passed", "model_execution", "scientific_validation", "frozen_code_execution"))


def test_actual_bundled_preflight_check_mutation_still_refused(short_workspace, isolated_authority):
    source = short_workspace / "modified-library/models/WOFOST"
    shutil.copytree(REPO / "models/WOFOST", source)
    preflight = source / "preflight_check.py"
    original = preflight.read_text(encoding="utf-8")
    assert "check_import(checks, module, critical=True)" in original
    preflight.write_text(original.replace("check_import(checks, module, critical=True)",
        "check_import(checks, module, critical=False)", 1), encoding="utf-8")
    cfg = paths.KissConfig.default(short_workspace / "workspace")
    cfg.python = str(Path(sys.executable).resolve())
    setup.prepare_common(cfg, REPO)
    target = cfg.root / "ki"
    with pytest.raises(ki_adaptations.AdaptationError, match="Unsupported WOFOST fresh path contract"):
        setup.materialise_active(source, target, cfg,
            manifest=Manifest.load(REPO / "kiss/manifests/WOFOST.yaml"), library_root=REPO)
    assert not target.exists()
    assert not ki_guard.is_managed(target)
