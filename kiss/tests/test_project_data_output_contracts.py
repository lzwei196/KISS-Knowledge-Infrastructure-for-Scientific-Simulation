"""Real guarded data-worker evidence for opt-in formats; no model execution."""
import copy
import json
import os
from pathlib import Path

import pytest

from kiss_cli import flowgate, harness_runtime, project_data_tools
from .test_project_data_tools import case, approve, run
from .test_project_data_formats import WEATHER, AGRO, WEATHER_CONTRACT, AGRO_CONTRACT


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "signing-keys"))


COPY_SOURCE = '''from pathlib import Path
import json
out = Path('outputs'); out.mkdir(parents=True, exist_ok=True)
for source, destination in [('weather.txt','weather.csv'), ('agro.txt','agro.yaml'), ('soil.dat','soil.soil')]:
    (out / destination).write_bytes((Path('inputs') / source).read_bytes())
(out / 'report.json').write_text(json.dumps({'copied':3, 'scientific_validation':'not_performed'}))
'''


def typed_case(tmp_path, *, source=COPY_SOURCE, version=2, weather=WEATHER, agro=AGRO):
    c = list(case(tmp_path, source))
    _, project, _, plan, inv, _ = c
    for name, value in (("weather.txt", weather), ("agro.txt", agro), ("soil.dat", "SOLNAM='soil'\nSMW=0.10\n")):
        (project / "inputs" / name).write_text(value, encoding="utf-8")
    inv["items"][0]["local_paths"] = [str(p) for p in (project / "inputs").iterdir()]
    contracts = copy.deepcopy([WEATHER_CONTRACT, AGRO_CONTRACT])
    authored = project_data_tools.write(project, "M", "reader", source, "converter",
        **({"output_formats": contracts} if version == 2 else {}))
    plan["steps"][0].update(kind="prepare", project_data_tool=authored["project_data_tool"],
                            outputs=["weather", "agro", "soil", "report"])
    c[-1] = authored
    return tuple(c)


def execute(c):
    approve(c)
    result = run(c)
    summary = json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    path = Path(summary["receipt"])
    return result, path, json.loads(path.read_text())


def evidence(c):
    return c[2].flow.receipts.evidence(c[1], c[3], c[2].flow.approval.read(c[1]),
                                     enforcement="exact", inventory=c[4])


def test_real_worker_v2_validates_both_formats_and_keeps_v1_extra_output_checks(tmp_path):
    c = typed_case(tmp_path)
    originals = {p.name: p.read_bytes() for p in (c[1] / "inputs").iterdir()}
    result, receipt_path, receipt = execute(c)
    assert result.startswith("exit_code=0"), result
    assert receipt["validation"]["status"] == "passed", receipt["validation"]
    assert receipt["execution_scope"] == "project_data_tool" and receipt["model_executed"] is False
    assert receipt["validation"]["scientific_validation"] == "not_performed"
    assert receipt["validation"]["model_ready"] is False
    typed = receipt["validation"]["typed_outputs"]
    assert typed["contracts"] == c[3]["steps"][0]["project_data_tool"]["output_formats"]
    assert [report["output_id"] for report in typed["outputs"]] == ["weather", "agro"]
    assert all(report["ok"] and not report["model_ready"] for report in typed["outputs"])
    checks = receipt["validation"]["checks"]
    assert any(row.get("scope") == "unchanged_input_copy" and row["source"] == "inputs/soil.dat" for row in checks)
    assert any(row["check"] == "data_artifact_structure:report.json" and row["ok"] for row in checks)
    assert {p.name: p.read_bytes() for p in (c[1] / "inputs").iterdir()} == originals
    assert (c[1] / "outputs/weather.csv").read_bytes() == originals["weather.txt"]
    assert (c[1] / "outputs/agro.yaml").read_bytes() == originals["agro.txt"]
    before = receipt_path.read_bytes()
    proof = evidence(c)
    assert proof["steps_passed"] == ["M:read"], proof
    assert receipt_path.read_bytes() == before


def test_v1_does_not_implicitly_detect_pcse_preamble(tmp_path):
    c = typed_case(tmp_path, version=1)
    _, _, receipt = execute(c)
    assert receipt["validation"]["status"] == "failed"
    assert "typed_outputs" not in receipt["validation"]
    assert evidence(c)["steps_passed"] == []


@pytest.mark.parametrize("weather,agro", [
    ("a,b\n1,2\n", AGRO),
    (WEATHER.replace("19800229", "19800230"), AGRO),
    (WEATHER, AGRO.replace("1980-06-01", "1981-06-01")),
    (WEATHER, "[1, 2, 3]\n"),
])
def test_explicit_format_rejection_never_falls_back_to_csv_or_exact_copy(tmp_path, weather, agro):
    c = typed_case(tmp_path, weather=weather, agro=agro)
    _, _, receipt = execute(c)
    assert receipt["exit_code"] == 0
    assert receipt["validation"]["status"] == "failed"
    assert evidence(c)["steps_passed"] == []


@pytest.mark.parametrize("changes", [
    {"format": "unknown"}, {"format": []}, {"extra": 1}, {"output_id": "x" * 129},
    {"path": "outputs/../weather.csv"}, {"path": "C:/weather.csv"},
    {"path": "outputs/${weather}.csv"}, {"path": "outputs/$weather.csv"},
    {"path": "outputs/weather\n.csv"}, {"path": "outputs/w:ther.csv"},
    {"path": "outputs/weather.txt"}, {"path": "outputs/" + "a" * 1020 + ".csv"},
    {"date_format": "%Y-%m-%d"}, {"date_format": None},
])
def test_invalid_typed_contract_rejected_before_authoring(tmp_path, changes):
    flowgate.load()
    contract = {**WEATHER_CONTRACT, **changes}
    with pytest.raises((ValueError, TypeError)):
        project_data_tools.write(tmp_path, "M", "reader", "pass", "converter", output_formats=[contract])
    assert not (tmp_path / "project_tools").exists()


@pytest.mark.parametrize("defect", ["duplicate_id", "duplicate_path", "missing_id", "unknown_field"])
def test_plan_rejects_unbound_or_duplicate_format_contracts(tmp_path, defect):
    c = typed_case(tmp_path)
    step = c[3]["steps"][0]
    contracts = step["project_data_tool"]["output_formats"]
    if defect == "duplicate_id":
        contracts.append({**WEATHER_CONTRACT, "path": "outputs/second.csv"})
    elif defect == "duplicate_path":
        contracts.append({**WEATHER_CONTRACT, "output_id": "report"})
    elif defect == "missing_id":
        contracts[0]["output_id"] = "absent"
    else:
        contracts[0]["dateformat"] = "%Y%m%d"
    assert c[2].write_plan(c[3], c[4])


def test_declared_output_must_be_freshly_captured_even_if_old_file_exists(tmp_path):
    c = typed_case(tmp_path)
    out = c[1] / "outputs"
    out.mkdir()
    (out / "weather.csv").write_text(WEATHER)
    (out / "agro.yaml").write_text(AGRO)
    result = project_data_tools.validate_outputs(c[1], [out / "agro.yaml"], 0, step=c[3]["steps"][0])
    assert result["status"] == "failed"
    assert any("freshly captured" in row.get("detail", "") for row in result["checks"])


@pytest.mark.parametrize("defect", ["file_changed", "file_missing", "format_policy", "validator_digest", "binding_policy"])
def test_completion_rechecks_current_typed_file_and_policy(tmp_path, monkeypatch, defect):
    c = typed_case(tmp_path)
    _, path, _ = execute(c)
    assert evidence(c)["steps_passed"] == ["M:read"]
    original_receipt = path.read_bytes()
    from ki_tools_common.flow import project_data_formats, project_tools
    if defect == "file_changed":
        (c[1] / "outputs/weather.csv").write_text(WEATHER.replace("2538.000", "2539.000"))
    elif defect == "file_missing":
        (c[1] / "outputs/agro.yaml").unlink()
    elif defect == "format_policy":
        monkeypatch.setattr(project_data_formats, "POLICY", "changed-policy")
    elif defect == "validator_digest":
        monkeypatch.setattr(project_data_formats, "source_digest", lambda: "0" * 64)
    else:
        monkeypatch.setattr(project_tools, "OUTPUT_POLICY", "changed-policy")
    result = evidence(c)
    assert result["steps_passed"] == []
    assert result["runs"][0]["validation"] == "failed"
    assert result["runs"][0]["validation_reason"]
    assert path.read_bytes() == original_receipt


@pytest.mark.parametrize("defect", ["binding", "missing_reports", "missing_format", "wrong_hash", "wrong_bytes", "scope", "model_ready", "validation_none"])
def test_authentic_but_incomplete_typed_receipts_do_not_satisfy_completion(tmp_path, defect):
    c = typed_case(tmp_path)
    _, path, receipt = execute(c)
    if defect == "binding":
        receipt["project_data_tool"]["output_formats"][0]["date_format"] = "%Y-%m-%d"
    elif defect == "missing_reports":
        del receipt["validation"]["typed_outputs"]
    elif defect == "missing_format":
        receipt["validation"]["typed_outputs"]["outputs"].pop()
    elif defect == "wrong_hash":
        receipt["validation"]["typed_outputs"]["outputs"][0]["sha256"] = "0" * 64
    elif defect == "wrong_bytes":
        receipt["outputs"][0]["bytes"] += 1
    elif defect == "scope":
        receipt["execution_scope"] = "ki_tool"
    elif defect == "model_ready":
        receipt["validation"]["model_ready"] = True
    else:
        receipt["validation"] = None
    path.write_text(json.dumps(c[2].flow.receipts.sign(c[1], receipt)), encoding="utf-8")
    result = evidence(c)
    assert result["steps_passed"] == [], result
    assert result["runs"][0]["validation"] == "failed", result


def test_later_authentic_invalid_v2_attempt_does_not_resurrect_earlier_pass(tmp_path):
    c = typed_case(tmp_path)
    _, path, receipt = execute(c)
    later = copy.deepcopy(receipt)
    later["run_id"] += "-later"
    later["finished_at"] = "2099-01-01T00:00:00+00:00"
    del later["validation"]["typed_outputs"]
    path.with_name("later.json").write_text(json.dumps(c[2].flow.receipts.sign(c[1], later)), encoding="utf-8")
    result = evidence(c)
    assert result["steps_passed"] == []
    assert any(row["validation"] == "failed" for row in result["runs"])


def test_later_real_failed_retry_supersedes_previous_pass(tmp_path):
    c = typed_case(tmp_path)
    execute(c)
    assert evidence(c)["steps_passed"] == ["M:read"]
    result = run(c)
    assert result.startswith("exit_code=1"), result  # Existing artifacts cannot be overwritten.
    assert evidence(c)["steps_passed"] == []


def test_output_alias_introduced_after_run_invalidates_evidence(tmp_path):
    c = typed_case(tmp_path)
    execute(c)
    target = c[1] / "outputs/weather.csv"
    target.unlink()
    os.link(c[1] / "inputs/weather.txt", target)
    assert evidence(c)["steps_passed"] == []


def test_enlarged_artifact_rejected_before_opening_replacement(tmp_path, monkeypatch):
    c = typed_case(tmp_path)
    _, _, receipt = execute(c)
    target = c[1] / "outputs/weather.csv"
    target.write_text(WEATHER + "replacement grew\n")
    original_open = Path.open
    def opening(path, *args, **kwargs):
        assert path != target, "size drift must reject before reading the replacement"
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", opening)
    from ki_tools_common.flow import project_tools
    assert project_tools.typed_output_errors(c[1], c[3]["steps"][0], receipt["validation"], receipt["outputs"])


def test_full_approved_step_binding_is_checked_not_only_contract(tmp_path):
    c = typed_case(tmp_path)
    _, _, receipt = execute(c)
    from ki_tools_common.flow import project_tools
    changed = copy.deepcopy(c[3]["steps"][0])
    changed["outputs"].append("another-output")
    assert project_tools.typed_output_errors(c[1], changed, receipt["validation"], receipt["outputs"])


def test_contract_path_aliases_cannot_write_or_validate_outside_project(tmp_path):
    c = typed_case(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (c[1] / "outputs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create symbolic links")
    assert c[2].write_plan(c[3], c[4])
    assert not list(outside.iterdir())


def test_output_hardlink_is_rejected(tmp_path):
    c = typed_case(tmp_path)
    (c[1] / "outputs").mkdir()
    os.link(c[1] / "inputs/weather.txt", c[1] / "outputs/weather.csv")
    assert c[2].write_plan(c[3], c[4])


def test_host_format_module_comes_from_bundled_flow_not_pinned_ki_helper(tmp_path, monkeypatch):
    from . import test_project_data_tools as adapters
    stale = tmp_path / "old-model-helper" / "ki_tools_common" / "flow"
    stale.mkdir(parents=True)
    (stale / "project_tools.py").write_text("# Old immutable model helper, deliberately no format module\n")
    old = (stale / "project_tools.py").read_bytes()
    original_cfg = adapters._cfg
    def configured(project):
        cfg = original_cfg(project)
        cfg.roles["ki_tools_common"] = stale.parent
        return cfg
    monkeypatch.setattr(adapters, "_cfg", configured)
    c = typed_case(tmp_path)
    _, _, receipt = execute(c)
    assert receipt["validation"]["status"] == "passed"
    assert evidence(c)["steps_passed"] == ["M:read"]
    flowgate.load()
    from ki_tools_common.flow import project_data_formats
    assert Path(project_data_formats.__file__).resolve().is_relative_to(harness_runtime.bundled_source_root().resolve())
    assert (stale / "project_tools.py").read_bytes() == old
    assert not (stale / "project_data_formats.py").exists()


def test_format_module_is_required_by_bundled_startup_check(monkeypatch):
    original = flowgate.importlib.import_module
    def importing(name):
        if name == "ki_tools_common.flow.project_data_formats":
            raise ImportError("format module missing")
        return original(name)
    monkeypatch.setattr(flowgate.importlib, "import_module", importing)
    with pytest.raises(flowgate.FlowUnavailable, match="format module missing"):
        flowgate.load()
