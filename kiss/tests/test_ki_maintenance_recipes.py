"""Deterministic repairs preserve evidence and never run scientific software."""
import ast
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml

from kiss_cli import ki_maintenance_recipes as recipes, ki_verification


@pytest.fixture
def inventory(tmp_path):
    root = tmp_path / "base"
    (root / "tools").mkdir(parents=True)
    (root / "s1_stage/tools").mkdir(parents=True)
    (root / "tools/one.py").write_text("# public tool\n", encoding="utf-8")
    (root / "s1_stage/tools/two.py").write_text("# stage tool\n", encoding="utf-8")
    (root / "tools/__init__.py").write_text("", encoding="utf-8")
    (root / "knowledge_infrastructure.yaml").write_bytes(
        b"# preserve this comment\r\npackage:\r\n  name: Example\r\n"
        b"tools:\r\n  count: 2\r\n  files:\r\n  - s1_stage/tools/two.py\r\n  - tools/one.py\r\n"
        b"validation:\r\n  tier: validated\r\n  metrics:\r\n    best_nse: 0.9486\r\n"
        b"summary:\r\n  total_tools: 3 # stale inventory\r\n  generated: '2026-10-02'\r\n")
    return root


def test_summary_projection_preserves_every_other_byte(inventory):
    original = (inventory / "knowledge_infrastructure.yaml").read_bytes()
    result = recipes.recipe_changes(inventory, "Example")
    assert set(result) == {"tool_inventory"}
    assert result["tool_inventory"] == {
        "knowledge_infrastructure.yaml": original.replace(b"total_tools: 3", b"total_tools: 2")}
    assert (inventory / "knowledge_infrastructure.yaml").read_bytes() == original


def test_projection_repairs_canonical_inventory_both_layouts(inventory):
    path = inventory / "knowledge_infrastructure.yaml"
    original = path.read_bytes().replace(b"count: 2", b"count: 19").replace(b"  - tools/one.py\r\n", b"")
    path.write_bytes(original)
    result = recipes.expected_changes(inventory, "Example")
    projected = yaml.safe_load(result["knowledge_infrastructure.yaml"])
    assert projected["tools"] == {"count": 2, "files": ["s1_stage/tools/two.py", "tools/one.py"]}
    assert projected["summary"]["total_tools"] == 2
    assert projected["validation"] == yaml.safe_load(original)["validation"]
    assert b"# preserve this comment\r\n" in result["knowledge_infrastructure.yaml"]
    assert b"generated: '2026-10-02'\r\n" in result["knowledge_infrastructure.yaml"]


def test_apply_only_to_distinct_unchanged_draft(inventory, tmp_path):
    candidate = tmp_path / "draft"
    shutil.copytree(inventory, candidate)
    result = recipes.apply_recipe(candidate, source=inventory, recipe="tool_inventory", name="Example")
    assert result["changed_files"] == ["knowledge_infrastructure.yaml"]
    assert b"total_tools: 3" in (inventory / "knowledge_infrastructure.yaml").read_bytes()
    assert b"total_tools: 2" in (candidate / "knowledge_infrastructure.yaml").read_bytes()
    with pytest.raises(ValueError, match="draft changed"):
        recipes.apply_recipe(candidate, source=inventory, recipe="tool_inventory", name="Example")
    with pytest.raises(ValueError, match="separate draft"):
        recipes.apply_recipe(inventory, source=inventory, recipe="tool_inventory", name="Example")


def test_current_inventory_noop_and_unknown_recipe(inventory, tmp_path):
    path = inventory / "knowledge_infrastructure.yaml"
    path.write_bytes(path.read_bytes().replace(b"total_tools: 3", b"total_tools: 2"))
    assert recipes.expected_changes(inventory, "Example") == {}
    with pytest.raises(ValueError, match="no supported"):
        recipes.apply_recipe(tmp_path / "draft", source=inventory, recipe="unknown", name="Example")


@pytest.mark.parametrize("extra", ["tools: {count: 2, files: []}\n", "new_claim: &shared {metric: x}\nalias: *shared\n"])
def test_inventory_duplicate_or_aliased_yaml_rejected(inventory, extra):
    path = inventory / "knowledge_infrastructure.yaml"
    path.write_bytes(path.read_bytes() + extra.encode())
    with pytest.raises(ValueError, match="duplicate|aliases"):
        recipes.expected_changes(inventory, "Example")


def test_unreviewed_counter_is_rejected(inventory, monkeypatch, tmp_path):
    from kiss_cli import kdtstudio
    tools = tmp_path / "shared"
    tools.mkdir()
    (tools / "ki_projection_common.py").write_text(
        "_TOOL_EXCLUDE = ('__pycache__', '_rejected', '.kdt_')\n" + recipes._COUNTER.replace("return sorted(out)", "return []"),
        encoding="utf-8")
    monkeypatch.setattr(kdtstudio, "_projection_tools_root", lambda: tools)
    with pytest.raises(ValueError, match="counter changed"):
        recipes.expected_changes(inventory, "Example")


# Captured generated-section shape from DSSAT. Deliberately leave authored
# science and published/gathered bibliography prose around the count/index.
_DSSAT_SKILL = """> MANDATORY EXECUTION POLICY: use the real model.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| to run the pipeline stages | `tools/` (19 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| for claims and thresholds | `docs/gathered_papers.json` (27 papers) + `docs/papers_index.md` | preserved historical wording, no new fetched/read claim |
*Projected 2026-08-17 from the KI's actual contents — 10 components present.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/dssat_workdir_setup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/dssat_workdir_setup.py --help` |

*19 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

## Scientific validation
Retain criterion NSE >= 0.8, citation `author2020`, and 27 published papers.
Use 120 kg N/ha; do not change historical scores best_nse: 0.9486.
"""


@pytest.fixture
def dssat_index(tmp_path):
    root = tmp_path / "DSSAT"
    (root / "tools").mkdir(parents=True)
    for name in ("calib_run.py", "dssat_workdir_setup.py", "run_reference_case.py"):
        # Tools must never be imported/executed to index them.
        (root / "tools" / name).write_text("raise RuntimeError('not an index-time executable')\n", encoding="utf-8")
    (root / "SKILL.md").write_bytes(_DSSAT_SKILL.replace("\n", "\r\n").encode("utf-8"))
    (root / "knowledge_infrastructure.yaml").write_text(
        "package: {name: DSSAT}\ntools: {count: 19, files: [tools/calib_run.py, tools/dssat_workdir_setup.py]}\n"
        "validation: {best_nse: 0.9486}\nsummary: {total_tools: 19}\n", encoding="utf-8")
    return root


def test_dssat_index_adds_exact_missing_runner_and_preserves_evidence_bytes(dssat_index, tmp_path):
    original = (dssat_index / "SKILL.md").read_bytes()
    result = recipes.recipe_changes(dssat_index, "DSSAT")
    assert set(result) == {"tool_inventory"}
    assert set(result["tool_inventory"]) == {"knowledge_infrastructure.yaml", "SKILL.md"}
    expected = original.replace(b"(19 tools)", b"(3 tools)").replace(b"*19 public tools", b"*3 public tools")
    runner = b"| `tools/run_reference_case.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_reference_case.py --help` |\r\n"
    expected = expected.replace(b"\r\n*3 public tools", runner + b"\r\n*3 public tools")
    assert result["tool_inventory"]["SKILL.md"] == expected
    assert (dssat_index / "SKILL.md").read_bytes() == original
    candidate = tmp_path / "candidate"
    shutil.copytree(dssat_index, candidate)
    recipes.apply_recipe(candidate, source=dssat_index, recipe="tool_inventory", name="DSSAT")
    assert recipes.recipe_changes(candidate, "DSSAT") == {}


def test_tool_map_count_and_public_index_have_distinct_rules(dssat_index):
    for name in ("_helper.py", "__init__.py", "setup.py", "conftest.py"):
        (dssat_index / "tools" / name).write_text("", encoding="utf-8")
    (dssat_index / "tools/__pycache__").mkdir()
    (dssat_index / "tools/__pycache__/cached.py").write_text("", encoding="utf-8")
    (dssat_index / "s1_stage").mkdir()
    (dssat_index / "s1_stage/stage.py").write_text("", encoding="utf-8")
    changes = recipes.expected_changes(dssat_index, "DSSAT")
    manifest = yaml.safe_load(changes["knowledge_infrastructure.yaml"])
    assert manifest["tools"]["count"] == 7  # cross-layout, excludes __init__/cache
    skill = changes["SKILL.md"].decode("utf-8")
    assert "`tools/` (7 tools)" in skill  # direct tools, includes __init__/packaging
    assert "*4 public tools;" in skill  # excludes all private/packaging tools
    assert "`s1_stage/stage.py`" in skill
    assert "`tools/_helper.py`" not in skill
    assert "`tools/setup.py`" not in skill


@pytest.mark.parametrize("interpreter", ["C:/Model Files/中文/python3.EXE", "/opt/venv/bin/python", "python3"])
def test_preserve_existing_project_interpreter(dssat_index, interpreter):
    path = dssat_index / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(b"KISSPATH_PYTHON_ENV/bin/python", interpreter.encode("utf-8")))
    updated = recipes.expected_changes(dssat_index, "DSSAT")["SKILL.md"].decode("utf-8")
    assert f"`{interpreter} {{KI}}/tools/run_reference_case.py --help`" in updated
    assert "KISSPATH_PYTHON_ENV" not in updated


@pytest.mark.parametrize("label", ["KI-MAP", "KI-TOOL-INDEX"])
@pytest.mark.parametrize("fault", ["duplicate_begin", "duplicate_end", "no_begin", "no_end", "reversed"])
def test_malformed_marker_pairs_fail_closed(dssat_index, label, fault):
    path = dssat_index / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    begin = next(line for line in text.splitlines() if line.startswith(f"<!-- {label}:BEGIN"))
    end = f"<!-- {label}:END -->"
    if fault == "duplicate_begin": text += "\n" + begin
    elif fault == "duplicate_end": text += "\n" + end
    elif fault == "no_begin": text = text.replace(begin, "")
    elif fault == "no_end": text = text.replace(end, "")
    else: text = text.replace(begin, "PLACEHOLDER").replace(end, begin).replace("PLACEHOLDER", end)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        recipes.expected_changes(dssat_index, "DSSAT")


@pytest.mark.parametrize("before,after", [
    ("KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help", "python {KI}/tools/calib_run.py --run"),
    ("KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help", "python;evil {KI}/tools/calib_run.py --help"),
    ("KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help", "python {KI}/tools/other.py --help"),
    ("KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help", "python {KI}/tools/calib_run.py --help"),
    ("Every public tool in this KI, by exact path.", "Additional scientific claim. Every public tool in this KI, by exact path."),
])
def test_unknown_index_or_invocation_is_not_regenerated(dssat_index, before, after):
    path = dssat_index / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(before.encode(), after.encode()))
    with pytest.raises(ValueError, match="invocation|interpreter|recognized"):
        recipes.expected_changes(dssat_index, "DSSAT")


def test_markdown_unsafe_tool_name_is_not_projected(dssat_index):
    (dssat_index / "tools/unsafe`name.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="safely projected"):
        recipes.expected_changes(dssat_index, "DSSAT")


def test_changed_scientific_prose_cannot_be_overwritten_by_recipe(dssat_index, tmp_path):
    candidate = tmp_path / "candidate"
    shutil.copytree(dssat_index, candidate)
    path = candidate / "SKILL.md"
    path.write_bytes(path.read_bytes().replace(b"NSE >= 0.8", b"NSE >= -10"))
    with pytest.raises(ValueError, match="draft changed"):
        recipes.apply_recipe(candidate, source=dssat_index, recipe="tool_inventory", name="DSSAT")
    assert (candidate / "knowledge_infrastructure.yaml").read_bytes() == (dssat_index / "knowledge_infrastructure.yaml").read_bytes()


def test_zero_public_tools_remains_idempotent(dssat_index, tmp_path):
    for path in (dssat_index / "tools").glob("*.py"):
        path.unlink()
    (dssat_index / "tools/_helper.py").write_text("", encoding="utf-8")
    candidate = tmp_path / "candidate"
    shutil.copytree(dssat_index, candidate)
    recipes.apply_recipe(candidate, source=dssat_index, recipe="tool_inventory", name="DSSAT")
    assert b"*0 public tools;" in (candidate / "SKILL.md").read_bytes()
    assert recipes.recipe_changes(candidate, "DSSAT") == {}
    (candidate / "tools/new.py").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no existing interpreter"):
        recipes.recipe_changes(candidate, "DSSAT")


def test_reordered_nonoverlapping_sections_preserve_authored_prose(dssat_index):
    path = dssat_index / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    start, stop = text.index("<!-- KI-MAP:BEGIN"), text.index("<!-- KI-MAP:END -->") + len("<!-- KI-MAP:END -->")
    section = text[start:stop]
    reordered = text[:start] + text[stop:] + "\n" + section + "\n"
    path.write_bytes(reordered.encode("utf-8"))
    updated = recipes.expected_changes(dssat_index, "DSSAT")["SKILL.md"].decode("utf-8")
    assert updated.index("<!-- KI-TOOL-INDEX:END -->") < updated.index("<!-- KI-MAP:BEGIN")
    assert "NSE >= 0.8" in updated
    assert "`tools/` (3 tools)" in updated


def test_missing_index_is_not_authored_by_maintenance(dssat_index):
    path = dssat_index / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    start, stop = text.index("<!-- KI-TOOL-INDEX:BEGIN"), text.index("<!-- KI-TOOL-INDEX:END -->") + len("<!-- KI-TOOL-INDEX:END -->")
    path.write_text(text[:start] + text[stop:], encoding="utf-8")
    assert "SKILL.md" not in recipes.expected_changes(dssat_index, "DSSAT")


_OPTIONAL = '''
def report_project_data(path, label):
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print(f"INFO {label}: {n} items")
    else:
        print(f"INFO optional data absent: {label}")

def check_common_data():
    global PASS, FAIL
    for path in ("KISSPATH_OBS", "KISSPATH_FORCING", "KISSPATH_STATIC"):
        if os.path.isdir(path):
            PASS += 1
        else:
            print(f"WARN optional data absent: {path}")

# Legacy unused helpers do not become newly reachable through the adapter.
def check_binary_search(name, label):
    subprocess.run([name])

def main():
    global PASS, FAIL
    print("PREFLIGHT")
    check_file("C:/Model Files/测验/vic.exe", "Primary", executable=True)
    check_file("C:\\\\Model Files\\\\路由\\\\route.exe", "Routing", executable=True)
    report_project_data("KISSPATH_FORCING/region", "Forcing")
    check_common_data()
    ki_dir = os.path.dirname(os.path.abspath(__file__))
    triplets = os.path.join(ki_dir, "diagnostics", "triplets.yaml")
    if os.path.isfile(triplets):
        print("INFO diagnostics present")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        print("STATUS: FAILED")
        sys.exit(1)
    else:
        print("STATUS: PASSED")
        sys.exit(0)

if __name__ == "__main__":
    main()
'''


@pytest.fixture
def preflight(tmp_path, monkeypatch):
    base = tmp_path / "base"
    candidate = tmp_path / "candidate"
    base.mkdir()
    source = "import os\nimport sys\nimport shutil\nimport subprocess\n\nPASS = 0\nFAIL = 0\n\n" + recipes._CHECK_FILE + _OPTIONAL
    (base / "preflight_check.py").write_bytes(source.replace("\n", "\r\n").encode("utf-8"))
    shutil.copytree(base, candidate)
    monkeypatch.setattr(ki_verification, "_preflight_interpreter", lambda: sys.executable)
    return base, candidate


def test_reporting_preserves_original_function_asts_and_all_original_bytes(preflight):
    base, candidate = preflight
    original = (base / "preflight_check.py").read_bytes()
    changes = recipes.expected_changes(base, "Example")
    assert set(changes) == {"preflight_check.py"}
    updated = changes["preflight_check.py"]
    before = ast.parse(original)
    after = ast.parse(updated)
    original_functions = {n.name: ast.dump(n) for n in before.body if isinstance(n, ast.FunctionDef)}
    assert all(original_functions[n.name] == ast.dump(n) for n in after.body
               if isinstance(n, ast.FunctionDef) and n.name in original_functions)
    guard = b'if __name__ == "__main__":\r\n'
    old_prefix, suffix = original.split(guard)
    assert updated.startswith(old_prefix)
    assert updated.endswith(guard + suffix)
    assert (base / "preflight_check.py").read_bytes() == original


def test_reporting_real_counter_decisions_and_optional_data(preflight):
    base, candidate = preflight
    recipes.apply_recipe(candidate, source=base, recipe="preflight_reporting", name="Example中文")
    report = recipes.validate_preflight_behavior(base, candidate)
    assert report["ok"] is True
    assert report["model_execution"] == "not_run"
    assert len(report["fixtures"]) == 7
    assert all(row["ok"] and row["report_count"] == 1 for row in report["fixtures"])
    assert [row["returncode"] for row in report["fixtures"]] == [0, 0, 1, 1, 1, 1, None]
    assert report["fixtures"][-1]["error"] == "OSError: fixture access failure"
    assert recipes.expected_changes(candidate, "Example中文") == {}


def test_wrf_package_contract_combines_repairs_and_runs_reporting_fixtures(preflight):
    base, candidate = preflight
    # WRF-Hydro's shape: one required binary, optional project data, stale
    # manifest count plus missing PREFLIGHT_REPORT. Neither partial fix suffices.
    path = base / "preflight_check.py"
    text = path.read_text(encoding="utf-8")
    text = "\n".join(line for line in text.split("\n") if '"Routing", executable=True)' not in line)
    text = text.replace("C:/Model Files/测验/vic.exe", "KISSPATH_BINARIES/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro_NoahMP.exe")
    path.write_text(text, encoding="utf-8")
    (base / "tools").mkdir()
    (base / "tools/run_model.py").write_text("raise RuntimeError('never run')\n", encoding="utf-8")
    (base / "knowledge_infrastructure.yaml").write_text(
        "tools: {count: 1, files: [tools/run_model.py]}\nsummary: {total_tools: 17}\n"
        "validation: {reference_version: 5.2.0, best_nse: 0.9486}\n", encoding="utf-8")
    shutil.rmtree(candidate)
    shutil.copytree(base, candidate)
    changes = recipes.recipe_changes(base, "WRF_Hydro")
    assert set(changes) == {"tool_inventory", "preflight_reporting", "package_contract"}
    assert changes["package_contract"] == {**changes["tool_inventory"], **changes["preflight_reporting"]}
    result = recipes.apply_recipe(candidate, source=base, recipe="package_contract", name="WRF_Hydro")
    assert result["changed_files"] == ["knowledge_infrastructure.yaml", "preflight_check.py"]
    assert recipes.validate_preflight_behavior(base, candidate)["ok"] is True
    assert len(recipes.validate_preflight_behavior(base, candidate)["fixtures"]) == 5
    assert recipes.recipe_changes(candidate, "WRF_Hydro") == {}


@pytest.mark.parametrize("before,after", [
    ("FAIL += 1", "PASS += 1"),
    ('check_common_data()\n    ki_dir', 'subprocess.run(["model"])\n    ki_dir'),
    ('check_common_data()\n    ki_dir', 'check_binary_search("model", "Model")\n    ki_dir'),
    ('PASS = 0', 'PASS = sum([0])'),
    ('import subprocess', 'import subprocess\nsubprocess.run(["model"])'),
    ('executable=True)', 'executable=False)'),
    ('def main():', '@print\ndef main():'),
    ('def check_binary_search(name, label):', 'def check_binary_search(name, label, *, x=open("untrusted", "w").write("x")):'),
    ('def check_binary_search(name, label):', 'def check_binary_search(name, /, label: open("untrusted", "w")):'),
    ('def check_binary_search(name, label):', 'def check_binary_search(*args: open("untrusted", "w")):'),
    ('def check_binary_search(name, label):', 'def check_binary_search(**args: open("untrusted", "w")):'),
    ('def check_binary_search(name, label):', 'def check_binary_search(*, label: open("untrusted", "w")):'),
    ('    print("PREFLIGHT")', '    print = __builtins__["open"]\n    print("untrusted", "w")'),
    ('    print("PREFLIGHT")', '    print = os.path.isfile\n    print("untrusted")'),
    ('    print("PREFLIGHT")', '    print(os.__dict__)'),
])
def test_unknown_or_executable_layout_gets_no_reporting_recipe(preflight, before, after):
    base, _ = preflight
    path = base / "preflight_check.py"
    path.write_text(path.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
    assert "preflight_reporting" not in recipes.recipe_changes(base, "Example")


def test_candidate_arbitrary_change_is_never_executed(preflight):
    base, candidate = preflight
    recipes.apply_recipe(candidate, source=base, recipe="preflight_reporting", name="Example")
    path = candidate / "preflight_check.py"
    path.write_bytes(path.read_bytes() + b'\nraise RuntimeError("untrusted")\n')
    with pytest.raises(ValueError, match="exact deterministic"):
        recipes.validate_preflight_behavior(base, candidate)


def test_bad_report_does_not_count_as_behavioral_success(preflight, monkeypatch):
    base, candidate = preflight
    recipes.apply_recipe(candidate, source=base, recipe="preflight_reporting", name="Example")
    from types import SimpleNamespace
    monkeypatch.setattr(recipes.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps({"ok": False})))
    with pytest.raises(ValueError, match="failed its reporting"):
        recipes.validate_preflight_behavior(base, candidate)
