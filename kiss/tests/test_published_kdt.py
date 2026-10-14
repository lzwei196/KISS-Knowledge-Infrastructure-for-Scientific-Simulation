"""The publication profile changes three reviewed KDT literature sites only."""
import ast
import copy
import hashlib
import shutil
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import kdtstudio, ki_verification, published_kdt as profile


_ENGINE = kdtstudio.engine_root()


@pytest.fixture
def base_source():
    source = _ENGINE / "verify_ki_structure.py"
    if not source.is_file():
        pytest.skip("Reviewed KDT source is not installed")
    return source.read_text(encoding="utf-8")


@pytest.fixture
def gate(base_source, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(_ENGINE))
    with kdtstudio._engine_imports():
        yield kdtstudio._load_engine_module("verify_ki_structure.py", "published_profile_test")


@pytest.fixture
def bibliography(monkeypatch):
    import kiss_cli
    helper = types.ModuleType("kiss_cli.published_literature")
    helper.calls = []
    helper.result = {"ok": True, "present": True, "count": 1,
                     "failures": [], "warnings": [], "info": {"evidence": "metadata"}}

    def check(root, *, model_name, kind="process_model"):
        helper.calls.append((root, model_name, kind))
        return copy.deepcopy(helper.result)

    helper.check = check
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    monkeypatch.setattr(kiss_cli, "published_literature", helper, raising=False)
    return helper


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "preflight_check.py").write_text(
        "print('PREFLIGHT_REPORT={\"checks\": []}')\n", encoding="utf-8")
    return root


def test_profile_patch_preserves_every_unrelated_ast_node(base_source):
    assert hashlib.sha256(base_source.encode()).hexdigest() == profile.BASE_SOURCE_SHA256
    assert len(profile._PROFILE_EDITS) == 3
    patched = profile._profile_source(base_source)
    # Reverse only the three explicitly reviewed hunks, then compare the full
    # module AST. Any other changed import, function, check or return fails.
    recovered = patched
    for before, after in reversed(profile._PROFILE_EDITS):
        assert recovered.count(after) == 1
        recovered = recovered.replace(after, before, 1)
    assert ast.dump(ast.parse(recovered)) == ast.dump(ast.parse(base_source))
    assert "_published_literature_check(ki, kind=kind)" in patched
    assert "if gp.is_file() and _model_reqs:" not in patched
    assert "gp.is_file()" not in patched


@pytest.mark.parametrize("mutation", ["\n# unreviewed change\n", "\nMIN_TOOLS = 0\n"])
def test_unknown_base_verifier_fails_closed(base_source, mutation):
    with pytest.raises(profile.PublishedProfileError, match="no reviewed"):
        profile._profile_source(base_source + mutation)


def test_gate_view_rejects_unknown_engine_without_calling_helper(gate, tmp_path, bibliography):
    other = tmp_path / "verify_ki_structure.py"
    other.write_text("def verify(root): return {'ok': True}\n", encoding="utf-8")
    with mock.patch.object(gate, "__file__", str(other)):
        with pytest.raises(profile.PublishedProfileError, match="no reviewed"):
            profile.gate_view(gate, model_name="Demo")
    assert not bibliography.calls


def test_private_profile_keeps_authoring_and_frozen_runtime_proxy(gate, bibliography, candidate):
    original = gate.verify
    proxy = ki_verification._GateRuntimeSys(sys.executable)
    gate.sys = proxy
    view = profile.gate_view(gate, model_name="Demo")
    result = ki_verification._portable_tool_index_verifier(view)(candidate, kind="process_model")
    authoring = ki_verification._portable_tool_index_verifier(gate)(candidate, kind="process_model")
    assert gate.verify is original and gate.sys is proxy and view.sys is proxy
    assert bibliography.calls == [(candidate, "Demo", "process_model")]
    assert result["info"]["literature_profile"] == "published_metadata"
    assert any("gathered_papers.json missing" in failure for failure in authoring["failures"])
    assert not any("gathered_papers.json missing" in failure for failure in result["failures"])
    assert any("validation_convention.yaml missing" in failure for failure in result["failures"])
    for common_failure in ("SKILL.md missing", "tools/", "diagnostics/triplets.yaml missing", "dag.yaml missing"):
        assert any(common_failure in failure for failure in authoring["failures"])
        assert any(common_failure in failure for failure in result["failures"])
    assert not result["ok"]


def test_missing_metadata_and_missing_convention_both_block(gate, bibliography, candidate):
    bibliography.result.update(ok=False, present=False, count=0,
                               failures=["Published papers metadata missing"])
    view = profile.gate_view(gate, model_name="Demo")
    result = ki_verification._portable_tool_index_verifier(view)(candidate, kind="process_model")
    assert "Published papers metadata missing" in result["failures"]
    assert any("validation_convention.yaml missing" in item for item in result["failures"])
    assert not result["ok"]


def test_profile_keeps_existing_convention_content_checks(gate, bibliography, candidate):
    (candidate / "docs").mkdir()
    (candidate / "dag.yaml").write_text("outputs:\n - var: discharge\n", encoding="utf-8")
    (candidate / "docs" / "validation_convention.yaml").write_text(
        "validation:\n - dag_variable: absent_output\n   headline_metrics:\n"
        "    - metric: nse\n      bands: {good: 0.7}\n", encoding="utf-8")
    view = profile.gate_view(gate, model_name="Demo")
    result = ki_verification._portable_tool_index_verifier(view)(candidate, kind="process_model")
    assert any("not a dag output" in failure for failure in result["failures"])
    assert any("NO citation" in failure for failure in result["failures"])
    assert not result["ok"]


def test_task_workflow_missing_literature_and_convention_remain_advisory(gate, bibliography, candidate):
    bibliography.result.update(present=False, count=0, warnings=["Workflow bibliography absent"])
    view = profile.gate_view(gate, model_name="Workflow")
    result = ki_verification._portable_tool_index_verifier(view)(candidate, kind="task_workflow")
    assert bibliography.calls == [(candidate, "Workflow", "task_workflow")]
    assert "Workflow bibliography absent" in result["warnings"]
    assert not any("validation_convention.yaml missing" in item for item in result["failures"])
    assert any("validation_convention.yaml missing" in item for item in result["warnings"])


def test_unrecognized_kind_cannot_relax_publication_literature(candidate, bibliography):
    with pytest.raises(profile.PublishedProfileError, match="Unsupported"):
        profile._checked_literature(candidate, "Demo", "library")
    assert not bibliography.calls


@pytest.mark.parametrize("bad", [None, {}, {"ok": 1}, {"count": True},
                                    {"count": -1}, {"failures": "bad"},
                                    {"ok": False}, {"present": False},
                                    {"count": 0}, {"failures": ["bad"]}])
def test_invalid_checker_results_fail_closed(candidate, bibliography, bad):
    if bad is None or bad == {}:
        bibliography.result = bad
    else:
        bibliography.result.update(bad)
    with pytest.raises(profile.PublishedProfileError, match="invalid result"):
        profile._checked_literature(candidate, "Demo")


def test_profile_identity_includes_both_modules(monkeypatch, tmp_path, bibliography):
    helper_source = tmp_path / "published_literature.py"
    helper_source.write_text("VALUE = 1\n", encoding="utf-8")
    bibliography.__file__ = str(helper_source)
    first = profile.profile_source_digest()
    helper_source.write_text("VALUE = 2\n", encoding="utf-8")
    assert profile.profile_source_digest() != first
    with mock.patch.object(profile, "PROFILE_POLICY", "next-reviewed-policy"):
        assert profile.profile_source_digest() != first


def test_frozen_profile_identity_uses_complete_importer_code(tmp_path):
    module = types.ModuleType("fixture_frozen_profile")
    module.__file__ = str(tmp_path / "missing.pyc")
    module.__loader__ = types.SimpleNamespace(get_code=lambda name: compile("VALUE=1", name, "exec"))
    first = profile._module_identity(module)
    module.__loader__ = types.SimpleNamespace(get_code=lambda name: compile("VALUE=2", name, "exec"))
    assert profile._module_identity(module) != first
    module.__loader__ = None
    with pytest.raises(profile.PublishedProfileError, match="Cannot identify"):
        profile._module_identity(module)


def test_real_published_adcirc_passes_profile_but_not_authoring(gate, tmp_path):
    source = Path("D:/GeoForge-Model-Tests-20261010/ki-updates/quarantine/066789f876dd/models/ADCIRC")
    if not source.is_dir():
        pytest.skip("Read-only ADCIRC publication fixture is not available")
    before = ki_verification.content_digest(source)
    root = tmp_path / "adcirc"
    shutil.copytree(source, root)
    # Match the host's structural-only preflight contract: no candidate code
    # executes and a critical check explicitly defers native software testing.
    (root / "preflight_check.py").write_text(
        "import json\n"
        "report={'checks':[{'kind':'run','subject':'deferred','critical':True,"
        "'status':'fail','fix':'Run GeoForge software setup and verification'}]}\n"
        "print('PREFLIGHT_REPORT='+json.dumps(report))\nraise SystemExit(1)\n",
        encoding="utf-8")
    view = profile.gate_view(gate, model_name="ADCIRC")
    published = ki_verification._portable_tool_index_verifier(view)(root, kind="process_model")
    authoring = ki_verification._portable_tool_index_verifier(gate)(root, kind="process_model")
    assert published["ok"], published["failures"]
    assert published["info"]["published_literature"]["dag_deferred_count"] == 4
    assert not authoring["ok"]
    assert any("gathered_papers.json missing" in item for item in authoring["failures"])
    assert ki_verification.content_digest(source) == before
