"""SHAW integration regressions anchored in the official 3.03 Trial outputs."""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
KI = ROOT / "models" / "SHAW"
TOOLS = KI / "s6_execution" / "tools"
FIXTURES = Path(__file__).parent / "fixtures" / "shaw_trial"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    parser = load("parse_shaw_output", TOOLS / "parse_shaw_output.py")
    monkeypatch.setitem(sys.modules, "parse_shaw_output", parser)
    return SimpleNamespace(
        parser=parser,
        runner=load("shaw_runner_test", TOOLS / "run_shaw.py"),
        frost=load("shaw_frost_test", TOOLS / "shaw_frost_analysis.py"),
        preflight=load("shaw_preflight_test", KI / "preflight_check.py"),
    )


def test_official_water_columns_and_hour24(modules):
    rows = modules.parser.parse_water_file(FIXTURES / "water.txt")
    assert rows[0]["datetime"] == "1986-12-05T00:00:00"
    assert rows[-1]["datetime"] == "1986-12-17T00:00:00"
    assert rows[0]["precip_mm"] == 0
    assert rows[0]["et_mm"] == .02
    assert rows[0]["drainage_mm"] == -2.69
    assert rows[0]["storage_change_mm"] == 2.67
    assert rows[1]["precip_mm"] == 9.1
    assert rows[1]["snowmelt_mm"] == 1.17
    assert rows[1]["intercepted_precip_mm"] == 2.42
    assert rows[1]["storage_change_mm"] == pytest.approx(15.69)
    assert "rain_mm" not in rows[1] and "snow_mm" not in rows[1]


def test_official_energy_and_frost_units(modules):
    first = modules.parser.parse_energy_file(FIXTURES / "energy.txt")[0]
    assert first["rnet_wm2"] == pytest.approx(92.7)
    assert (first["sensible_wm2"], first["latent_wm2"], first["ground_wm2"]) == (-71.5, -1.4, 11.5)
    last = modules.parser.parse_frost_file(FIXTURES / "frost.txt")[-1]
    assert (last["thaw_depth_cm"], last["frost_depth_cm"], last["snow_depth_cm"]) == (0, .1, 4.5)
    assert last["swe_mm"] == 9.2
    assert last["swe_cm"] == pytest.approx(.92)


def test_official_profiles_keep_all_nodes_and_normalize_end(modules):
    rows = modules.parser.parse_profile_file(FIXTURES / "temp.txt", "temp_C")
    assert rows[0]["datetime"] == "1986-12-04T12:00:00"
    assert rows[-1]["datetime"] == "1986-12-17T00:00:00"
    assert len([key for key in rows[-1] if key.startswith("temp_C_node")]) == 11
    assert rows[-1]["temp_C_node1"] == -.1
    assert rows[-1]["temp_C_node11"] == 8.4
    assert len(modules.parser.parse_profile_file(FIXTURES / "moist.txt")) == 3


def test_four_digit_year_and_leap_boundary(modules, tmp_path):
    source = tmp_path / "temp.out"
    source.write_text("366 24 2024 1.2D+00\n", encoding="utf-8")
    row = modules.parser.parse_profile_file(source)[0]
    assert row["year"] == 2024
    assert row["datetime"] == "2025-01-01T00:00:00"
    assert row["value_node1"] == 1.2


@pytest.mark.parametrize("line", ["338 24 86 1 2", "338 24 86 nan 0 0 0", "366 24 2023 0 0 0 0", "350 24"])
def test_invalid_scientific_rows_are_not_silently_dropped(modules, tmp_path, line):
    source = tmp_path / "frost.out"
    source.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frost.out:1"):
        modules.parser.parse_frost_file(source)


@pytest.mark.parametrize("text", ["338 12 86 1 2 3\n338 13 86 1\n", "DY HR YR 0.0 0.1 0.2\n338 12 86 1\n"])
def test_profile_rejects_missing_nodes(modules, tmp_path, text):
    source = tmp_path / "temp.out"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="nodes; expected 3"):
        modules.parser.parse_profile_file(source)


def test_frost_metrics_count_days_not_six_hour_samples(modules):
    rows = modules.frost.parse_frost_output(FIXTURES / "frost.txt")
    last = rows[-1]
    rows.append({**last, "hour": 18})
    metrics = modules.frost.compute_frost_metrics(rows)[0]
    assert metrics["frozen_days"] == 1
    assert metrics["snow_cover_days"] == 2
    assert metrics["max_swe_cm"] == .9


def test_plot_readers_share_correct_scientific_columns(modules):
    pytest.importorskip("matplotlib")
    plot = load("shaw_plot_test", TOOLS / "plot_shaw_profiles.py")
    times, water = plot.read_water_data(FIXTURES / "water.txt")
    assert times[-1].isoformat() == "1986-12-17T00:00:00"
    assert water["precip"][1] == 9.1 and water["snowmelt"][1] == 1.17
    assert plot.read_energy_data(FIXTURES / "energy.txt")[1]["rnet"][0] == pytest.approx(92.7)
    assert plot.read_frost_data(FIXTURES / "frost.txt")[1][-1] == .1


def setup_run(tmp_path):
    names = ["out.out", "temp.out"] + [f"unused{i}.out" for i in range(17)]
    control = tmp_path / "Trial.303.inp"
    control.write_text("Shaw 3.0\n0 1 0 0\nsite.sit\nweather.wea\ninit.moi\ninit.tem\n"
                       + "1 1 " + "0 " * 18 + "\n" + "\n".join(names)
                       + "\nTrailing PEST configuration retained\n", encoding="utf-8")
    (tmp_path / "site.sit").write_text("Trial period; two nodes for wrapper tests\n338 12 86 350 86\nsite\n0 0 0 2 0 .001 1\n", encoding="utf-8")
    return control


@pytest.mark.parametrize("returncode, fresh, complete, stdout, expected", [
    (0, True, True, "Run Complete", True),
    (0, False, True, "Run Complete", False),
    (0, True, False, "Run Complete", False),
    (2, True, True, "unrelated fatal failure", False),
    (2, False, True, "end of file", False),
    (2, True, True, "Run Complete; end of file", True),
    (24, True, True, "Run Complete; end-of-file during read, unit 5", True),
    (2, True, True, "end of file", False),
    (0xC0000005, True, True, "Run Complete; end of file", False),
    (-11, True, True, "Run Complete; end of file", False),
    (99, True, True, "Run Complete; end of file", False),
    (2, True, True, "Normal completion; Press Enter to end; end of file", True),
])
def test_run_requires_fresh_complete_result(modules, tmp_path, monkeypatch, returncode, fresh, complete, stdout, expected):
    control = setup_run(tmp_path)
    original = control.read_bytes()
    profile = tmp_path / "temp.out"
    profile.write_text("350 24 86 8.4\n", encoding="utf-8")
    def execute(command, **kwargs):
        assert kwargs["input"] == "Trial.303.inp\nY\n\n"
        assert kwargs["cwd"] == str(tmp_path)
        if fresh:
            start = datetime(1986, 12, 4, 12)
            rows = []
            for i in range(301 if complete else 300):
                stamp = start + timedelta(hours=i)
                rows.append(f"{stamp.timetuple().tm_yday} {stamp.hour} 86 0.1 8.4\n")
            profile.write_text("".join(rows), encoding="utf-8")
            (tmp_path / "out.out").write_text("Normal completion", encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    monkeypatch.setattr(modules.runner.subprocess, "run", execute)
    assert modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path) is expected
    assert control.read_bytes() == original


def test_terminal_row_alone_is_not_simulation_completion(modules, tmp_path, monkeypatch):
    control = setup_run(tmp_path)
    def execute(*args, **kwargs):
        assert kwargs["input"] == "Trial.303.inp\n\n"
        (tmp_path / "temp.out").write_text("350 24 86 0.1 8.4\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Run Complete", stderr="")
    monkeypatch.setattr(modules.runner.subprocess, "run", execute)
    assert not modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path)


@pytest.mark.parametrize("collision", ["site", "control", "hardlink", "escape", "log", "disabled_general"])
def test_rerun_cannot_overwrite_inputs_even_without_staging(modules, tmp_path, monkeypatch, collision):
    control = setup_run(tmp_path)
    site = tmp_path / "site.sit"
    if collision in ("site", "disabled_general"):
        control.write_text(control.read_text().replace("out.out", "site.sit"), encoding="utf-8")
        if collision == "disabled_general":
            control.write_text(control.read_text().replace("1 1 0", "0 1 0"), encoding="utf-8")
    elif collision == "control":
        control.write_text(control.read_text().replace("out.out", control.name), encoding="utf-8")
    elif collision == "hardlink":
        (tmp_path / "out.out").hardlink_to(site)
    elif collision == "log":
        (tmp_path / "shaw.stdout.log").hardlink_to(site)
    else:
        control.write_text(control.read_text().replace("out.out", "../outside.out"), encoding="utf-8")
    original = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    def must_not_launch(*args, **kwargs):
        pytest.fail("unsafe output must be rejected before native launch")
    monkeypatch.setattr(modules.runner.subprocess, "run", must_not_launch)
    assert not modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path)
    assert all(path.read_bytes() == data for path, data in original.items())


@pytest.mark.parametrize("implicit", ["ShawPEST.fof", "ShawMod.fof"])
def test_implicit_native_control_cannot_replace_selected_input(modules, tmp_path, monkeypatch, implicit):
    control = setup_run(tmp_path)
    (tmp_path / implicit).write_text("Other scientific settings", encoding="utf-8")
    def must_not_launch(*args, **kwargs):
        pytest.fail("implicit control must be rejected before native launch")
    monkeypatch.setattr(modules.runner.subprocess, "run", must_not_launch)
    assert not modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path)


def test_run_rejects_control_outside_workdir(modules, tmp_path, monkeypatch):
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    control = setup_run(elsewhere)
    setup_run(tmp_path)  # a different control with the same basename
    def must_not_launch(*args, **kwargs):
        pytest.fail("validated control must be the exact file read by native stdin")
    monkeypatch.setattr(modules.runner.subprocess, "run", must_not_launch)
    assert not modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path)


def test_coverage_respects_site_model_timestep(modules, tmp_path, monkeypatch):
    control = setup_run(tmp_path)
    site = tmp_path / "site.sit"
    site.write_text(site.read_text().replace("0 .001 1", "0 .001 3"), encoding="utf-8")
    def execute(*args, **kwargs):
        rows = []
        for i in range(101):
            stamp = datetime(1986, 12, 4, 12) + timedelta(hours=3 * i)
            rows.append(f"{stamp.timetuple().tm_yday} {stamp.hour} 86 0.1 8.4\n")
        (tmp_path / "temp.out").write_text("".join(rows), encoding="utf-8")
        (tmp_path / "out.out").write_text("Normal completion", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="Normal completion", stderr="")
    monkeypatch.setattr(modules.runner.subprocess, "run", execute)
    assert modules.runner.run_shaw(control, tmp_path / "shaw.exe", tmp_path)


def test_staging_preserves_all_input_bytes(modules, tmp_path):
    source, dest = tmp_path / "uploads", tmp_path / "outputs"
    source.mkdir()
    control = setup_run(source)
    for name in ("weather.wea", "init.moi", "init.tem"):
        (source / name).write_bytes(b"original scientific bytes\r\n")
    originals = {p.name: p.read_bytes() for p in source.iterdir()}
    modules.runner.stage_inputs(source, control.name, dest)
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == originals
    assert {p.name: p.read_bytes() for p in source.iterdir()} == originals


@pytest.mark.parametrize("change", ["../outside.wea", "D:/outside.wea", "sub/../../outside.wea"])
def test_staging_rejects_escaping_input_paths(modules, tmp_path, change):
    source = tmp_path / "uploads"
    source.mkdir()
    control = setup_run(source)
    control.write_text(control.read_text().replace("weather.wea", change), encoding="utf-8")
    with pytest.raises(ValueError, match="relative filename"):
        modules.runner.stage_inputs(source, control.name, tmp_path / "outputs")
    assert not (tmp_path / "outputs").exists()


def test_staging_cannot_overwrite_inputs_or_existing_different_files(modules, tmp_path):
    source, dest = tmp_path / "uploads", tmp_path / "outputs"
    source.mkdir()
    dest.mkdir()
    control = setup_run(source)
    with pytest.raises(ValueError, match="separate"):
        modules.runner.stage_inputs(source, control.name, source)
    (dest / control.name).write_text("other control", encoding="utf-8")
    with pytest.raises(ValueError, match="different existing file"):
        modules.runner.stage_inputs(source, control.name, dest)
    assert (dest / control.name).read_text() == "other control"


def test_windows_native_executable_beats_source_directory(modules, tmp_path, monkeypatch):
    (tmp_path / "shaw303").mkdir()
    native = tmp_path / "shaw303.exe"
    native.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "platform", "win32")
    assert modules.runner.resolve_executable(tmp_path / "shaw303") == native
    assert modules.preflight.native_binary(tmp_path / "shaw303") == native


def test_existing_control_still_requires_project_inputs(modules, tmp_path):
    control = setup_run(tmp_path)
    exe = tmp_path / "shaw.exe"
    exe.write_bytes(b"MZ")
    args = SimpleNamespace(inp_file=control.name, sit_file=None, wea_file=None,
                           moi_file=None, tem_file=None, shaw_exe=str(exe))
    assert not modules.runner.validate_inputs(args, tmp_path)


@pytest.mark.parametrize("missing_plotting", [False, True])
def test_software_preflight_does_not_require_trial_data(modules, tmp_path, monkeypatch, missing_plotting):
    preflight = modules.preflight
    binary = tmp_path / "shaw.exe"
    binary.write_bytes(b"MZ")
    binary.chmod(0o755)
    monkeypatch.setattr(preflight, "HYDROCRAFT_ROOT", tmp_path)
    monkeypatch.setattr(preflight, "SHAW_DIST_DIR", tmp_path / "missing-example")
    monkeypatch.setattr(preflight, "MANIFEST_BINARY", binary)
    monkeypatch.setattr(preflight, "TOOL_DEFAULT_BINARY", binary)
    monkeypatch.setattr(preflight, "PYTHON_ENV", Path(sys.executable))
    monkeypatch.setattr(preflight.subprocess, "run", lambda command, **k: SimpleNamespace(
        returncode=int(missing_plotting and command[-1] == "import matplotlib"),
        stdout="Simultaneous Heat And Water\nEnter the file", stderr=""))
    with pytest.raises(SystemExit) as exit_status:
        preflight.main()
    assert exit_status.value.code == int(missing_plotting)
    trial = [c for c in preflight.checks if "Trial." in c["subject"]]
    assert len(trial) == 5 and all(not c["critical"] and c["status"] == "fail" for c in trial)
    plotting = [c for c in preflight.checks if c["subject"].endswith(": import matplotlib")]
    assert len(plotting) == 1 and plotting[0]["critical"]
    assert plotting[0]["status"] == ("fail" if missing_plotting else "pass")


def test_preflight_rejects_loader_failure(modules, tmp_path, monkeypatch):
    binary = tmp_path / "shaw.exe"
    binary.write_bytes(b"MZ")
    binary.chmod(0o755)
    monkeypatch.setattr(modules.preflight.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0xC000007B, stdout="", stderr=""))
    assert not modules.preflight.check_binary_starts(binary, "SHAW")
    assert modules.preflight.checks[-1]["critical"]


@pytest.mark.parametrize("returncode, diagnostic, expected", [
    (2, "end of file", True), (24, "end-of-file", True),
    (0xC0000005, "end of file", False), (-11, "end of file", False),
    (99, "end of file", False), (2, "unrelated error", False),
])
def test_preflight_banner_cannot_hide_abnormal_exit(modules, tmp_path, monkeypatch, returncode, diagnostic, expected):
    binary = tmp_path / "shaw.exe"
    binary.write_bytes(b"MZ")
    binary.chmod(0o755)
    monkeypatch.setattr(modules.preflight.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=returncode, stdout="Simultaneous Heat And Water\nEnter the file", stderr=diagnostic))
    assert modules.preflight.check_binary_starts(binary, "SHAW") is expected


def test_preflight_interpreter_uses_configured_windows_venv():
    from kiss_cli.port import unsubstitute
    cfg = SimpleNamespace(python=Path("D:/project/venv/Scripts/python.exe"),
                          roles={"server_root": Path("D:/project"), "python_env": Path("D:/project/venv")})
    source, _, _ = unsubstitute((KI / "preflight_check.py").read_text(encoding="utf-8"), cfg)
    assert 'PYTHON_ENV = Path("D:/project/venv/Scripts/python.exe")' in source


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_binary_role_separates_shared_install_from_project(modules, tmp_path, monkeypatch, platform):
    project = tmp_path / "scenario"
    binary_dir = tmp_path / "shared-install" / "binaries" / "shaw"
    binary_dir.mkdir(parents=True)
    native = binary_dir / "shaw303.exe"
    native.write_bytes(b"MZ")
    legacy = project / "model" / "shaw" / "shaw303"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(modules.preflight, "HYDROCRAFT_ROOT", project)
    monkeypatch.setattr(modules.preflight, "BINARY_DIR", binary_dir)
    monkeypatch.setattr(modules.runner, "BINARY_DIR", binary_dir)
    monkeypatch.setattr(modules.runner, "SHAW_EXE", str(legacy))
    expected = native if platform == "win32" else legacy
    assert modules.preflight.installed_binary("shaw303") == expected
    assert Path(modules.runner.default_executable()) == expected
    if platform == "win32":
        # A canonical-only install needs no extra shaw.exe alias to pass startup.
        assert modules.preflight.installed_binary("shaw") == native
        native.unlink()
        assert modules.preflight.installed_binary("shaw303") == legacy
        assert Path(modules.runner.default_executable()) == legacy
        legacy.unlink()
        assert modules.preflight.installed_binary("shaw303") == native
        assert Path(modules.runner.default_executable()) == native


def test_materialized_binary_role_is_shared_not_project(tmp_path):
    from kiss_cli.port import unsubstitute
    shared = tmp_path / "installation" / "binaries"
    cfg = SimpleNamespace(python=Path("D:/venv/Scripts/python.exe"), roles={
        "server_root": tmp_path / "scenario", "python_env": Path("D:/venv"),
        "binaries": shared})
    for path in (KI / "preflight_check.py", TOOLS / "run_shaw.py"):
        source, _, _ = unsubstitute(path.read_text(encoding="utf-8"), cfg)
        assert f'BINARY_DIR = Path("{shared.as_posix()}") / "shaw"' in source
