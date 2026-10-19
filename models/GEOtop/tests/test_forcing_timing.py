"""Forcing timing and rain amount of tools/convert_forcing.py (2026-10-19 fix).

What GEOtop does (source/repo/src/geotop):
  * times.cc:130-138: the model clock is Python days since 0001-01-01 + 367.
  * meteodata.cc:589-607: a JDfrom0 column overrides Date.
  * meteodata.cc:137-245: a record stamped t is used for (t-dt, t].
  * keywords.h:437: HeaderIPrec is an intensity in mm/h.

The first tests check the tool's numbers only. The last ones run the real
binary on made-up test meteo (one rain pulse and one temperature step at
known times, written here on purpose) and check WHEN and HOW MUCH reaches
GEOtop. They are skipped when the binary is not there.
"""
import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

KI = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("GEOTOP_BINARY", KI.parent / "geotop"))


def _load():
    spec = importlib.util.spec_from_file_location("cf_timing", KI / "tools" / "convert_forcing.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cf = _load()


def geotop_clock(dt):
    """times.cc convert_dateeur12_JDfrom0, written out as in the C++."""
    y = dt.year
    jd = (dt - datetime(y, 1, 1)).total_seconds() / 86400.0
    days = 1 + 366 + (y - 1) * 365 + np.floor((y - 1) / 4.) - np.floor((y - 1) / 100.) \
        + np.floor((y - 1) / 400.)
    return jd + days


# ---------------------------------------------------------------- tool only

def test_jd_matches_geotop_clock():
    t = datetime(1900, 1, 1)
    while t < datetime(2101, 1, 1):
        for h in (0, 12, 21):
            x = t + timedelta(hours=h)
            assert abs(cf.date_to_jd_from0(x) - geotop_clock(x)) < 1e-9, x
        t += timedelta(days=7)
    # GEOtop's own Matsch_B2 output: 02/10/2009 01:00 -> 734048.041667
    assert f"{cf.date_to_jd_from0(datetime(2009, 10, 2, 1)):.6f}" == "734048.041667"


def test_stamp_rules():
    for src in ("cmfd", "mswx", "nasa_power"):
        assert set(cf.stamp_rules(src, True).values()) == {"start"}
    r = cf.stamp_rules("cmfd", False)
    assert r["Iprec"] == "end" and r["AirT"] == "pair" and r["Swglobal"] == "pair"
    r = cf.stamp_rules("mswx", False)
    assert r.pop("Swglobal") == "pair" and set(r.values()) == {"start"}
    assert set(cf.stamp_rules("nasa_power", False).values()) == {"start"}
    with pytest.raises(ValueError):
        cf.stamp_rules("era5", False)


def test_align_to_interval_end():
    idx = pd.date_range("2017-11-01 00:00", periods=4, freq="3h")
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [10.0, 20.0, 30.0, 40.0]}, index=idx)
    out = cf.align_to_interval_end(df, {"a": "end", "b": "pair"}, 10800)
    assert list(out.index) == list(idx[1:])                 # first pair has no record before
    assert list(out["a"]) == [2.0, 3.0, 4.0]
    assert list(out["b"]) == [15.0, 25.0, 35.0]
    out = cf.align_to_interval_end(df, {"a": "start", "b": "start"}, 10800)
    assert list(out.index) == list(idx + pd.Timedelta(hours=3))
    assert list(out["a"]) == [1.0, 2.0, 3.0, 4.0]
    # start + end mixed: only stamps both can fill
    out = cf.align_to_interval_end(df, {"a": "start", "b": "end"}, 10800)
    assert list(out.index) == list(idx[1:])
    assert list(out["a"]) == [1.0, 2.0, 3.0] and list(out["b"]) == [20.0, 30.0, 40.0]
    with pytest.raises(ValueError):
        cf.align_to_interval_end(df, {"a": "end"}, 10800)   # b has no rule
    nan = df.copy()
    nan.iloc[1, 1] = np.nan
    out = cf.align_to_interval_end(nan, {"a": "end", "b": "pair"}, 10800)
    assert np.isnan(out["b"].iloc[0]) and np.isnan(out["b"].iloc[1]) and out["b"].iloc[2] == 35.0


def test_upsample_interpolates_at_interval_centres():
    # native 3-h interval means of f(x) = x hours: the mean over (t-3, t] is t - 1.5
    idx = pd.date_range("2017-11-01 00:00", periods=10, freq="3h")
    hrs = (idx - idx[0]).total_seconds() / 3600.0
    df = pd.DataFrame({"AirT": hrs - 1.5, "Iprec": np.arange(10, dtype=float) * 3.0}, index=idx)
    out = cf.to_grid(df, idx[1], idx[-2], 3600)
    g = (out.index - idx[0]).total_seconds() / 3600.0
    np.testing.assert_allclose(out["AirT"].to_numpy(), g - 0.5, atol=1e-12)   # mean over (g-1, g]
    # rain: the 3-h depth is split over its 3 hours, each hour taking 1/3
    k = np.ceil(g / 3.0).astype(int)
    np.testing.assert_allclose(out["Iprec"].to_numpy(), k * 3.0 / 3.0, atol=1e-12)
    # the last stamp needs one record after the window
    with pytest.raises(cf.CoverageError) as e:
        cf.to_grid(df, idx[1], idx[-1], 3600)
    assert e.value.need_after


def _csv(path, step_s, rain_stamp, rain_mm, t_step, t0, t1):
    rows, t = [], t0
    while t <= t1:
        rows.append({"datetime": t.strftime("%Y-%m-%d %H:%M"),
                     "AirT": 5.0 if t <= t_step else 15.0,
                     "Iprec": rain_mm if t == rain_stamp else 0.0,
                     "RelHum": 60.0, "WindSp": 2.0, "Swglobal": 0.0, "LWin": 300.0,
                     "AirPress": 1010.0})
        t += timedelta(seconds=step_s)
    pd.DataFrame(rows).to_csv(path, index=False)


def _convert(csv_path, out, dt, start, end, stamp="end"):
    args = argparse.Namespace(
        source="csv", input=str(csv_path), lat=36.0, lon=116.0, elev=44.0,
        start=start.strftime(cf.GEOTOP_DATE_FMT), end=end.strftime(cf.GEOTOP_DATE_FMT),
        dt=dt, output=str(out), col_map="{}", temp_unit="C", rh_unit="percent",
        precip_unit="mm_step", date_format=None, pres_unit="hPa", csv_stamp=stamp)
    cf.process(args)
    return pd.read_csv(out)


START, END = datetime(2017, 11, 1), datetime(2017, 11, 5)
REC0, REC1 = datetime(2017, 10, 30), datetime(2017, 11, 7)
T_STEP = datetime(2017, 11, 3)
CASES = {   # record step: (rain stamp, rain depth mm)
    3600: (datetime(2017, 11, 2, 12), 6.0),
    10800: (datetime(2017, 11, 2, 12), 6.0),
    86400: (datetime(2017, 11, 3), 12.0),
}


@pytest.mark.parametrize("step", sorted(CASES))
def test_written_file_is_mm_per_hour_on_geotop_clock(step, tmp_path):
    rstamp, depth = CASES[step]
    _csv(tmp_path / "in.csv", step, rstamp, depth, T_STEP, REC0, REC1)
    m = _convert(tmp_path / "in.csv", tmp_path / "meteo0001.txt", step, START, END)
    d = pd.to_datetime(m["Date"], format=cf.GEOTOP_DATE_FMT)
    clock = np.array([geotop_clock(x.to_pydatetime()) for x in d])
    np.testing.assert_allclose(m["JDfrom0"].to_numpy(), clock, atol=1e-6)
    wet = m[m["Iprec"] > 0]
    assert len(wet) == 1 and wet["Date"].iloc[0] == rstamp.strftime(cf.GEOTOP_DATE_FMT)
    assert wet["Iprec"].iloc[0] == pytest.approx(depth / (step / 3600.0))


def test_csv_stamp_start_moves_rows_one_step(tmp_path):
    _csv(tmp_path / "in.csv", 10800, datetime(2017, 11, 2, 12), 6.0, T_STEP, REC0, REC1)
    m = _convert(tmp_path / "in.csv", tmp_path / "m.txt", 10800, START, END, stamp="start")
    wet = m[m["Iprec"] > 0]
    assert wet["Date"].iloc[0] == "02/11/2017 15:00"


def test_csv_stamp_start_file_ending_at_the_window_end(tmp_path):
    # rows 31/10 23:00 .. 01/11 23:00 stamped at the START cover 01/11 00:00 ..
    # 02/11 00:00 after the move: exactly the window, so it must be accepted
    # (round-1 review: the window was checked before the move and refused it)
    t0, t1 = datetime(2017, 10, 31, 23), datetime(2017, 11, 1, 23)
    _csv(tmp_path / "in.csv", 3600, datetime(2017, 11, 1, 23), 2.0, datetime(2017, 11, 1, 12), t0, t1)
    m = _convert(tmp_path / "in.csv", tmp_path / "m.txt", 3600,
                 datetime(2017, 11, 1), datetime(2017, 11, 2), stamp="start")
    assert m["Date"].iloc[0] == "01/11/2017 00:00" and m["Date"].iloc[-1] == "02/11/2017 00:00"
    wet = m[m["Iprec"] > 0]
    assert list(wet["Date"]) == ["02/11/2017 00:00"] and wet["Iprec"].iloc[0] == pytest.approx(2.0)
    # one hour more is not covered: refused, nothing made up
    with pytest.raises(cf.CoverageError):
        _convert(tmp_path / "in.csv", tmp_path / "m2.txt", 3600,
                 datetime(2017, 11, 1), datetime(2017, 11, 2, 1), stamp="start")


def _instant_csv(path):
    # 3-hourly INSTANT values AirT(t) = hours since 30/10 00:00; rain 6 mm in
    # the 3 h before 01/11 12:00
    t0 = datetime(2017, 10, 30)
    rows = []
    for i in range(40):
        t = t0 + timedelta(hours=3 * i)
        rows.append({"datetime": t.strftime("%Y-%m-%d %H:%M"), "AirT": 3.0 * i,
                     "Iprec": 6.0 if t == datetime(2017, 11, 1, 12) else 0.0,
                     "RelHum": 60.0, "WindSp": 2.0, "Swglobal": 0.0})
    pd.DataFrame(rows).to_csv(path, index=False)
    return t0


def test_csv_stamp_instant_pairs_state_values(tmp_path):
    t0 = _instant_csv(tmp_path / "in.csv")
    hrs = lambda d: (pd.to_datetime(d, format=cf.GEOTOP_DATE_FMT) - pd.Timestamp(t0)) \
        .dt.total_seconds().to_numpy() / 3600.0
    s, e = datetime(2017, 11, 1), datetime(2017, 11, 2)
    m = _convert(tmp_path / "in.csv", tmp_path / "m.txt", 3600, s, e, stamp="instant")
    # the row stamped g is the mean of AirT over (g-1, g] = g - 0.5 h
    np.testing.assert_allclose(m["AirT"].to_numpy(), hrs(m["Date"]) - 0.5, atol=0.006)
    wet = m[m["Iprec"] > 0]                      # rain: total since the row before
    assert list(wet["Date"]) == ["01/11/2017 10:00", "01/11/2017 11:00", "01/11/2017 12:00"]
    np.testing.assert_allclose(wet["Iprec"].to_numpy(), 2.0)
    # the same file read as "end" uses the instants 1.5 h late (documented)
    m = _convert(tmp_path / "in.csv", tmp_path / "m2.txt", 3600, s, e, stamp="end")
    np.testing.assert_allclose(m["AirT"].to_numpy(), hrs(m["Date"]) + 1.0, atol=0.006)
    # same step: (t-3, t] gets the mean of the instants at t-3 and t
    m = _convert(tmp_path / "in.csv", tmp_path / "m3.txt", 10800, s, e, stamp="instant")
    np.testing.assert_allclose(m["AirT"].to_numpy(), hrs(m["Date"]) - 1.5, atol=0.006)


def test_two_edge_retry_keeps_the_pads(tmp_path, monkeypatch):
    # CMFD-like loader: whole days, 3-hourly 00..21, temp/srad "pair". Window
    # 01/11 00:00 .. 03/11 21:00 at 1 h: try 1 lacks the record before the
    # first pair, try 2 lacks the record after 21:00, try 3 (both) works.
    lf = pytest.importorskip("ki_tools_common.load_forcing")
    calls = []

    def fake(source, lat, lon, y0, y1, forcing_dir=None, period=None):
        d0, d1 = period
        calls.append((d0, d1))
        idx = pd.date_range(pd.Timestamp(d0), pd.Timestamp(d1) + pd.Timedelta(hours=21), freq="3h")
        n = len(idx)
        hrs = (idx - pd.Timestamp("2017-10-01")).total_seconds().to_numpy() / 3600.0
        return {"dates": idx.to_pydatetime(), "temp_c": hrs / 100.0, "precip_mm": np.zeros(n),
                "srad_wm2": np.zeros(n), "wind_ms": np.full(n, 2.0), "shum_kgkg": np.full(n, 0.005),
                "pres_pa": np.full(n, 101325.0), "lrad_wm2": np.full(n, 300.0),
                "timestep_seconds": 10800}

    monkeypatch.setattr(lf, "load_hourly_forcing", fake)
    args = argparse.Namespace(
        source="cmfd", input="", lat=36.0, lon=116.0, elev=44.0,
        start="01/11/2017 00:00", end="03/11/2017 21:00", dt=3600,
        output=str(tmp_path / "m.txt"), csv_stamp="end")
    n = cf.process(args)
    assert n == 70
    from datetime import date
    assert calls == [(date(2017, 11, 1), date(2017, 11, 3)), (date(2017, 10, 31), date(2017, 11, 3)),
                     (date(2017, 10, 31), date(2017, 11, 4))]
    m = pd.read_csv(tmp_path / "m.txt")
    assert m["Date"].iloc[0] == "01/11/2017 00:00" and m["Date"].iloc[-1] == "03/11/2017 21:00"


# ---------------------------------------------------------- the real binary

SOIL = "Dz,Kh,Kv,vwc_r,vwc_w,vwc_fc,vwc_s,alpha,n,stor\n" + \
    "".join(f"{dz},3.81E-02,3.81E-02,0.05,0.05,0.10,0.37,0.00350,1.8,5.00E-07\n"
            for dz in (10, 10, 20, 20, 50, 50, 100, 100, 150, 150, 200, 200, 300, 300, 500, 500, 500))

INPTS = """TimeStepEnergyAndWater = 900
InitDateDDMMYYYYhhmm = 01/11/2017 00:00
EndDateDDMMYYYYhhmm = 05/11/2017 00:00
RecoverSim = 0
PointSim = 1
WaterBalance = 1
EnergyBalance = 1
DtPlotDischarge = 1
DtPlotBasin = 1
DtPlotPoint = 1
StandardTimeSimulation = 0
MeteoStationStandardTime = 0
Latitude = 36.0
Longitude = 116.0
FlagSkyViewFactor = 0
CalculateCastShadow = 0
LWinParameterization = 4
MoninObukhov = 1
CanopyStabCorrection = 1
NumberOfMeteoStations = 1
MeteoStationLatitude = 36.0
MeteoStationLongitude = 116.0
MeteoStationElevation = 44.0
MeteoStationWindVelocitySensorHeight = 10
MeteoStationTemperatureSensorHeight = 2
HeaderDateDDMMYYYYhhmmMeteo = "Date"
HeaderJulianDayfrom0Meteo = "JDfrom0"
HeaderIPrec = "Iprec"
HeaderWindVelocity = "WindSp"
HeaderWindDirection = "WindDir"
HeaderRH = "RelHum"
HeaderAirTemp = "AirT"
HeaderAirPress = "AirPress"
HeaderSWglobal = "Swglobal"
HeaderCloudSWTransmissivity = "CloudTrans"
HeaderLWin = "LWin"
PointElevation = 44.0
PointSlope = 0
PointAspect = 0
PointSkyViewFactor = 1
NumLandCoverTypes = 1
SoilRoughness = 50
VegHeight = 300
LSAI = 1.0
CanopyFraction = 0.6
RootDepth = 300
ThresTempRain = 3
ThresTempSnow = -1
PointSoilType = 1
SoilLayerTypes = 1
InitWaterTableDepth = +3000
InitSoilTemp = 8.6
FreeDrainageAtBottom = 0
HeaderSoilDz = "Dz"
HeaderLateralHydrConductivity = "Kh"
HeaderNormalHydrConductivity = "Kv"
HeaderThetaRes = "vwc_r"
HeaderWiltingPoint = "vwc_w"
HeaderFieldCapacity = "vwc_fc"
HeaderThetaSat = "vwc_s"
HeaderAlpha = "alpha"
HeaderN = "n"
HeaderSpecificStorativity = "stor"
MeteoFile = "meteo/meteo"
SoilParFile = "soil/soil"
PointOutputFile = "output-tabs/point"
PointAll = 1
"""

needs_binary = pytest.mark.skipif(not (BINARY.is_file() and os.access(BINARY, os.X_OK)),
                                  reason=f"GEOtop binary not found at {BINARY}")


@needs_binary
@pytest.mark.parametrize("step", sorted(CASES))
def test_geotop_gets_rain_and_step_at_the_right_time(step, tmp_path):
    rstamp, depth = CASES[step]
    sim = tmp_path / "sim"
    for sub in ("meteo", "soil", "output-tabs"):
        (sim / sub).mkdir(parents=True)
    (sim / "geotop.inpts").write_text(INPTS)
    (sim / "soil" / "soil0001.txt").write_text(SOIL)
    _csv(tmp_path / "in.csv", step, rstamp, depth, T_STEP, REC0, REC1)
    _convert(tmp_path / "in.csv", sim / "meteo" / "meteo0001.txt", step, START, END)
    p = subprocess.run([str(BINARY), str(sim)], capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    with open(sim / "output-tabs" / "point0001.txt") as f:
        rows = list(csv.DictReader(f))
    when = [datetime.strptime(r["Date12[DDMMYYYYhhmm]"], cf.GEOTOP_DATE_FMT) for r in rows]
    rain = np.array([float(r["Prain_over_canopy[mm]"]) + float(r["Psnow_over_canopy[mm]"])
                     for r in rows])
    # each output row covers the hour before its stamp; the record stamped
    # rstamp covers (rstamp - step, rstamp]
    inside = np.array([rstamp - timedelta(seconds=step) < w <= rstamp for w in when])
    assert rain.sum() == pytest.approx(depth, abs=1e-3)
    assert rain[~inside].sum() == pytest.approx(0.0, abs=1e-3)
    np.testing.assert_allclose(rain[inside], depth / (step / 3600.0), atol=1e-3)
    first_warm = next(w for w, r in zip(when, rows) if float(r["Tair[C]"]) > 10)
    assert first_warm == T_STEP + timedelta(hours=1)
