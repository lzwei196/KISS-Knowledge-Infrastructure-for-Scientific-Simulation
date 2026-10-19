"""Studio auto evidence must remain within its explicitly selected source."""
import json
from pathlib import Path

import pytest


from kiss_cli import kdtstudio as studio

@pytest.fixture
def job(tmp_path):
    root = tmp_path / "job"
    source = root / "probe" / "source"
    source.mkdir(parents=True)
    (root / "runs").mkdir()
    (source / "README.md").write_text("This WRF source only", encoding="utf-8")
    local = tmp_path / "selected-local"
    local.mkdir()
    return root, source, {"source_type": "local", "source": str(local)}


def report(root, value):
    (root / "probe" / "probe_report.json").write_text(
        json.dumps(value), encoding="utf-8")


def test_actual_engine_source_dir_inventories_only_this_ki(job, tmp_path, monkeypatch):
    root, source, doc = job
    # Reproduce the service cwd containing other KIs, engine docs and papers.
    outside = tmp_path / "profile" / "quarantine" / "OtherKI" / "docs"
    outside.mkdir(parents=True)
    (outside / "manual.md").write_text("Other model 10.1234/not-wrf", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    report(root, {"source_dir": str(source), "model_name": "WRF_Hydro"})
    monkeypatch.setattr(studio, "_meta", lambda _: (root, doc))
    result = studio.evidence_inventory("job")
    assert result["ready"] is True
    assert Path(result["source_root"]) == source
    found = {item["kind"]: item for item in result["items"]}
    assert found["official_docs"]["automatic"] == ["README.md"]
    assert found["literature"]["automatic"] == []
    assert found["literature"]["state"] == "agent_can_resolve"


@pytest.mark.parametrize("value", [
    {}, [], None, {"source_dir": ""}, {"source_dir": " "},
    {"source_dir": None}, {"source_dir": 123}, {"source_dir": []},
    {"source_root": ""}, {"source_root": None}, {"source_dir": "."},
    {"source_dir": "probe/source"}, {"source_dir": "~/source"},
])
def test_missing_invalid_or_relative_metadata_never_falls_back_to_cwd(job, monkeypatch, value):
    root, source, doc = job
    monkeypatch.chdir(source)
    report(root, value)
    monkeypatch.setattr(studio, "_meta", lambda _: (root, doc))
    result = studio.evidence_inventory("job")
    assert result["ready"] is False
    assert result["source_root"] is None
    assert all(not item["automatic"] for item in result["items"])


def test_absent_or_malformed_report_has_no_inventory(job):
    root, _, doc = job
    assert studio._probe_source(root, doc) is None
    (root / "probe" / "probe_report.json").write_text("{bad", encoding="utf-8")
    assert studio._probe_source(root, doc) is None


@pytest.mark.parametrize("kind", ["parent", "sibling", "file", "missing"])
def test_unrelated_or_missing_report_path_is_rejected(job, tmp_path, kind):
    root, source, doc = job
    sibling = tmp_path / "OtherKI"
    sibling.mkdir()
    path = {"parent": tmp_path, "sibling": sibling,
            "file": source / "README.md", "missing": tmp_path / "missing"}[kind]
    report(root, {"source_dir": str(path)})
    assert studio._probe_source(root, doc) is None


@pytest.mark.parametrize("key", ["source_dir", "source_root"])
def test_legacy_exact_selected_local_source_is_allowed(job, key):
    root, _, doc = job
    source = Path(doc["source"])
    report(root, {key: str(source)})
    assert studio._probe_source(root, doc) == source
    assert studio._probe_source(root, {**doc, "source_type": "git"}) is None


def test_nested_git_probe_source_and_matching_legacy_keys(job):
    root, source, _ = job
    nested = source / "repo"
    nested.mkdir()
    report(root, {"source_dir": str(nested), "source_root": str(nested)})
    assert studio._probe_source(root, {"source_type": "git"}) == nested


@pytest.mark.parametrize("other", ["selected", "blank", "invalid"])
def test_conflicting_or_invalid_alias_is_not_ignored(job, other):
    root, source, doc = job
    value = {"selected": doc["source"], "blank": "", "invalid": []}[other]
    report(root, {"source_dir": str(source), "source_root": value})
    assert studio._probe_source(root, doc) is None


def test_resolved_probe_escape_is_rejected(job, tmp_path, monkeypatch):
    root, source, doc = job
    outside = tmp_path / "other-model"
    outside.mkdir()
    alias = source / "escaped"
    alias.mkdir()
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        return outside if path == alias else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)
    report(root, {"source_dir": str(alias)})
    assert studio._probe_source(root, doc) is None


def test_supplied_evidence_remains_separate_when_probe_is_invalid(job, monkeypatch):
    root, _, doc = job
    report(root, {})
    (root / "runs" / "user-evidence.json").write_text(json.dumps([
        {"kind": "literature", "source_type": "link", "value": "https://doi.org/10.1234/user"}
    ]), encoding="utf-8")
    monkeypatch.setattr(studio, "_meta", lambda _: (root, doc))
    result = studio.evidence_inventory("job")
    literature = next(item for item in result["items"] if item["kind"] == "literature")
    assert result["ready"] is False
    assert literature["state"] == "found"
    assert literature["automatic"] == []
    assert len(literature["supplied"]) == 1
