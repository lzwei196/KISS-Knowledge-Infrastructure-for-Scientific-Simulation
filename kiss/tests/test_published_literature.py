"""Publication metadata is useful evidence without becoming authoring proof."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from kiss_cli import published_literature as literature


@pytest.fixture
def package(tmp_path):
    (tmp_path / "docs").mkdir()
    papers = {"model": "Example", "note": "Metadata only, no full texts.",
              "count": 1, "open_access": 1,
              "papers": [{"doi": "10.1234/Example", "title": "Example model",
                          "access": "open", "role": "A new domain-specific role",
                          "serves": ["an unrestricted domain quantity"]}]}
    convention = {"model_id": "Example", "references": {"model_paper": {"doi": "https://doi.org/10.1234/example"}},
                  "validation": [{"cites": ["model_paper"]}],
                  "deferred_paywalled": [{"doi": "10.4567/Deferred", "ref": "Unfetched study",
                                           "needed_for": ["water_temperature"]}]}
    dag = {"identity": {"model_id": "Example"}, "influence": {"citation_index": {
        "available": {"doi": "doi:10.1234/EXAMPLE"},
        "deferred": {"doi": "10.4567/deferred"}},
        "edges": [{"citations": ["available", "deferred"]}]}}
    for relative, doc in (("docs/papers.json", papers),
                          ("docs/validation_convention.yaml", convention), ("dag.yaml", dag)):
        write(tmp_path, relative, doc)
    return tmp_path


def write(root, relative, doc):
    text = json.dumps(doc, ensure_ascii=False) if relative.endswith(".json") else yaml.safe_dump(doc)
    (root / relative).write_text(text, encoding="utf-8")


def edit(root, relative, mutate):
    doc = yaml.safe_load((root / relative).read_text(encoding="utf-8"))
    mutate(doc)
    write(root, relative, doc)


def check(package):
    return literature.check(package, model_name="Example")


def test_metadata_and_deferred_are_distinct_and_input_bytes_unchanged(package):
    before = {p: p.read_bytes() for p in package.rglob("*") if p.is_file()}
    result = check(package)
    assert result["ok"] and result["present"] and result["count"] == 1
    assert result["info"]["validation_reference_count"] == 1
    assert result["info"]["dag_deferred_count"] == 1
    assert result["info"]["fetched_text_verified"] is False
    assert result["info"]["scientific_validation"] is False
    assert "deferred/paywalled" in result["warnings"][0]
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize("key,value", [
    ("model", "Other"), ("model", None), ("note", []), ("count", True),
    ("count", 2), ("open_access", False), ("open_access", 0),
    ("papers", []), ("papers", {}), ("papers", [42]),
])
def test_envelope_schema_rejects_invalid_fields(package, key, value):
    edit(package, "docs/papers.json", lambda d: d.update({key: value}))
    assert not check(package)["ok"]


@pytest.mark.parametrize("key,value", [
    ("doi", None), ("doi", "10.1234/not a doi"), ("doi", 12),
    ("title", []), ("access", "oa_gold"), ("access", None),
    ("role", ["benchmark"]), ("serves", "water"), ("serves", [None]),
    ("serves", [""]), ("text_path", "/private/paper.txt"), ("status", "oa_manual"),
])
def test_paper_schema_rejects_invalid_or_authoring_fields(package, key, value):
    edit(package, "docs/papers.json", lambda d: d["papers"][0].update({key: value}))
    assert not check(package)["ok"]


def test_record_with_neither_doi_nor_title_is_not_bibliography(package):
    edit(package, "docs/papers.json", lambda d: d["papers"][0].update(doi="", title=""))
    assert not check(package)["ok"]


def test_optional_roles_and_quantities_are_not_a_closed_vocabulary(package):
    edit(package, "docs/papers.json", lambda d: d["papers"][0].pop("role"))
    edit(package, "docs/papers.json", lambda d: d["papers"][0].pop("serves"))
    assert check(package)["ok"]


def test_exporter_allows_blank_title_with_doi_as_unenriched_metadata(package):
    edit(package, "docs/papers.json", lambda d: d["papers"][0].update(title=""))
    result = check(package)
    assert result["ok"]
    assert any("blank published title" in item for item in result["warnings"])


def test_task_workflow_absent_literature_is_advisory(tmp_path):
    result = literature.check(tmp_path, model_name="Task", kind="task_workflow")
    assert result["ok"] and not result["present"] and result["count"] == 0
    assert "advisory" in result["warnings"][0]


def test_task_workflow_present_bibliography_does_not_require_scientific_documents(package):
    (package / "dag.yaml").unlink()
    (package / "docs/validation_convention.yaml").unlink()
    result = literature.check(package, model_name="Example", kind="task_workflow")
    assert result["ok"] and result["present"] and result["count"] == 1
    edit(package, "docs/papers.json", lambda d: d.update(model="Wrong"))
    assert not literature.check(package, model_name="Example", kind="task_workflow")["ok"]


def test_unsupported_kind_cannot_downgrade_a_process_model(package):
    assert not literature.check(package, model_name="Example", kind="unrecognised")["ok"]


@pytest.mark.parametrize("relative", ["dag.yaml", "docs/validation_convention.yaml"])
@pytest.mark.parametrize("value", ["DifferentModel", None, [], ""])
def test_other_document_model_identity_cannot_drift(package, relative, value):
    edit(package, relative, lambda d: (d["identity"] if relative == "dag.yaml" else d).update(model_id=value))
    assert any("model identity conflicts" in f for f in check(package)["failures"])


def test_catalogue_separator_and_plus_spellings_are_equivalent(package):
    edit(package, "docs/papers.json", lambda d: d.update(model="SWAT_Plus"))
    edit(package, "dag.yaml", lambda d: d["identity"].update(model_id="SWAT+"))
    edit(package, "docs/validation_convention.yaml", lambda d: d.update(model_id="SWAT+"))
    assert literature.check(package, model_name="SWAT_Plus")["ok"]


def test_normalized_doi_duplicate_is_rejected(package):
    def duplicate(d):
        d["papers"].append({**d["papers"][0], "doi": " HTTPS://DX.DOI.ORG/10.1234/example "})
        d.update(count=2, open_access=2)
    edit(package, "docs/papers.json", duplicate)
    assert any("duplicate normalized DOI" in f for f in check(package)["failures"])


@pytest.mark.parametrize("relative", ["docs/papers.json", "docs/validation_convention.yaml", "dag.yaml"])
def test_missing_or_invalid_documents_fail_closed(package, relative):
    (package / relative).unlink()
    assert not check(package)["ok"]
    (package / relative).write_bytes(b"\xff")
    assert not check(package)["ok"]
    (package / relative).write_text("[]", encoding="utf-8")
    assert not check(package)["ok"]


def test_duplicate_json_keys_do_not_select_a_convenient_identity(package):
    path = package / "docs/papers.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"model": "Example"',
                    '"model": "Other", "model": "Example"'), encoding="utf-8")
    assert any("duplicate JSON key" in f for f in check(package)["failures"])


def test_duplicate_yaml_keys_cannot_erase_reference_gaps(package):
    path = package / "docs/validation_convention.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\nreferences: {}\n", encoding="utf-8")
    assert any("duplicate YAML key" in f for f in check(package)["failures"])


@pytest.mark.parametrize("relative,mutation,expected", [
    ("docs/validation_convention.yaml", lambda d: d["references"]["model_paper"].update(doi="10.4567/Deferred"), "both deferred and a validation reference"),
    ("docs/validation_convention.yaml", lambda d: d["validation"][0].update(cites=["invented"]), "unknown citation key"),
    ("docs/validation_convention.yaml", lambda d: d["validation"][0].update(cites="model_paper"), "expected a list"),
    ("dag.yaml", lambda d: d["influence"]["edges"][0].update(citations=["invented"]), "unknown citation key"),
    ("dag.yaml", lambda d: d["influence"].update(citation_index=[]), "expected a mapping"),
])
def test_declared_citation_gaps_are_blocking(package, relative, mutation, expected):
    edit(package, relative, mutation)
    assert any(expected in f for f in check(package)["failures"])


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(deferred_paywalled={}),
    lambda d: d["deferred_paywalled"][0].update(needed_for=[]),
    lambda d: d["deferred_paywalled"][0].update(ref=""),
    lambda d: d["deferred_paywalled"][0].update(status="fetched"),
    lambda d: d["deferred_paywalled"][0].update(text_path="paper.txt"),
    lambda d: d["deferred_paywalled"].append(dict(d["deferred_paywalled"][0])),
    lambda d: d["deferred_paywalled"][0].update(doi="10.1234/example"),
])
def test_misrepresented_deferred_literature_is_blocking(package, mutation):
    edit(package, "docs/validation_convention.yaml", mutation)
    assert not check(package)["ok"]


def test_published_subscription_metadata_can_remain_deferred(package):
    def add(d):
        d["papers"].append({"doi": "10.4567/deferred", "title": "Unfetched study", "access": "subscription"})
        d["count"] = 2
    edit(package, "docs/papers.json", add)
    result = check(package)
    assert result["ok"] and result["info"]["dag_deferred_count"] == 1


def test_exporter_title_only_record_stays_metadata_not_fetched_evidence(package):
    from kiss_cli.papers import Library, Paper
    rows = [Paper.from_gathered({"title": "A technical manual without DOI"})]
    (package / "docs/papers.json").write_text(Library("Example", rows).dumps(), encoding="utf-8")
    result = check(package)
    assert result["ok"]
    assert result["info"]["published_without_doi"] == 1
    assert result["info"]["fetched_text_verified"] is False
    assert result["info"]["scientific_validation"] is False


def test_declared_reference_need_not_be_duplicated_in_exported_library(package):
    edit(package, "docs/validation_convention.yaml", lambda d:
         d["references"]["model_paper"].update(doi="10.1234/declared-separately"))
    edit(package, "dag.yaml", lambda d:
         d["influence"]["citation_index"]["available"].update(doi="10.1234/another-reference"))
    result = check(package)
    assert result["ok"]
    assert result["info"]["validation_references_outside_papers"] == 1
    assert result["info"]["dag_citations_outside_papers"] == 1
    assert any("not verified" in message for message in result["warnings"])


@pytest.mark.parametrize("value", [None, "unknown_not_fetched", "unknown_standard_not_fetched"])
def test_explicit_unidentified_deferred_targets_never_fill_a_citation_gap(package, value):
    edit(package, "docs/validation_convention.yaml", lambda d: d["deferred_paywalled"].append({
        "doi": value, "ref": "A spatial temperature validation study is still needed", "needed_for": ["temperature"]}))
    result = check(package)
    assert result["ok"] and result["info"]["deferred_without_doi"] == 1
    edit(package, "dag.yaml", lambda d: d["influence"]["citation_index"]["available"].update(doi="10.1234/missing"))
    result = check(package)
    assert result["ok"]
    assert any("absent from published papers" in f for f in result["warnings"])
    assert result["info"]["dag_citations_outside_papers"] == 1


@pytest.mark.parametrize("value", [None, "unknown_not_fetched", "not-a-doi"])
def test_validation_reference_doi_cannot_use_deferred_sentinels(package, value):
    edit(package, "docs/validation_convention.yaml", lambda d: d["references"]["model_paper"].update(doi=value))
    assert any("references.model_paper.doi: expected a DOI" in f for f in check(package)["failures"])


def test_doi_less_descriptive_bibliography_is_not_claimed_as_paper_evidence(package):
    def describe(d):
        d["influence"]["citation_index"]["available"] = {
            "short_citation": "Author thesis 2019", "note": "University dissertation, no DOI supplied."}
    edit(package, "dag.yaml", describe)
    result = check(package)
    assert result["ok"] and result["info"]["dag_bibliography_without_doi"] == 1
    assert any("not crosslinked paper evidence" in w for w in result["warnings"])
    edit(package, "dag.yaml", lambda d: d["influence"]["citation_index"]["available"].pop("note"))
    assert not check(package)["ok"]


def test_cyclic_yaml_is_bounded(package):
    (package / "dag.yaml").write_text("influence: {}\ncycle: &c {nested: *c}\n", encoding="utf-8")
    assert any("traversal limit" in f for f in check(package)["failures"])


def test_real_published_adcirc_has_six_validation_and_four_deferred_citations(tmp_path):
    source = Path("D:/GeoForge-Model-Tests-20261010/ki-updates/quarantine/f00153640bfd/models/ADCIRC")
    if not source.is_dir():
        pytest.skip("Read-only actual ADCIRC publication fixture is not available")
    relative_paths = ["docs/papers.json", "docs/validation_convention.yaml", "dag.yaml"]
    before = {rel: hashlib.sha256((source / rel).read_bytes()).hexdigest() for rel in relative_paths}
    for rel in relative_paths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)
    result = literature.check(tmp_path, model_name="ADCIRC")
    assert result["ok"], result["failures"]
    assert result["count"] == 20
    assert result["info"]["validation_reference_count"] == 6
    assert result["info"]["dag_deferred_count"] == 4
    assert before == {rel: hashlib.sha256((source / rel).read_bytes()).hexdigest() for rel in relative_paths}
