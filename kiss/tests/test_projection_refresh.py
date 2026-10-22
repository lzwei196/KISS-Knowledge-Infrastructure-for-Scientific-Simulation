"""The host regenerates a repair draft's projected KI files from their sources."""
from __future__ import annotations

import shutil
import sys

import pytest
import yaml

from kiss_cli import ki_projection_refresh as refresh

# A stand-in for the pinned KDT engine's vocabulary: canonical field names and synonyms.
VOCABULARY = '''
_ALIAS = {"symptom": "symptom", "error": "symptom", "diagnosis": "diagnosis", "cause": "diagnosis",
          "remedy": "remedy", "fix": "remedy"}
def canonical_key(field):
    return _ALIAS.get(str(field).strip().lower())
'''
TRIPLETS = [
    {"id": "dt_001", "symptom": "Run stops at READ_HRLDINFO", "cause": "namelist missing: copy it",
     "fix": ["copy namelist.hrldas", "rerun"], "severity": "critical"},
    {"id": "dt_002", "error": "Could NOT find Hypre (missing: HYPRE_LIBRARIES)",
     "diagnosis": "HYPRE_ROOT limits the search", "remedy": "drop HYPRE_ROOT", "severity": "silent"},
]
BASELINE_MANIFEST = {
    "package": {"name": "Demo", "binary": {"path": "KISSPATH_BINARIES/demo/demo.exe", "type": "ELF"}},
    "validation": {"tier": "validated", "tier_justification": "measured: NSE=0.712",
                   "metrics": {"best_nse": 0.712}},
    "summary": {"total_tools": 1, "total_diagnostic_triplets": 2},
}
SHARED = ("candidate_overlay", "ki_vocabulary", "ki_projection_common")


def write_yaml(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


def make_ki(root):
    for folder in ("diagnostics", "docs", "tools/s1"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    write_yaml(root / "dag.yaml", {
        "identity": {"model_id": "Demo", "language": "fortran", "implementation": "demo 1.0"},
        "inputs": {"forcing": [{"name": "precip", "unit": "mm h-1"}],
                   "parameters": [{"var": "ksat", "unit": "m s-1"}]},
        "outputs": [{"name": "streamflow", "unit": "m3 s-1",
                     "observability": {"comparable_obs_shapes": ["daily gauge"]}},
                    {"name": "soil_moisture", "unit": "m3 m-3"}]})
    write_yaml(root / "diagnostics" / "triplets.yaml", TRIPLETS)
    (root / "tools" / "s1" / "run.py").write_text("print('run')\n", encoding="utf-8")
    # Non-ASCII text must read as UTF-8 on every host, including a GBK-locale Windows.
    (root / "docs" / "s1_run.md").write_text("# Stage 1 — 运行\n", encoding="utf-8")
    (root / "docs" / "format_spec.yaml").write_text("# baseline projection\nknown_issues: []\n",
                                                    encoding="utf-8")
    write_yaml(root / "knowledge_infrastructure.yaml", BASELINE_MANIFEST)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    root = tmp_path / "engine"
    root.mkdir()
    (root / "ki_vocabulary.py").write_text(VOCABULARY, encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(root))
    return root


@pytest.fixture
def draft(tmp_path, engine):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    make_ki(base)
    shutil.copytree(base, candidate)
    return base, candidate


def snapshot(root):
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_untouched_draft_is_left_alone(draft):
    base, candidate = draft
    before = snapshot(candidate)
    result = refresh.refresh(candidate, base)
    assert result["ran"] is True and result["regenerated"] == [] and result["errors"] == []
    assert snapshot(candidate) == before
    assert refresh.feedback(result) == []


def test_new_triplet_regenerates_both_projections_and_keeps_database_fields(draft):
    base, candidate = draft
    write_yaml(candidate / "diagnostics" / "triplets.yaml",
               TRIPLETS + [{"id": "dt_003", "symptom": "s", "diagnosis": "d", "remedy": "r"}])
    result = refresh.refresh(candidate, base)
    assert {item["file"] for item in result["regenerated"]} == {refresh.FORMAT_SPEC, refresh.MANIFEST}
    assert {item["reason"] for item in result["regenerated"]} == {"its sources changed"}
    text = (candidate / refresh.FORMAT_SPEC).read_text(encoding="utf-8")
    assert text.startswith("# format_spec.yaml — projected from dag.yaml")
    spec = yaml.safe_load(text)
    assert [issue["id"] for issue in spec["known_issues"]] == ["dt_001", "dt_002", "dt_003"]
    # Synonyms resolve through the KDT vocabulary; lists flatten the generator's way.
    assert spec["known_issues"][0]["diagnosis"] == "namelist missing: copy it"
    assert spec["known_issues"][0]["remedy"] == "copy namelist.hrldas; rerun"
    assert spec["known_issues"][1]["symptom"].startswith("Could NOT find Hypre")
    assert [row["name"] for row in spec["outputs"]["primary"]] == ["streamflow"]
    manifest = yaml.safe_load((candidate / refresh.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["summary"]["total_diagnostic_triplets"] == 3
    assert manifest["summary"]["total_tools"] == 1 and manifest["pipeline"]["stages"] == ["s1_run"]
    # The models database exists only on the authoring server: these stay as they were.
    assert manifest["validation"] == BASELINE_MANIFEST["validation"]
    assert manifest["package"]["binary"] == BASELINE_MANIFEST["package"]["binary"]
    entry = next(item for item in result["regenerated"] if item["file"] == refresh.MANIFEST)
    assert entry["carried_from_baseline"] == ["validation", "package.binary"]
    lines = refresh.feedback(result)
    assert any("regenerated docs/format_spec.yaml because its sources changed" in line for line in lines)
    assert "not docs/format_spec.yaml, knowledge_infrastructure.yaml or SKILL.md's generated tool index" in lines[-1]


def test_hand_broken_projection_is_regenerated(draft):
    base, candidate = draft
    (candidate / refresh.FORMAT_SPEC).write_text("known_issues:\n- id: x\n  symptom: a: b\n", encoding="utf-8")
    result = refresh.refresh(candidate, base)
    assert [(item["file"], item["reason"]) for item in result["regenerated"]] == [
        (refresh.FORMAT_SPEC, "it no longer parses")]
    assert yaml.safe_load((candidate / refresh.FORMAT_SPEC).read_text(encoding="utf-8"))["model"]["name"] == "Demo"


def test_hand_edited_manifest_is_reprojected(draft):
    base, candidate = draft
    write_yaml(candidate / refresh.MANIFEST, {**BASELINE_MANIFEST, "summary": {"total_tools": 99}})
    result = refresh.refresh(candidate, base)
    assert [(item["file"], item["reason"]) for item in result["regenerated"]] == [
        (refresh.MANIFEST, "it was edited by hand in this draft")]
    manifest = yaml.safe_load((candidate / refresh.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["summary"]["total_tools"] == 1


def test_broken_source_is_named_and_projection_is_untouched(draft):
    base, candidate = draft
    (candidate / "diagnostics" / "triplets.yaml").write_text(
        "- id: dt_9\n  symptom: CMake: Could NOT find Hypre (missing: x)\n", encoding="utf-8")
    before = (candidate / refresh.FORMAT_SPEC).read_bytes()
    result = refresh.refresh(candidate, base)
    assert result["regenerated"] == []
    assert result["errors"] and all("source diagnostics/triplets.yaml does not parse" in error["error"]
                                    and "line 2" in error["error"] for error in result["errors"])
    assert (candidate / refresh.FORMAT_SPEC).read_bytes() == before
    text = " ".join(refresh.feedback(result))
    assert "diagnostics/triplets.yaml" in text and "Fix the source file" in text


def test_missing_engine_changes_nothing(draft, monkeypatch, tmp_path):
    base, candidate = draft
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(tmp_path / "absent"))
    (candidate / refresh.FORMAT_SPEC).write_text("broken: [", encoding="utf-8")
    result = refresh.refresh(candidate, base)
    assert result["ran"] is False and "KDT engine" in result["reason"]
    assert (candidate / refresh.FORMAT_SPEC).read_text(encoding="utf-8") == "broken: ["
    assert "could not reproject" in " ".join(refresh.feedback(result))


def test_without_a_baseline_only_unreadable_projections_are_regenerated(draft):
    _, candidate = draft
    write_yaml(candidate / refresh.MANIFEST, {"summary": {"total_tools": 99}})
    assert refresh.refresh(candidate, None)["regenerated"] == []
    (candidate / refresh.FORMAT_SPEC).write_text("broken: [", encoding="utf-8")
    assert [item["file"] for item in refresh.refresh(candidate, None)["regenerated"]] == [refresh.FORMAT_SPEC]


def test_import_state_is_restored(draft):
    base, candidate = draft
    path_before, modules_before = list(sys.path), {name: sys.modules.get(name) for name in SHARED}
    (candidate / refresh.FORMAT_SPEC).write_text("broken: [", encoding="utf-8")
    refresh.refresh(candidate, base)
    assert sys.path == path_before
    assert {name: sys.modules.get(name) for name in SHARED} == modules_before


@pytest.mark.parametrize("doc, expected", [
    (None, ([], "empty")),
    ([{"id": 1}, "stray"], ([{"id": 1}], "ok")),
    ({"triplets": [{"id": 2}]}, ([{"id": 2}], "ok")),
    ({"diagnostic_triplets": [{"id": 3}]}, ([{"id": 3}], "ok")),
    ({}, ([], "empty")),
    ({"other": 1}, ([], "unreadable")),
    ("text", ([], "unreadable")),
])
def test_triplet_reader_accepts_the_documented_shapes(doc, expected):
    assert refresh.read_triplets(doc) == expected


def skill_with_index(tools):
    from kiss_cli import ki_maintenance_recipes as recipes
    rows = "".join(f"| `{path}` | `KISSPATH_PYTHON_ENV/bin/python {{KI}}/{path} --help` |\n" for path in tools)
    return ("# Demo\n\nIntro.\n\n" + recipes._INDEX_BEGIN + "\n" + recipes._INDEX_HEADER + rows +
            "\n*" + str(len(tools)) + recipes._INDEX_FOOTER + "\n" + recipes._INDEX_END + "\n\nBody stays.\n")


def test_a_new_tool_is_added_to_the_skill_tool_index(draft):
    base, candidate = draft
    for root in (base, candidate):
        (root / "SKILL.md").write_text(skill_with_index(["tools/s1/run.py"]), encoding="utf-8")
    (candidate / "tools" / "s1" / "check_paths.py").write_text("print('check')\n", encoding="utf-8")
    result = refresh.refresh(candidate, base)
    assert [item["file"] for item in result["regenerated"]][:1] == [refresh.SKILL_INDEX]
    text = (candidate / "SKILL.md").read_text(encoding="utf-8")
    assert "| `tools/s1/check_paths.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1/check_paths.py --help` |" in text
    assert "\n*2 public tools" in text and text.endswith("\n\nBody stays.\n")
    assert any("tool index" in line for line in refresh.feedback(result))


def test_a_current_tool_index_is_left_alone(draft):
    base, candidate = draft
    for root in (base, candidate):
        (root / "SKILL.md").write_text(skill_with_index(["tools/s1/run.py"]), encoding="utf-8")
    before = (candidate / "SKILL.md").read_bytes()
    result = refresh.refresh(candidate, base)
    assert result["regenerated"] == [] and (candidate / "SKILL.md").read_bytes() == before


def test_an_unrecognized_tool_index_is_reported_not_rewritten(draft):
    base, candidate = draft
    from kiss_cli import ki_maintenance_recipes as recipes
    broken = "# Demo\n" + recipes._INDEX_BEGIN + "\nhand-written list\n" + recipes._INDEX_END + "\n"
    (candidate / "SKILL.md").write_text(broken, encoding="utf-8")
    result = refresh.refresh(candidate, base)
    assert any(item["file"] == refresh.SKILL_INDEX for item in result["errors"])
    assert (candidate / "SKILL.md").read_text(encoding="utf-8") == broken
