"""Calibration and verifier runs read a projected KI in place and write only outside it.

Projection binds a KI's own server paths into the project's verified copy, so a
cache or run folder spelled from the KI's path would change bytes the integrity
guard checks. The model itself is replaced by a stub; everything else is the
KI's shipped code, projected exactly as a desktop project projects it.
"""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from kiss_cli import ki_verification, paths, port

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "models"


def project(tmp_path, name):
    """The model's home and its KI copy, as ``models/<KI>/`` and ``models/<KI>/ki``."""
    cfg = paths.KissConfig.default(tmp_path / "project")
    home = Path(cfg.roles["ki_root"]) / name
    port.materialise(LIBRARY / name, home / "ki", cfg, ki_target=home / "ki", model=name)
    return home, home / "ki"


def load(path, name, monkeypatch):
    # KI tool runs put the shared helpers on PYTHONPATH; sys.path is restored after.
    monkeypatch.syspath_prepend(str(REPO / "ki_tools_common"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finished(cmd, **_):
    return subprocess.CompletedProcess(cmd, 0, "", "")


def test_marrmot_candidate_and_cached_inputs_stay_out_of_the_ki(tmp_path, monkeypatch):
    home, ki = project(tmp_path, "MARRMoT")
    contract = yaml.safe_load((ki / "calibration.yaml").read_text(encoding="utf-8"))
    assert contract["injection"]["mode"] == "runner"
    assert not [p["name"] for p in contract["parameters"] if (p.get("address") or {}).get("root")]

    dates = pd.date_range("1979-01-01", "1990-12-31", freq="D").strftime("%Y-%m-%d")
    q = np.random.default_rng(0).gamma(2.0, 1.0, len(dates))
    real_case = home / "detached" / "real_case"
    real_case.mkdir(parents=True)
    pd.DataFrame({"date": dates, "P": 2.0, "T": 15.0, "Ep": 1.0}).to_csv(real_case / "forcing.csv", index=False)
    pd.DataFrame({"date": dates, "Q_mm_d": q}).to_csv(real_case / "obs_q.csv", index=False)
    before = ki_verification.content_digest(ki)

    run = load(ki / "tools" / "calib_run.py", "marrmot_calib_run", monkeypatch)

    def forward(cmd, **kwargs):
        output = Path(cmd[cmd.index("--output") + 1])
        pd.DataFrame({"Q_mm_d": q * 0.9}).to_csv(output.parent / "marrmot_timeseries.csv", index=False)
        return finished(cmd, **kwargs)

    monkeypatch.setattr(run, "subprocess", types.SimpleNamespace(run=forward))
    workdir = tmp_path / "project" / "calibration" / "runs" / "r1"
    workdir.mkdir(parents=True)
    handed = {"x1": 350.0, "x2": 1.5, "x3": 120.0, "x4": 4.0}
    (workdir / "kdt_params.json").write_text(json.dumps(handed), encoding="utf-8")
    monkeypatch.setenv("KDT_CALIB_PARAMS", str(workdir / "kdt_params.json"))
    metrics_file = workdir / "calib_metrics.json"
    monkeypatch.setattr(sys, "argv", ["calib_run.py", "--workdir", str(workdir), "--out", str(metrics_file)])

    run.main()

    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    assert metrics["__kdt__"]["applied_params"] == handed
    assert np.isfinite(metrics["nse"])
    assert (workdir / "calib" / "forcing.csv").is_file()
    assert ki_verification.content_digest(ki) == before


def test_modflow6_forcing_cache_stays_out_of_the_ki(tmp_path, monkeypatch):
    _home, ki = project(tmp_path, "MODFLOW6")
    before = ki_verification.content_digest(ki)
    run = load(ki / "tools" / "calib_run.py", "modflow6_calib_run", monkeypatch)
    days = pd.date_range("2018-01-01", "2021-12-31", freq="D")
    loader = types.ModuleType("ki_tools_common.load_forcing")
    loader.load_daily_forcing = lambda *_a, **_k: {
        "dates": list(days.to_pydatetime()), "precip_mm": np.ones(len(days))}
    monkeypatch.setitem(sys.modules, loader.__name__, loader)
    workdir = tmp_path / "project" / "calibration" / "runs" / "r1"

    monthly = run.ensure_forcing_cache(str(workdir))

    assert len(monthly) == 48
    assert (workdir / "calib" / f"cmfd_monthly_{run.STATION}.json").is_file()
    assert ki_verification.content_digest(ki) == before


def test_swatplus_verifier_runs_a_copy_of_its_deck(tmp_path, monkeypatch):
    _home, ki = project(tmp_path, "SWAT_Plus")
    deck = ki / "calib" / "run_txtinout"       # where the verifier reads its validated deck
    deck.mkdir(parents=True)
    (deck / "file.cio").write_text("deck\n", encoding="utf-8")
    (deck / "channel_sd_day.txt").write_text("stale\n", encoding="utf-8")
    before = ki_verification.content_digest(ki)
    run = load(ki / "run_and_score_v1b.py", "swatplus_run_and_score_v1b", monkeypatch)

    def binary(cmd, cwd, **kwargs):
        assert not (Path(cwd) / "channel_sd_day.txt").exists()
        (Path(cwd) / "channel_sd_day.txt").write_text("fresh\n", encoding="utf-8")
        return finished(cmd, **kwargs)

    monkeypatch.setattr(run, "subprocess", types.SimpleNamespace(run=binary))
    run.OUTDIR.mkdir(parents=True, exist_ok=True)

    run.run_binary()

    assert not run.TXTINOUT.resolve().is_relative_to(ki.resolve())
    assert (run.TXTINOUT / "file.cio").read_text(encoding="utf-8") == "deck\n"
    assert (run.TXTINOUT / "channel_sd_day.txt").read_text(encoding="utf-8") == "fresh\n"
    assert ki_verification.content_digest(ki) == before
