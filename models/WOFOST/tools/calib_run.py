#!/usr/bin/env python3
"""WOFOST/PCSE calibration driver — TARGET CASE ``OBS:spam2020`` (SPAM 2020 maize,
US Corn Belt / Iowa box), determining metric PBIAS.

    python3 tools/calib_run.py --workdir <wd> --out <metrics.json>

WHAT THIS IS
------------
The programmatic run+score used by calibration_kit (``injection.mode: runner``).
It reproduces EXACTLY the validated real-case coupling recorded in
``real_case_result.json`` / provenance ``WOFOST_20260704T091928Z``:

    WOFOST 7.2 (PCSE 6.0.12) Wofost72_PP, crop=maize variety=Grain_maize_205,
    NASA POWER forcing, HWSD soil, sowing 05-01 (campaign 04-20, max_duration 200),
    15 SPAM-2020 1.0-deg cells over lat[40,43] lon[-96,-91], years 2016-2020
    averaged per cell, TWSO(dry) -> market moisture 15.5%, harvested-area-weighted
    regional mean vs the SPAM regional mean  ->  PBIAS.

    Validated reference: pbias = -13.746346372413093 %  (n_cells = 15)

It NEVER reimplements the model: every simulation goes through the KI's own
canonical tools

    s3_weather_prep/create_csv_weather_file.py     (PCSE CSV weather)
    s2_soil_params/convert_hwsd_to_pcse_soil.py    (HWSD -> PCSE soil hydraulics)
    s4_agromanagement/generate_agromanagement_yaml.py (crop calendar)
    s6_execution/run_wofost_simulation.py          (engine instantiate + run + extract)

and the obs side goes through ``ki_tools_common.crop_obs.get_spam_regional_yield``.
The s2/s3/obs products are SITE-INVARIANT under the calibrated parameters, so they
are built ONCE into a persistent cache (``--prepare``, or automatically on the first
eval) and reused; every eval then only re-runs s4 + s6 (75 engine runs, ~2 s).

INJECTION (runner mode — REQUIRED here)
---------------------------------------
The KI regenerates its agromanagement each run and the crop parameters live inside
the PCSE crop-parameter library (``YAMLCropDataProvider``), not in a stable file the
model reads from the workdir. Injection therefore happens the MODEL'S OWN WAY:

  * crop parameters -> ``pcse.base.ParameterProvider.set_override()``, PCSE's native
    calibration API, applied to the very provider object the engine is built from;
  * management (sowing date) -> regenerated agromanagement YAML via the s4 KI tool.

Read-back is taken from the EFFECTIVE artifacts the engine consumed: the parameter
provider is snapshotted at CROP_FINISH (PCSE's engine clears overrides there,
pcse/engine.py:323) and the agromanagement YAML is re-read from disk. Any parameter
that cannot be written AND read back -> no metrics, non-zero exit.

FAIL-CLOSED
-----------
* pinned obs envelope (station identity, source, the exact 15-cell coordinate set,
  every cell yield + harvested area, the regional mean / min / max / total area)
  is ASSERTED on every eval — a changed or corrupted SPAM record is never scored;
* run health for EVERY cell-year comes from the s6 tool's own report
  (``maturity_reached``, ``final_dvs``, ``yield_twso_kgha``, ``n_days``): missing
  or None is a FAILURE, never defaulted to a passing value;
* a single failed cell-year aborts the eval (a partial cell set would compare a
  different sim domain to the fixed obs aggregate and bias PBIAS);
* on any failure: nothing is written to --out and the exit code is non-zero
  (the kit scores +inf).

SPLIT (env KDT_CALIB_SPLIT)
---------------------------
Blocked-spatial (leave-region-out) on the SPAM longitude columns:
  "calibration" -> the 9 western cells  (lon columns -95.5, -94.5, -93.5)
  "holdout"     -> the 6 eastern cells  (lon columns -92.5, -91.5)
  unset / "" / "full" / "all" -> all 15 cells (the validated full-domain record)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import logging
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KI = os.path.dirname(HERE)
TOOLS = os.path.join(KI, "tools")

for _cand in ("/mnt/disk1/Hydrocraft_server/models/ki_tools_common",):
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")) and _cand not in sys.path:
        sys.path.insert(0, _cand)

# ---------------------------------------------------------------------------
# TARGET CASE — PINNED.  Not one of these values may come from the environment:
# the scored gauge/obs is a property of the capability, not of the caller.
# ---------------------------------------------------------------------------
OBS_ID = "spam2020"
CASE_ID = "OBS:" + OBS_ID                    # -> "OBS:spam2020"
OBS_DATASET = "SPAM 2020 V2r0 (IFPRI) all-technology maize yield Y_TA + harvested area H_TA"
OBS_SOURCE_FILES = ("Global_CSV/spam2020V2r0_global_yield.csv.zip",
                    "Global_CSV/spam2020V2r0_global_harvested_area.csv.zip")
REGION_NAME = "US Corn Belt (Iowa) maize"
SPAM_CROP = "maize"
LAT_RANGE = (40.0, 43.0)
LON_RANGE = (-96.0, -91.0)
BOX_STEP = 1.0

# validated run recipe (real_case_result.json / WOFOST_20260704T091928Z)
MODE = "PP"
CROP = "maize"
VARIETY = "Grain_maize_205"
YEAR_START, YEAR_END = 2016, 2020
MARKET_MOISTURE = 0.155
ELEV_M = 300.0
FORCING_SOURCE = "nasa_power"
SOW_MONTH, SOW_DAY = 5, 1                    # reference sowing date (05-01)
CAMPAIGN_LEAD_DAYS = 11                      # campaign start = sowing - 11 d (04-20)
MAX_DURATION = 200
REFERENCE_PBIAS = -13.746346372413093        # validated full-domain value

# --- PINNED OBS ENVELOPE (SPAM 2020, read 2026-08-04; identical to the validated run) ---
# (lat, lon, yield_kgha, harvested_area_ha) for every 1.0-deg box in the target region.
OBS_CELLS = [
    (40.5, -95.5, 12824.398282033751, 245476.29999999987),
    (40.5, -94.5, 10100.026034576642, 176303.99999999997),
    (40.5, -93.5, 11012.990568783962, 98248.19999999997),
    (40.5, -92.5, 10883.170517603534, 95691.00000000001),
    (40.5, -91.5, 10732.312288631598, 228008.30000000002),
    (41.5, -95.5, 12482.647780157049, 313634.8),
    (41.5, -94.5, 12948.045260712504, 262620.69999999995),
    (41.5, -93.5, 14468.67838094268, 183496.89999999994),
    (41.5, -92.5, 14498.595343130304, 268300.40000000014),
    (41.5, -91.5, 14612.1539978241, 262512.8000000001),
    (42.5, -95.5, 11255.865967537493, 337028.8),
    (42.5, -94.5, 12524.926986487631, 374930.60000000003),
    (42.5, -93.5, 12780.894722872117, 382022.20000000024),
    (42.5, -92.5, 12750.202282642485, 341279.9000000001),
    (42.5, -91.5, 13188.167576350594, 317381.29999999993),
]
OBS_N_CELLS = 15
OBS_AREA_WTD_MEAN = 12633.255207533377       # = the validated obs_area_wtd_mean_kgha
OBS_UNWEIGHTED_MEAN = 12470.871732685764
OBS_MIN_KGHA = 10100.026034576642
OBS_MAX_KGHA = 14612.1539978241
OBS_TOTAL_AREA_HA = 3886936.2
OBS_RTOL = 1e-6

# --- blocked-spatial holdout: the 2 EASTERNMOST longitude columns are held out ---
HOLDOUT_LON_COLUMNS = (-92.5, -91.5)         # 6 of 15 cells (0.40)

# ---------------------------------------------------------------------------
# Parameter contract (mirrors calibration.yaml; see it for ranges + citations)
# ---------------------------------------------------------------------------
SCALAR_PARAMS = {                            # name -> PCSE crop parameter name
    "TSUM1": "TSUM1", "TSUM2": "TSUM2", "SPAN": "SPAN", "TDWI": "TDWI",
    "RGRLAI": "RGRLAI", "CVO": "CVO", "Q10": "Q10",
}
TABLE_MULT_PARAMS = {                        # name -> PCSE AFGEN table scaled on its y-values
    "AMAXTB_MULT": "AMAXTB", "SLATB_MULT": "SLATB",
    "EFFTB_MULT": "EFFTB", "KDIFTB_MULT": "KDIFTB",
}
PARTITION_PARAM = "FOTB_EXP"                 # storage-organ partitioning shape exponent
MGMT_PARAM = "SOW_OFFSET_DAYS"               # sowing-date shift (days) vs the 05-01 reference

DEFAULTS = {
    "TSUM1": 935.0, "TSUM2": 920.0, "SPAN": 33.0, "TDWI": 50.0,
    "RGRLAI": 0.0294, "CVO": 0.671, "Q10": 2.0,
    "AMAXTB_MULT": 1.0, "SLATB_MULT": 1.0, "EFFTB_MULT": 1.0, "KDIFTB_MULT": 1.0,
    "FOTB_EXP": 1.0, "SOW_OFFSET_DAYS": 0,
}
READBACK_RTOL = 1e-9
KNOWN_PARAMS = frozenset(DEFAULTS)

log = logging.getLogger("wofost_calib_run")


class CalibError(RuntimeError):
    """Any condition that must produce NO metrics and a non-zero exit."""


# ---------------------------------------------------------------------------
# KI tool loading — the tools are executed IN-PROCESS (module globals + process())
# so pcse is imported once per eval instead of 75 times. Same code path as the
# validated subprocess invocation, just without the interpreter start-up.
# ---------------------------------------------------------------------------
def _load_tool(name, *relpath):
    path = os.path.join(TOOLS, *relpath)
    if not os.path.isfile(path):
        raise CalibError(f"KI tool missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# OBS side — resolve, then ASSERT the whole declared envelope
# ---------------------------------------------------------------------------
def _close(a, b, rtol=OBS_RTOL):
    return (a is not None and b is not None
            and math.isfinite(float(a)) and math.isfinite(float(b))
            and math.isclose(float(a), float(b), rel_tol=rtol, abs_tol=0.0))


def _read_spam_obs():
    """Read the SPAM 2020 regional aggregate through the KI's obs helper.

    ki_tools_common.crop_obs opens the SPAM zip archives with zipfile.ZipFile(path)
    (read-only) — the obs catalogue is never opened for writing.
    """
    from ki_tools_common.crop_obs import get_spam_regional_yield, SPAM_DIR
    if not os.path.isdir(SPAM_DIR):
        raise CalibError(f"SPAM 2020 root not found: {SPAM_DIR}")
    for rel in OBS_SOURCE_FILES:
        p = os.path.join(SPAM_DIR, rel)
        if not os.path.isfile(p):
            raise CalibError(f"SPAM source file missing: {p}")
    o = get_spam_regional_yield(SPAM_CROP, LAT_RANGE, LON_RANGE, step=BOX_STEP)
    cells = [(round(float(la), 4), round(float(lo), 4), float(y), float(a))
             for (la, lo, y), a in zip(o.get("cells") or [], o.get("areas") or [])]
    return {"source_dir": SPAM_DIR, "cells": cells,
            "area_weighted_mean_kgha": o.get("area_weighted_mean_kgha"),
            "unweighted_mean_kgha": o.get("unweighted_mean_kgha")}


def _assert_obs_envelope(rec):
    """Every obs-envelope field the contract declares is READ and ASSERTED here.
    A changed/corrupted SPAM record for the SAME region can never be silently scored."""
    cells = rec.get("cells") or []
    if len(cells) != OBS_N_CELLS:
        raise CalibError(f"obs envelope: n_cells {len(cells)} != pinned {OBS_N_CELLS}")
    got = {(c[0], c[1]): (c[2], c[3]) for c in cells}
    for la, lo, yld, area in OBS_CELLS:
        if (la, lo) not in got:
            raise CalibError(f"obs envelope: pinned cell ({la},{lo}) absent from SPAM record")
        g_y, g_a = got[(la, lo)]
        if not _close(g_y, yld):
            raise CalibError(f"obs envelope: cell ({la},{lo}) yield {g_y} != pinned {yld}")
        if not _close(g_a, area):
            raise CalibError(f"obs envelope: cell ({la},{lo}) harvested area {g_a} != pinned {area}")
    ys = [c[2] for c in cells]
    ars = [c[3] for c in cells]
    if not _close(rec.get("area_weighted_mean_kgha"), OBS_AREA_WTD_MEAN):
        raise CalibError(f"obs envelope: regional area-weighted mean "
                         f"{rec.get('area_weighted_mean_kgha')} != pinned {OBS_AREA_WTD_MEAN}")
    if not _close(rec.get("unweighted_mean_kgha"), OBS_UNWEIGHTED_MEAN):
        raise CalibError(f"obs envelope: unweighted mean "
                         f"{rec.get('unweighted_mean_kgha')} != pinned {OBS_UNWEIGHTED_MEAN}")
    if not _close(min(ys), OBS_MIN_KGHA) or not _close(max(ys), OBS_MAX_KGHA):
        raise CalibError(f"obs envelope: cell-yield range [{min(ys)},{max(ys)}] != pinned "
                         f"[{OBS_MIN_KGHA},{OBS_MAX_KGHA}]")
    if not _close(sum(ars), OBS_TOTAL_AREA_HA):
        raise CalibError(f"obs envelope: total harvested area {sum(ars)} != pinned "
                         f"{OBS_TOTAL_AREA_HA}")
    return rec


def resolve_obs(cache_dir):
    """The ONE place the scored obs is resolved. Returns the validated obs record;
    `case_id` / `scored_obs` are derived from THIS record, so the self-declaration
    cannot diverge from what was scored."""
    cache = os.path.join(cache_dir, "spam_obs.json")
    rec = None
    if os.path.isfile(cache):
        try:
            with open(cache, "r") as fh:                    # read-only
                d = json.load(fh)
            if d.get("obs_id") == OBS_ID:
                rec = {"source_dir": d["source_dir"],
                       "cells": [tuple(c) for c in d["cells"]],
                       "area_weighted_mean_kgha": d["area_weighted_mean_kgha"],
                       "unweighted_mean_kgha": d["unweighted_mean_kgha"]}
        except Exception as e:                              # corrupt cache -> re-read SPAM
            log.warning("obs cache unreadable (%s); re-reading SPAM", e)
            rec = None
    if rec is None:
        rec = _read_spam_obs()
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache, "w") as fh:
                json.dump({"obs_id": OBS_ID, **rec}, fh, indent=1)
        except OSError:
            pass                                           # read-only cache root is fine
    _assert_obs_envelope(rec)                              # ALWAYS, cached or fresh
    rec["obs_id"] = OBS_ID
    rec["dataset"] = OBS_DATASET
    return rec


def select_split(cells, split):
    """Blocked-spatial split on the SPAM longitude columns."""
    if split == "calibration":
        sel = [c for c in cells if c[1] not in HOLDOUT_LON_COLUMNS]
    elif split == "holdout":
        sel = [c for c in cells if c[1] in HOLDOUT_LON_COLUMNS]
    else:
        sel = list(cells)
    if not sel:
        raise CalibError(f"split {split!r} selected no cells")
    return sorted(sel)


def resolve_split():
    raw = (os.environ.get("KDT_CALIB_SPLIT") or "").strip().lower()
    if raw == "holdout":
        return "holdout"
    if raw == "calibration":
        return "calibration"
    return "full"          # unset / "" / "full" / "all" -> the validated full domain


# ---------------------------------------------------------------------------
# PREPARE — site-invariant inputs (forcing + soil), built once, reused by every eval
# ---------------------------------------------------------------------------
def cache_root():
    """Persistent cache for the site-invariant inputs. Never holds obs identity —
    the obs envelope is re-asserted against the pinned constants on every eval."""
    env = os.environ.get("KDT_CALIB_WOFOST_CACHE")
    if env:
        return os.path.abspath(env)
    for cand in (os.path.join(KI, ".calib_cache", "OBS_spam2020_corn_belt"),
                 os.path.join(os.path.expanduser("~"), ".cache", "kdt_wofost_calib",
                              "OBS_spam2020_corn_belt")):
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".w")
            with open(probe, "w") as fh:
                fh.write("")
            os.unlink(probe)
            return cand
        except OSError:
            continue
    raise CalibError("no writable cache root for the prepared WOFOST inputs")


def _vap_kpa(shum_kgkg, pres_pa):
    q = max(float(shum_kgkg), 1e-6)
    return ((q * float(pres_pa)) / (0.622 + 0.378 * q)) / 1000.0


def _write_generic_weather(forcing, out_csv):
    """The generic CSV the s3 KI tool consumes (W/m2 IRRAD, mm RAIN) — identical to
    the validated real-case runner."""
    dates = [str(d) for d in forcing["dates"]]
    srad, tmin = forcing["srad_wm2"], forcing["temp_min_c"]
    tmax, wind = forcing["temp_max_c"], forcing["wind_ms"]
    rain, shum, pres = forcing["precip_mm"], forcing["shum_kgkg"], forcing["pres_pa"]
    with open(out_csv, "w") as f:
        f.write("date,IRRAD,TMIN,TMAX,VAP,WIND,RAIN\n")
        for i in range(len(dates)):
            f.write(f"{dates[i]},{float(srad[i]):.2f},{float(tmin[i]):.2f},"
                    f"{float(tmax[i]):.2f},{_vap_kpa(shum[i], pres[i]):.4f},"
                    f"{float(wind[i]):.2f},{float(rain[i]):.4f}\n")


def _check_weather_csv(path, lat, lon):
    """Validate the cached PCSE weather CSV really is this cell's full record."""
    hdr, ndays, first, last = None, 0, None, None
    with open(path, "r") as fh:                                  # read-only
        for line in fh:
            if line.startswith("Longitude"):
                hdr = line.strip()
            elif line[:1].isdigit():
                ndays += 1
                first = first or line.split(",")[0]
                last = line.split(",")[0]
    if hdr is None:
        raise CalibError(f"weather cache {path}: no site header")
    if f"Longitude = {lon}" not in hdr or f"Latitude = {lat}" not in hdr:
        raise CalibError(f"weather cache {path}: header {hdr!r} is not cell ({lat},{lon})")
    need_first, need_last = f"{YEAR_START}0101", f"{YEAR_END}1231"
    if first != need_first or last != need_last:
        raise CalibError(f"weather cache {path}: covers {first}..{last}, need "
                         f"{need_first}..{need_last}")
    exp = (_dt.date(YEAR_END, 12, 31) - _dt.date(YEAR_START, 1, 1)).days + 1
    if ndays != exp:
        raise CalibError(f"weather cache {path}: {ndays} days, expected {exp}")


def ensure_cell_inputs(cache_dir, lat, lon, s2, s3):
    """PCSE weather CSV + PCSE soil JSON for one cell (built once, then reused)."""
    cdir = os.path.join(cache_dir, "cells", f"{lat:.2f}_{lon:.2f}")
    # UNIQUE BASENAME PER CELL (trap): PCSE's CSVWeatherDataProvider keys its pickle
    # cache on the file BASENAME only (pcse/input/csvweatherdataprovider.py:251) and
    # reuses it whenever the cache is newer than the CSV. With every cell's file
    # called "weather_pcse.csv" all 15 cells silently load the FIRST cell's weather
    # (observed: every cell returned an identical yield). The validated real-case
    # runner dodged this only because it regenerated each CSV immediately before use.
    wx = os.path.join(cdir, f"weather_pcse_{lat:.2f}_{lon:.2f}.csv")
    soil = os.path.join(cdir, "soil.json")
    if not os.path.isfile(wx):
        os.makedirs(cdir, exist_ok=True)
        from ki_tools_common.load_forcing import load_daily_forcing
        forcing, last = None, None
        for _try in range(4):                    # NASA POWER is occasionally flaky
            try:
                forcing = load_daily_forcing(FORCING_SOURCE, lat, lon, YEAR_START, YEAR_END)
                break
            except Exception as e:               # noqa: BLE001 - retried, then raised
                last = e
                log.warning("forcing fetch %s,%s attempt %d failed: %s", lat, lon, _try + 1, e)
        if forcing is None:
            raise CalibError(f"forcing unavailable for cell ({lat},{lon}): {last}")
        generic = os.path.join(cdir, "weather_generic.csv")
        _write_generic_weather(forcing, generic)
        s3.INPUT_CSV = generic
        s3.LAT, s3.LON, s3.ELEV = lat, lon, ELEV_M
        s3.OUTPUT_FILE = wx
        s3.IRRAD_IS_WM2 = True                   # srad is W/m2 -> x86.4 kJ/m2/day
        s3.RAIN_IS_CM = False                    # load_forcing already gives mm
        s3.validate_inputs()
        s3.process()
    _check_weather_csv(wx, lat, lon)
    if not os.path.isfile(soil):
        os.makedirs(cdir, exist_ok=True)
        s2.LAT, s2.LON = lat, lon
        params = s2.process()
        with open(soil, "w") as fh:
            json.dump(params, fh, indent=2)
    with open(soil, "r") as fh:                                  # read-only
        sp = json.load(fh)
    for k in ("SMW", "SMFCF", "SM0", "CRAIRC", "K0", "SOPE", "KSUB", "RDMSOL"):
        if sp.get(k) is None:
            raise CalibError(f"soil cache {soil}: missing {k}")
    return wx, soil


# ---------------------------------------------------------------------------
# INJECTION — PCSE's own ParameterProvider.set_override + regenerated agromanagement
# ---------------------------------------------------------------------------
def _afgen(table, x):
    xs, ys = table[0::2], table[1::2]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            f = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + f * (ys[i] - ys[i - 1])
    return ys[-1]


def _scaled_table(table, mult):
    return [(v * mult if i % 2 else v) for i, v in enumerate(table)]


def _table_mult_readback(base, eff):
    """Recover the multiplier actually present in the effective table."""
    if len(base) != len(eff):
        raise CalibError("table read-back: length changed")
    ratios = [e / b for b, e in zip(base[1::2], eff[1::2]) if abs(b) > 0]
    if not ratios:
        raise CalibError("table read-back: no non-zero base entries")
    if max(ratios) - min(ratios) > 1e-9 * max(1.0, max(abs(r) for r in ratios)):
        raise CalibError(f"table read-back: non-uniform scaling {ratios}")
    return sum(ratios) / len(ratios)


def _partition_tables(fotb, fltb, fstb, p):
    """FO' = FO**p on the union DVS grid, with FL/FS renormalised so the WOFOST
    partitioning identity FL+FS+FO == 1 holds exactly at every knot (PCSE checks
    this in DVS_Partitioning._check_partitioning)."""
    knots = sorted(set(fotb[0::2]) | set(fltb[0::2]) | set(fstb[0::2]))
    fo_n, fl_n, fs_n = [], [], []
    for u in knots:
        fo, fl, fs = _afgen(fotb, u), _afgen(fltb, u), _afgen(fstb, u)
        fo2 = fo ** p if fo > 0.0 else 0.0
        rem, base_rem = 1.0 - fo2, fl + fs
        if base_rem > 1e-12:
            k = rem / base_rem
            fl2, fs2 = fl * k, fs * k
        else:
            fl2 = fs2 = 0.0
        fo_n += [u, fo2]
        fl_n += [u, fl2]
        fs_n += [u, fs2]
    return fo_n, fl_n, fs_n


def _fotb_exp_readback(base_fotb, eff_fotb):
    """p = ln(FO')/ln(FO) at a knot where 0 < FO < 1 (DVS 1.1 for maize: FO = 0.5)."""
    for x, y in zip(base_fotb[0::2], base_fotb[1::2]):
        if 0.0 < y < 1.0:
            y2 = _afgen(eff_fotb, x)
            if not (0.0 < y2 < 1.0):
                raise CalibError(f"FOTB read-back: effective FO({x})={y2} out of (0,1)")
            return math.log(y2) / math.log(y)
    raise CalibError("FOTB read-back: no knot with 0 < FO < 1")


class _Injector:
    """Patches pcse.base.ParameterProvider so the values are applied to the very
    provider the engine is constructed with (PCSE's documented calibration hook),
    and snapshots the effective values at CROP_FINISH, where the engine clears the
    overrides (pcse/engine.py:323)."""

    def __init__(self, params):
        self.req = params
        self.base = {}          # untouched crop-parameter defaults
        self.snapshots = []     # effective values as consumed by each engine run

    def install(self):
        import pcse.base
        from pcse.input import YAMLCropDataProvider
        cd = YAMLCropDataProvider()
        cd.set_active_crop(CROP, VARIETY)
        for pname in list(SCALAR_PARAMS.values()) + list(TABLE_MULT_PARAMS.values()) \
                + ["FOTB", "FLTB", "FSTB"]:
            if pname not in cd:
                raise CalibError(f"crop parameter {pname} absent from {CROP}/{VARIETY}")
            v = cd[pname]
            self.base[pname] = list(v) if isinstance(v, (list, tuple)) else v

        overrides = {}
        for name, pname in SCALAR_PARAMS.items():
            if name in self.req:
                overrides[pname] = float(self.req[name])
        for name, pname in TABLE_MULT_PARAMS.items():
            if name in self.req:
                overrides[pname] = _scaled_table(self.base[pname], float(self.req[name]))
        if PARTITION_PARAM in self.req:
            fo, fl, fs = _partition_tables(self.base["FOTB"], self.base["FLTB"],
                                           self.base["FSTB"], float(self.req[PARTITION_PARAM]))
            overrides["FOTB"], overrides["FLTB"], overrides["FSTB"] = fo, fl, fs

        watch = sorted(set(overrides) | {"FOTB", "FLTB", "FSTB"})
        inj = self
        _Base = pcse.base.ParameterProvider

        class _CalibParameterProvider(_Base):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                for _n, _v in overrides.items():
                    self.set_override(_n, _v, check=True)     # PCSE native injection
                for _n, _v in overrides.items():              # immediate read-back
                    _got = self[_n]
                    if isinstance(_v, list):
                        if [round(z, 12) for z in _got] != [round(z, 12) for z in _v]:
                            raise CalibError(f"{_n}: provider read-back != requested")
                    elif not math.isclose(float(_got), float(_v), rel_tol=READBACK_RTOL):
                        raise CalibError(f"{_n}: provider read-back {_got} != requested {_v}")

            def clear_override(self, varname=None):
                if varname is None:      # engine clears at CROP_FINISH -> snapshot first
                    inj.snapshots.append({n: (list(self[n]) if isinstance(self[n], (list, tuple))
                                              else self[n]) for n in watch})
                return super().clear_override(varname)

        pcse.base.ParameterProvider = _CalibParameterProvider
        self._overrides = overrides
        return self

    def applied_params(self):
        """Read the requested parameters BACK from the effective provider state that
        the engine consumed (snapshot taken at CROP_FINISH of every cell-year)."""
        if not self.snapshots:
            raise CalibError("no parameter snapshot captured — the engine never ran a crop")
        out = None
        for snap in self.snapshots:
            got = {}
            for name, pname in SCALAR_PARAMS.items():
                if name in self.req:
                    got[name] = float(snap[pname])
            for name, pname in TABLE_MULT_PARAMS.items():
                if name in self.req:
                    got[name] = _table_mult_readback(self.base[pname], snap[pname])
            if PARTITION_PARAM in self.req:
                got[PARTITION_PARAM] = _fotb_exp_readback(self.base["FOTB"], snap["FOTB"])
                for u, fo, fl, fs in zip(snap["FOTB"][0::2], snap["FOTB"][1::2],
                                         snap["FLTB"][1::2], snap["FSTB"][1::2]):
                    if abs(fo + fl + fs - 1.0) > 1e-9:
                        raise CalibError(f"partitioning identity broken at DVS {u}: "
                                         f"FO+FL+FS = {fo + fl + fs}")
            if out is None:
                out = got
            elif any(not math.isclose(float(out[k]), float(got[k]), rel_tol=1e-9)
                     for k in got):
                raise CalibError("parameter read-back differs between cell-years")
        return out


# ---------------------------------------------------------------------------
# One eval
# ---------------------------------------------------------------------------
def read_requested_params():
    """The candidate vector handed by the kit (env KDT_CALIB_PARAMS); defaults when
    the driver is run standalone. Unknown keys fail closed — an un-injectable
    parameter must never be silently ignored."""
    pf = os.environ.get("KDT_CALIB_PARAMS")
    handed = {}
    if pf:
        if not os.path.isfile(pf):
            raise CalibError(f"KDT_CALIB_PARAMS points at a missing file: {pf}")
        with open(pf, "r") as fh:                                # read-only
            handed = json.load(fh)
        if not isinstance(handed, dict):
            raise CalibError("KDT_CALIB_PARAMS must contain a JSON object")
        unknown = sorted(set(handed) - KNOWN_PARAMS)
        if unknown:
            raise CalibError(f"unknown parameter(s) {unknown} — this driver cannot inject them")
    req = dict(DEFAULTS)
    for k, v in handed.items():
        req[k] = int(round(float(v))) if k == MGMT_PARAM else float(v)
    return req, set(handed)


def _agro_yaml(s4, workdir, year, offset_days):
    sow = _dt.date(year, SOW_MONTH, SOW_DAY) + _dt.timedelta(days=int(offset_days))
    camp = sow - _dt.timedelta(days=CAMPAIGN_LEAD_DAYS)
    out = os.path.join(workdir, f"agro_{year}.yaml")
    s4.CROP_NAME, s4.VARIETY_NAME = CROP, VARIETY
    s4.CAMPAIGN_START = camp.isoformat()
    s4.CROP_START_DATE = sow.isoformat()
    s4.CROP_START_TYPE, s4.CROP_END_TYPE = "sowing", "maturity"
    s4.MAX_DURATION = MAX_DURATION
    s4.OUTPUT_FILE = out
    s4.process()
    import yaml
    with open(out, "r") as fh:                                   # read-back from disk
        loaded = yaml.safe_load(fh)
    cal = list(loaded[0].values())[0]["CropCalendar"]
    got = cal["crop_start_date"]
    if isinstance(got, _dt.datetime):
        got = got.date()
    if got != sow:
        raise CalibError(f"agromanagement read-back: crop_start_date {got} != {sow}")
    if cal.get("crop_name") != CROP or cal.get("variety_name") != VARIETY:
        raise CalibError("agromanagement read-back: wrong crop/variety")
    return out, (got - _dt.date(year, SOW_MONTH, SOW_DAY)).days


def _run_cell_year(s6, wx, soil, agro, out_csv):
    s6.SIMULATION_MODE, s6.CROP_NAME, s6.VARIETY_NAME = MODE, CROP, VARIETY
    s6.WEATHER_CSV, s6.AGRO_YAML = wx, agro
    s6.OUTPUT_CSV, s6.SOIL_PARAMS_JSON = out_csv, soil
    res = s6.process()
    # FAIL-CLOSED run health, straight from the s6 tool's own report. A missing or
    # None diagnostic is a failure — never defaulted to a passing value.
    for key in ("maturity_reached", "final_dvs", "yield_twso_kgha", "n_days"):
        if res.get(key) is None:
            raise CalibError(f"s6 run report missing {key!r}")
    if str(res["maturity_reached"]).lower() not in ("true", "1"):
        raise CalibError(f"crop did not reach maturity (final_dvs={res['final_dvs']})")
    if float(res["final_dvs"]) < 2.0:
        raise CalibError(f"final_dvs {res['final_dvs']} < 2.0 (DVSEND)")
    if int(res["n_days"]) <= 0:
        raise CalibError("simulation produced no days")
    twso = float(res["yield_twso_kgha"])
    if not math.isfinite(twso) or twso <= 0.0:
        raise CalibError(f"non-positive/non-finite TWSO {twso}")
    return twso


def evaluate(workdir):
    req, handed = read_requested_params()
    cdir = cache_root()
    obs = resolve_obs(cdir)                       # + full envelope assertion
    split = resolve_split()
    cells = select_split(obs["cells"], split)

    s2 = _load_tool("kdt_s2", "s2_soil_params", "convert_hwsd_to_pcse_soil.py")
    s3 = _load_tool("kdt_s3", "s3_weather_prep", "create_csv_weather_file.py")
    s4 = _load_tool("kdt_s4", "s4_agromanagement", "generate_agromanagement_yaml.py")
    s6 = _load_tool("kdt_s6", "s6_execution", "run_wofost_simulation.py")

    inj = _Injector(req).install()
    os.makedirs(workdir, exist_ok=True)

    offsets = set()
    agro = {}
    for yr in range(YEAR_START, YEAR_END + 1):
        path, off = _agro_yaml(s4, workdir, yr, req[MGMT_PARAM])
        agro[yr] = path
        offsets.add(off)
    if len(offsets) != 1:
        raise CalibError(f"inconsistent sowing offsets across years: {sorted(offsets)}")

    sim, obs_v, wts = [], [], []
    for (lat, lon, obs_kgha, area) in cells:
        wx, soil = ensure_cell_inputs(cdir, lat, lon, s2, s3)
        yields = []
        for yr in range(YEAR_START, YEAR_END + 1):
            out_csv = os.path.join(workdir, f"out_{lat:.2f}_{lon:.2f}_{yr}.csv")
            try:
                yields.append(_run_cell_year(s6, wx, soil, agro[yr], out_csv))
            except CalibError as e:
                raise CalibError(f"cell ({lat},{lon}) year {yr}: {e}")
        sim.append(sum(yields) / len(yields))     # multi-year mean, as validated
        obs_v.append(obs_kgha)
        wts.append(area)

    applied = inj.applied_params()
    applied[MGMT_PARAM] = offsets.pop()
    for name in handed:                           # requested == applied, or fail closed
        want, got = req[name], applied.get(name)
        if got is None:
            raise CalibError(f"{name}: no read-back value")
        if not math.isclose(float(got), float(want), rel_tol=1e-6, abs_tol=1e-12):
            raise CalibError(f"{name}: applied {got} != requested {want}")

    tw = sum(wts)
    if tw <= 0:
        raise CalibError("zero total harvested area over the scored cells")
    sim_dry = sum(s * w for s, w in zip(sim, wts)) / tw
    sim_mkt = sim_dry / (1.0 - MARKET_MOISTURE)   # TWSO is dry matter; SPAM is at market moisture
    obs_mean = sum(o * w for o, w in zip(obs_v, wts)) / tw
    if not (math.isfinite(sim_mkt) and math.isfinite(obs_mean) and obs_mean > 0):
        raise CalibError("non-finite aggregate")
    pbias = (sim_mkt - obs_mean) / obs_mean * 100.0
    pbias_dry = (sim_dry - obs_mean) / obs_mean * 100.0

    cell_key = ",".join(f"{la:.2f}/{lo:.2f}" for la, lo, _, _ in cells)
    scored_obs = (f"{obs['obs_id']} | {obs['dataset']} | source={obs['source_dir']}"
                  f"[{'; '.join(OBS_SOURCE_FILES)}] | crop={SPAM_CROP} | region={REGION_NAME}"
                  f" lat{LAT_RANGE} lon{LON_RANGE} step={BOX_STEP} | split={split}"
                  f" | n_cells={len(cells)} | cells={cell_key}"
                  f" | obs_area_wtd_mean_kgha={obs_mean:.6f}")

    return {
        # dag-valid family for TWSO @ regional_aggregate_time_series is
        # [trend_match, magnitude_accuracy]; SPAM 2020 is a SINGLE-year snapshot so
        # no trend metric is computable — only the determining metric pbias is emitted.
        "pbias": pbias,
        "pbias_dry": pbias_dry,
        "sim_area_wtd_mean_market_kgha": sim_mkt,
        "sim_area_wtd_mean_dry_kgha": sim_dry,
        "obs_area_wtd_mean_kgha": obs_mean,
        "__kdt__": {
            "applied_params": {k: applied[k] for k in sorted(applied)},
            "case_id": "OBS:" + obs["obs_id"],
            "scored_obs": scored_obs,
            "split": split,
            "n_cells": len(cells),
            "variable": "TWSO",
            "mode": MODE, "crop": CROP, "variety": VARIETY,
            "years": f"{YEAR_START}-{YEAR_END}",
            "market_moisture": MARKET_MOISTURE,
            "reference_pbias_full_domain": REFERENCE_PBIAS,
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--prepare", action="store_true",
                    help="build the site-invariant input cache (forcing + soil + obs) and exit")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    if not args.verbose:
        logging.disable(logging.INFO)

    try:
        if args.prepare:
            cdir = cache_root()
            obs = resolve_obs(cdir)
            s2 = _load_tool("kdt_s2", "s2_soil_params", "convert_hwsd_to_pcse_soil.py")
            s3 = _load_tool("kdt_s3", "s3_weather_prep", "create_csv_weather_file.py")
            for (lat, lon, _y, _a) in obs["cells"]:
                ensure_cell_inputs(cdir, lat, lon, s2, s3)
                print(f"  prepared {lat},{lon}", flush=True)
            print(f"PREPARED {len(obs['cells'])} cells in {cdir}")
            return 0
        if not args.out:
            ap.error("--out is required unless --prepare")
        metrics = evaluate(os.path.abspath(args.workdir))
    except Exception as e:                       # NO metrics file, non-zero exit -> +inf
        print(f"calib_run FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 2
    with open(args.out, "w") as fh:
        json.dump(metrics, fh, indent=1)
    print(json.dumps({k: v for k, v in metrics.items() if k != "__kdt__"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
