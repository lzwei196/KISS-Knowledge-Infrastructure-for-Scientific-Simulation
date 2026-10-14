"""Exact projection and real installed-PCSE provider contract regressions.

Native positive certification is never mocked or skipped. Select a real
Python 3.12/PCSE 6.0.13 environment with GEOFORGE_WOFOST_TEST_PYTHON when the
reviewed Windows fixture environment is elsewhere.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from kiss_cli import ki_maintenance_wofost as recipe

ORIGINAL = Path(__file__).parent / "fixtures" / "wofost_stage6_published.py"
NATIVE_PYTHON = os.environ.get("GEOFORGE_WOFOST_TEST_PYTHON",
    "D:/GeoForge-Setup-Tracer-20261010/workroot/wofost/python_env/bin/python.exe")


def _trees(root: Path, source: bytes | None = None):
    base, candidate = root / "base", root / "candidate"
    for path in (base, candidate):
        (path / recipe.TOOL_PATH).parent.mkdir(parents=True)
    (base / recipe.TOOL_PATH).write_bytes(source if source is not None else ORIGINAL.read_bytes())
    projected = recipe.expected_changes(base, "WOFOST")
    (candidate / recipe.TOOL_PATH).write_bytes(projected[recipe.TOOL_PATH])
    return base, candidate


def _unsupported(root, raw):
    path = root / recipe.TOOL_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return recipe.expected_changes(root, "WOFOST")


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_exact_projection_preserves_unrelated_bytes_and_native_defaults(tmp_path, newline):
    raw = ORIGINAL.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    base, candidate = _trees(tmp_path, raw)
    old = (recipe._OLD_BLOCK + recipe._PARAMS).encode().replace(b"\n", newline)
    new = (recipe._NEW_BLOCK + recipe._PARAMS).encode().replace(b"\n", newline)
    before = (base / recipe.TOOL_PATH).read_bytes()
    after = (candidate / recipe.TOOL_PATH).read_bytes()
    assert after.replace(new, old, 1) == before
    assert b'site_values.setdefault("WAV", WAV)' in after
    assert b'SMLIM=' not in after
    assert b".pop(" not in after
    assert list(recipe.expected_changes(base, "WOFOST")) == [recipe.TOOL_PATH]


@pytest.mark.parametrize("old,new", [
    (b"WAV = 20", b"WAV = 50"),
    (b'CO2 = 400', b'CO2 = 450'),
    (b'engine.run_till_terminate()', b'engine.run(days=2)'),
    (b'cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)', b'cropdata.set_active_crop("maize", VARIETY_NAME)'),
    (b'df.to_csv(OUTPUT_CSV)', b'df.to_csv(OUTPUT_CSV, index=False)'),
    (b'WOFOST72SiteDataProvider(WAV=WAV)', b'WOFOST72SiteDataProvider(WAV=WAV, SMLIM=.3)'),
])
def test_semantic_variants_rejected_before_projection(tmp_path, old, new):
    raw = ORIGINAL.read_bytes()
    assert old in raw
    assert _unsupported(tmp_path, raw.replace(old, new, 1)) == {}


def test_comment_outside_block_is_preserved_but_block_comment_must_match(tmp_path):
    raw = ORIGINAL.read_bytes()
    base, candidate = _trees(tmp_path / "outside", b"# retained comment\n" + raw)
    assert (candidate / recipe.TOOL_PATH).read_bytes().startswith(b"# retained comment\n")
    changed = raw.replace(b"Use WAV only.", b"Use different values.")
    assert _unsupported(tmp_path / "inside", changed) == {}


def test_wrong_model_and_already_patched_runner_are_not_supported(tmp_path):
    base, candidate = _trees(tmp_path)
    assert recipe.expected_changes(base, "DSSAT") == {}
    assert recipe.expected_changes(candidate, "WOFOST") == {}
    assert recipe.expected_changes(tmp_path / "missing", "WOFOST") == {}
    report = recipe.validate_behavior(candidate, base, NATIVE_PYTHON)
    assert report["ok"] is False and report["native_provider_execution"] is False
    assert "No recognized" in report["error"]


def test_mixed_newlines_fail_closed(tmp_path):
    raw = ORIGINAL.read_bytes().replace(b"\r\n", b"\n")
    raw = raw.replace(b"\n", b"\r\n", 1)
    assert _unsupported(tmp_path, raw) == {}


def test_no_runtime_is_not_certification(tmp_path):
    base, candidate = _trees(tmp_path)
    report = recipe.validate_behavior(base, candidate, tmp_path / "missing-python.exe")
    assert report["ok"] is False
    assert report["status"] == "failed"
    assert report["native_provider_execution"] is False
    assert report["fixture_count"] == 0
    with pytest.raises(ValueError):
        recipe.require_runtime_current(report)


@pytest.mark.parametrize("python", ["python", "relative/python.exe"])
def test_relative_runtime_path_is_rejected(tmp_path, python):
    base, candidate = _trees(tmp_path)
    report = recipe.validate_behavior(base, candidate, python)
    assert report["ok"] is False
    assert "absolute" in report["error"]


def test_selected_venv_cannot_be_certified_against_base_pcse(tmp_path):
    base, candidate = _trees(tmp_path / "ki")
    environment = tmp_path / "different-venv"
    result = subprocess.run([NATIVE_PYTHON, "-I", "-B", "-m", "venv", "--without-pip", str(environment)],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib = environment / ("Lib/site-packages" if os.name == "nt" else "lib/python3.12/site-packages")
    pcse = purelib / "pcse"
    pcse.mkdir(exist_ok=True)
    (pcse / "__init__.py").write_text('__version__ = "different-selected-environment"\n', encoding="utf-8")
    selected = subprocess.run([str(executable), "-I", "-B", "-c", "import pcse; print(pcse.__version__)"],
                              capture_output=True, text=True, timeout=20)
    assert selected.returncode == 0 and selected.stdout.strip() == "different-selected-environment"
    report = recipe.validate_behavior(base, candidate, executable)
    assert report["ok"] is False and report["native_provider_execution"] is False
    assert "virtualenv" in report["error"]


def test_candidate_tampering_rejected_before_any_process(tmp_path, monkeypatch):
    base, candidate = _trees(tmp_path)
    path = candidate / recipe.TOOL_PATH
    path.write_bytes(path.read_bytes() + b"\nprint('unapproved')\n")
    def forbidden(*args, **kwargs):
        raise AssertionError("No process should be launched for an unapproved candidate")
    monkeypatch.setattr(recipe.subprocess, "run", forbidden)
    report = recipe.validate_behavior(base, candidate, NATIVE_PYTHON)
    assert report["ok"] is False
    assert "exact WOFOST" in report["error"]


@pytest.fixture(scope="module")
def native_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-wofost-provider-fixtures")
    base, candidate = _trees(root)
    originals = [(base / recipe.TOOL_PATH).read_bytes(), (candidate / recipe.TOOL_PATH).read_bytes()]
    report = recipe.validate_behavior(base, candidate, NATIVE_PYTHON)
    assert report["ok"], report.get("error", report)
    assert [(base / recipe.TOOL_PATH).read_bytes(), (candidate / recipe.TOOL_PATH).read_bytes()] == originals
    return report


def test_real_pcse_provider_fixtures_certify_only_interface(native_report):
    report = native_report
    assert report["runtime"]["pcse_version"] == "6.0.13"
    assert report["runtime"]["python_version"][:2] == [3, 12]
    assert report["native_provider_execution"] is True
    assert report["model_execution"] is False
    assert report["scientific_validation"] is False
    assert report["fixture_count"] == len(recipe.fixture_ids()) == 53
    assert [row["id"] for row in report["fixtures"]] == recipe.fixture_ids()
    assert recipe.require_runtime_current(report) is report
    rows = {row["id"]: row for row in report["fixtures"]}
    assert rows["old_valid_no_site"]["native_outcome"]["site"]["WAV"] == 20
    assert rows["old_valid_no_site"]["native_outcome"]["site"]["SMLIM"] == .4
    assert rows["all_six_original_site_values"]["native_outcome"]["site"]["WAV"] == 50
    assert rows["all_six_original_site_values"]["native_outcome"]["site"]["SMLIM"] == .31
    assert rows["native_lower_boundaries"]["native_outcome"]["site"]["WAV"] == 0
    assert rows["old_valid_unknown_soil_preserved"]["native_outcome"]["soil"]["UNCHANGED_EXTRA"] == 17
    for name in ["unrelated_soil_crop_duplicate", "unrelated_site_crop_duplicate", "mixed_site_and_unrelated_duplicate"]:
        assert "Duplicate parameter" in rows[name]["native_outcome"]["message"]


@pytest.mark.parametrize("mutation", ["ok", "fixture_missing", "fixture_failed", "fixture_input_changed",
    "count", "protocol", "runtime_version", "native", "model", "science", "isolation", "files_missing"])
def test_incomplete_or_downgraded_reports_cannot_be_reused(native_report, mutation):
    report = copy.deepcopy(native_report)
    if mutation == "ok": report["ok"] = False
    elif mutation == "fixture_missing": report["fixtures"].pop()
    elif mutation == "fixture_failed": report["fixtures"][0]["ok"] = False
    elif mutation == "fixture_input_changed": report["fixtures"][0]["input_unchanged"] = False
    elif mutation == "count": report["fixture_count"] = 0
    elif mutation == "protocol": report["fixture_protocol_sha256"] = "old"
    elif mutation == "runtime_version": report["runtime"]["pcse_version"] = "6.0.12"
    elif mutation == "native": report["native_provider_execution"] = False
    elif mutation == "model": report["model_execution"] = True
    elif mutation == "science": report["scientific_validation"] = True
    elif mutation == "isolation": report["isolation"]["scratch_user_settings"] = False
    elif mutation == "files_missing":
        report["runtime"]["files"] = []
        report["runtime_identity"] = recipe._hash(report["runtime"])
    with pytest.raises(ValueError):
        recipe.require_runtime_current(report)


def test_runtime_file_content_change_invalidates_report_without_native_execution(native_report, tmp_path, monkeypatch):
    report = copy.deepcopy(native_report)
    path = tmp_path / "dependency.py"
    path.write_bytes(b"original")
    report["runtime"]["files"].append({"path": str(path), "resolved_path": str(path.resolve()),
        "size": 8, "sha256": hashlib.sha256(b"original").hexdigest()})
    report["runtime_identity"] = recipe._hash(report["runtime"])
    recipe.require_runtime_current(report)
    path.write_bytes(b"modified")
    def forbidden(*args, **kwargs):
        raise AssertionError("Receipt freshness checks must not launch Python")
    monkeypatch.setattr(recipe.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="content changed"):
        recipe.require_runtime_current(report)
