"""The host KDT adapter must read the same UTF-8 KI bytes on every locale."""
from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import kdtstudio, ki_verification as gate


_REVIEWED_ENGINE = kdtstudio.engine_root()
_TEXT = "river water — température 水温\n"


@pytest.fixture
def gbk_default(monkeypatch):
    """Exercise the affected default independently of the test host's locale."""
    original = Path.open
    original_read_text = Path.read_text

    def open_with_gbk(self, mode="r", buffering=-1, encoding=None,
                      errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "gbk"
        return original(self, mode, buffering, encoding, errors, newline)

    def read_text_with_locale(self, encoding=None, errors=None):
        # UTF-8 mode resolves an omitted encoding before calling Path.open.
        # Keep this fixture's legacy default explicit, without changing an
        # encoding supplied by the host's private UTF-8 adapter.
        return original_read_text(self, encoding="locale" if encoding is None else encoding,
                                  errors=errors)

    monkeypatch.setattr(Path, "open", open_with_gbk)
    monkeypatch.setattr(Path, "read_text", read_text_with_locale)


def test_utf8_adapter_is_private_and_propagates_to_helper_paths(tmp_path, monkeypatch, gbk_default):
    (tmp_path / "docs").mkdir()
    (tmp_path / "dag.yaml").write_text(_TEXT, encoding="utf-8")
    (tmp_path / "docs" / "triplets.yaml").write_text(_TEXT, encoding="utf-8")
    helper = types.ModuleType("ki_projection_common")
    exec("def read_triplet_entries(root):\n"
         " return (root/'docs'/'triplets.yaml').read_text()\n"
         "def tool_files(root):\n return []\n", helper.__dict__)
    monkeypatch.setitem(sys.modules, "ki_projection_common", helper)
    verifier = types.ModuleType("fixture_verifier")
    exec("from pathlib import Path\n"
         "def verify(root, *, kind=None):\n"
         " from ki_projection_common import tool_files, read_triplet_entries\n"
         " root=Path(root)\n"
         " return [(root/'dag.yaml').read_text(), read_triplet_entries(root),\n"
         "         next(root.glob('docs/*.yaml')).read_text()]\n", verifier.__dict__)
    original_reader = helper.read_triplet_entries
    adapted = gate._portable_tool_index_verifier(verifier)
    assert adapted(tmp_path) == [_TEXT] * 3
    assert verifier.Path is Path and helper.read_triplet_entries is original_reader
    with pytest.raises(UnicodeDecodeError):
        verifier.verify(tmp_path)


def test_utf8_adapter_keeps_strict_errors_and_explicit_encoding(tmp_path, gbk_default):
    bad = tmp_path / "invalid.yaml"
    bad.write_bytes(b"description: \xff\n")
    verifier = types.ModuleType("fixture_verifier")
    exec("from pathlib import Path\n"
         "def verify(root, *, kind=None):\n"
         " return Path(root).read_text(encoding=kind)\n", verifier.__dict__)
    adapted = gate._portable_tool_index_verifier(verifier)
    with pytest.raises(UnicodeDecodeError, match="utf-8"):
        adapted(bad)
    assert adapted(bad, kind="latin-1") == "description: ÿ\n"


@pytest.fixture
def fixture_engine(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    for relative in kdtstudio.REQUIRED_ENGINE_FILES:
        path = engine / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(engine))
    monkeypatch.setenv("GEOFORGE_KDT_HOME", str(tmp_path / "studio"))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "receipts"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    return engine


@pytest.mark.parametrize("frozen", [False, True])
def test_host_gate_utf8_keeps_safe_preflight_and_semantic_failures(
        fixture_engine, tmp_path, gbk_default, frozen):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "dag.yaml").write_text(_TEXT, encoding="utf-8")
    marker = tmp_path / "untrusted-preflight-ran"
    (candidate / "preflight_check.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
    (fixture_engine / "verify_ki_structure.py").write_text(
        "from pathlib import Path\nimport sys, subprocess\n"
        "def verify(root, *, kind=None):\n"
        " root=Path(root)\n"
        " text=(root/'dag.yaml').read_text()\n"
        " result=subprocess.run([sys.executable,str(root/'preflight_check.py')],"
        "capture_output=True,text=True)\n"
        f" assert text == {_TEXT!r}\n"
        " assert 'deferred' in result.stdout\n"
        " return {'ok':False,'failures':['required literature missing']}\n",
        encoding="utf-8")
    before = gate.content_digest(candidate)
    engine_before = kdtstudio.engine_source_digest()
    with (mock.patch.object(gate, "_frozen_windows", return_value=frozen),
          mock.patch.object(gate, "_preflight_interpreter", return_value=sys.executable)):
        report = gate.verify_candidate(candidate, desktop=False)
    assert report["failures"] == ["required literature missing"]
    assert not report["ok"] and not marker.exists()
    assert gate.content_digest(candidate) == before
    assert kdtstudio.engine_source_digest() == engine_before


def test_previous_locale_policy_receipt_requires_reverification(fixture_engine, tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "preflight_check.py").write_text("print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
    (fixture_engine / "verify_ki_structure.py").write_text(
        "def verify(root, *, kind=None):\n return {'ok':True,'failures':[]}\n", encoding="utf-8")
    with mock.patch.object(gate, "GATE_POLICY", "ki-draft-kdt-v2-portable-tool-index"):
        report = gate.verify_candidate(candidate, desktop=False)
    with pytest.raises(gate.VerificationError, match="another gate contract"):
        gate.require_current(candidate, report, desktop=False)


def test_real_pinned_gate_utf8_retains_content_validation(tmp_path, monkeypatch, gbk_default):
    # Copy only the installed reviewed engine. Candidate code never executes.
    with mock.patch.object(kdtstudio, "engine_root", return_value=_REVIEWED_ENGINE):
        if not _REVIEWED_ENGINE.is_dir() or not kdtstudio.engine_status().get("installed"):
            pytest.skip("Reviewed KDT engine is not installed on this test host")
    engine = tmp_path / "engine"
    shutil.copytree(_REVIEWED_ENGINE, engine, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(engine))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "receipts"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    candidate = tmp_path / "candidate"
    (candidate / "docs").mkdir(parents=True)
    (candidate / "SKILL.md").write_text("# UTF-8 KI\n" + _TEXT, encoding="utf-8")
    (candidate / "dag.yaml").write_text(
        "identity:\n  model_id: UnicodeModel\noutputs:\n"
        "  - var: river_water\n    unit: m\n"
        "    description: " + _TEXT +
        "    observability:\n      comparable_obs_shapes: [point]\n", encoding="utf-8")
    (candidate / "knowledge_infrastructure.yaml").write_text(
        "package:\n  name: UnicodeModel\nvalidation: {}\n"
        "summary:\n  total_tools: 99\n", encoding="utf-8")
    (candidate / "docs" / "format_spec.yaml").write_text(
        "outputs:\n  primary:\n    - name: river_water\n      unit: wrong\n"
        "known_issues: []\n", encoding="utf-8")
    (candidate / "preflight_check.py").write_text("print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
    before = gate.content_digest(candidate)
    report = gate.verify_candidate(candidate, desktop=False)
    failures = report["failures"]
    assert not any("does not parse" in item or "CRASHED" in item or "UnicodeDecodeError" in item
                   for item in failures)
    assert any("docs/gathered_papers.json missing" in item for item in failures)
    assert any("manifest: total_tools=99" in item for item in failures)
    assert any("unit disagrees with the dag" in item for item in failures)
    assert not report["ok"] and gate.content_digest(candidate) == before
