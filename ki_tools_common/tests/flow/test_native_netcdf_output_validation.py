"""Real tiny data containers and diagnostic negatives; no scientific engine."""
import json
import sys

import netCDF4
import numpy as np
import pytest

from ki_tools_common.flow import receipts, declared_outputs


FACTS = {"errored": False, "output_nonempty": True}


@pytest.fixture
def ki(tmp_path):
    root = tmp_path / "ki"
    root.mkdir()
    (root / "dag.yaml").write_text(
        "outputs:\n- var: streamflow\n  validation_rank: 1\n  unit: m3/s\n", encoding="utf-8")
    return root


def container(path, *, format="NETCDF4", variable="streamflow", values=(0.4, 1.1, 0.7)):
    with netCDF4.Dataset(path, "w", format=format) as ds:
        ds.createDimension("feature_id", len(values))
        ds.createDimension("time", 1)
        ids = ds.createVariable("feature_id", "i4", ("feature_id",))
        ids[:] = np.arange(len(values)) + 100
        t = ds.createVariable("time", "i4", ("time",))
        t.units = "minutes since 1970-01-01 00:00:00 UTC"
        t[:] = [21905280]
        v = ds.createVariable(variable, "f8", ("feature_id",))
        v.units = "m3 s-1"
        v[:] = values
    return path


@pytest.mark.parametrize("format", ["NETCDF3_CLASSIC", "NETCDF3_64BIT_OFFSET", "NETCDF3_64BIT_DATA", "NETCDF4"])
@pytest.mark.parametrize("name", ["201108260000.CHANOBS_DOMAIN1", "native-output", "result.bin"])
def test_actual_container_without_netcdf_extension_is_decoded(ki, tmp_path, format, name):
    path = container(tmp_path / name, format=format)
    values, steps, note = receipts._load_series(path, ("streamflow",))
    assert values == [0.4, 1.1, 0.7]
    assert "netcdf rank-1 var(s) streamflow" == note
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS)["status"] == "passed"


def test_native_extension_uses_netcdf4_when_xarray_is_unavailable(ki, tmp_path, monkeypatch):
    path = container(tmp_path / "201108260000.CHANOBS_DOMAIN1")
    monkeypatch.setitem(sys.modules, "xarray", None)
    values, steps, note = receipts._load_series(path, ("streamflow",))
    assert values == [0.4, 1.1, 0.7]
    assert note == "netcdf rank-1 var(s) streamflow"
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS)["status"] == "passed"


@pytest.mark.parametrize("name,data", [
    ("pretend.nc", b"time,streamflow\n1,2\n2,4\n3,1\n"),
    ("pretend.nc4", b"1 2 3 4\n"),
    ("empty.CHANOBS_DOMAIN1", b""),
    ("truncated.CHANOBS_DOMAIN1", b"CDF\x01\x00\x00\x00\x00\n1 2 3 4\n"),
    ("truncated.HDF", b"\x89HDF\r\n\x1a\n1 2 3 4\n"),
    ("binary.dat", b"\x00header\n1 2\n3 4\n"),
    ("invalid-utf8.dat", b"\xff1 2\n3 4\n"),
])
def test_spoofed_empty_and_truncated_files_cannot_pass(ki, tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    result = receipts.validate_outputs(ki, [path], run_facts=FACTS)
    assert result["status"] != "passed"
    if name.endswith((".nc", ".nc4")) or data.startswith((b"CDF", b"\x89HDF")):
        assert result["status"] == "failed"
        assert any("NETCDF_UNINSPECTABLE" in c["detail"] for c in result["checks"])


@pytest.mark.parametrize("variable,values", [
    ("streamflow", (0, 0, 0)),
    ("streamflow", (0.4, float("nan"), 0.7)),
    ("streamflow", (0.4, float("inf"), 0.7)),
    ("unrelated_positive", (1, 2, 3)),
])
def test_magic_never_bypasses_scientific_checks(ki, tmp_path, variable, values):
    path = container(tmp_path / "201108260000.CHANOBS_DOMAIN1", variable=variable, values=values)
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS)["status"] == "failed"


def test_existing_preparation_constant_policy_is_unchanged(ki, tmp_path):
    path = container(tmp_path / "constant-mask.native", values=(0, 0, 0))
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS, physical=False)["status"] == "passed"


@pytest.mark.parametrize("name", [
    "diag_hydro.00000", "diag_solver.1", "diagnostic.002", "diagnostics.txt",
    "solver.log", "solver.log.2", "stdout", "stderr.txt", "rank-1.stderr", "solver_logs.txt",
])
def test_generic_diagnostic_numbers_cannot_be_the_model_result(ki, tmp_path, name):
    path = tmp_path / name
    path.write_text("time,streamflow\n1,0.4\n2,1.1\n3,0.7\n", encoding="utf-8")
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS)["status"] != "passed"
    good = container(tmp_path / "real.CHANOBS_DOMAIN1")
    result = receipts.validate_outputs(ki, [path, good], run_facts=FACTS)
    assert result["status"] == "passed"
    assert any(c["check"] == "diagnostic_log:" + name for c in result["checks"])
    assert not any(c["check"] == "no_nan_inf:" + name for c in result["checks"])


@pytest.mark.parametrize("name", ["catalog.csv", "dialog.dat", "result.stderr.log.csv", "streamflow.tsv"])
def test_structured_result_names_are_not_mistaken_for_diagnostics(ki, tmp_path, name):
    path = tmp_path / name
    path.write_text("time,streamflow\n1,0.4\n2,1.1\n3,0.7\n", encoding="utf-8")
    assert receipts.validate_outputs(ki, [path], run_facts=FACTS)["status"] == "passed"


def test_declared_physical_logs_do_not_create_a_successful_result_contract(ki, tmp_path):
    project = tmp_path / "project"
    (project / "outputs").mkdir(parents=True)
    outputs = [project / "outputs" / name for name in ("diag_hydro.00000", "diag_hydro.00001")]
    for path in outputs:
        path.write_text("time,streamflow\n1,0.4\n2,1.1\n3,0.7\n", encoding="utf-8")
    step = {"id": "native", "kind": "model_run", "ki": "M", "tool": "run.py", "outputs": ["logs"]}
    inv = {"items": [{"id": "logs", "local_paths": [p.relative_to(project).as_posix() for p in outputs]}]}
    validation, binding = declared_outputs.validate(project, ki, step, inv, outputs,
        run_facts={"errored": False}, physical=True)
    assert binding is not None and validation["status"] != "passed"
    assert not any(c["check"].startswith("no_nan_inf") for c in validation["checks"])


def test_native_result_and_diagnostic_artifacts_keep_signed_byte_evidence(ki, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    output = container(project / "201108260000.CHANOBS_DOMAIN1")
    diagnostic = project / "diag_solver.00000"
    diagnostic.write_text("timing 1 2 3\n", encoding="utf-8")
    validation = receipts.validate_outputs(ki, [output, diagnostic], run_facts=FACTS)
    path = receipts.record_run(project, ki="M", executable=sys.executable,
        command=[sys.executable, "fixture.py"], cwd=str(project), started_at=1, finished_at=2,
        exit_code=0, inputs=[], outputs=[output, diagnostic], plan_step_id="M:run",
        approval_sha256="synthetic-approval", validation=validation)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert receipts.verify(project, doc) and doc["validation"]["status"] == "passed"
    entry = next(row for row in doc["outputs"] if row["path"] == diagnostic.name)
    assert receipts._entry_status(project, entry) == "intact"
    diagnostic.write_text("different diagnostics", encoding="utf-8")
    assert receipts._entry_status(project, entry) == "changed"
