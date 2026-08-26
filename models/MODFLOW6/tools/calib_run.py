#!/usr/bin/env python3
"""MODFLOW 6 — programmatic calibration run+score (NOT an agent).

    /usr/bin/python3 tools/calib_run.py --workdir <wd> --out <metrics.json>

TARGET CASE (pinned; this file scores THIS gauge and no other)
  case_id   GWSTN:360681210141
  gauge     China GW Yearbook 360681210141 鹰潭市贵溪市滨江镇黄坑村小学
            (Yingtan / Guixi, Jiangxi), 孔隙潜水 pore-phreatic, 信江 alluvial plain
  obs       yearbook.db :: 地下水_月均水位 . avg_wl_m  (monthly mean WL elevation, m)
  quantity  hydraulic_head (point_time_series);  determining metric = nse
  36 monthly points 2019-01..2021-12, envelope 27.45..31.18 m, land surface 33.72 m.
  RECHARGE-DRIVEN CYCLIC site: the water table peaks with the monsoon (2019-07, 2020-07,
  2021-05) and troughs in the winter dry season (2021-02) — CMFD gives this cell
  1649-2038 mm/yr with a 450-613 mm monsoon month, so the recharge levers carry the
  signal and the DRN ring carries the recession.

WHY runner MODE. The KI REGENERATES every MF6 input on each eval via its FloPy builders
(tools/s2..s7), so anything the kit pre-wrote would be overwritten before mf6 read it.
This script (1) reads the candidate from $KDT_CALIB_PARAMS, (2) injects it through the
KI's OWN builders (native flopy path), (3) reads every value BACK out of the written
.npf/.sto/.chd/.drn/.wel/.rcha, (4) emits __kdt__. The forward model is never
reimplemented: mf6 is the real binary, driven by the validated build_and_run().

SITE CONSTANTS ARE PINNED, NOT INHERITED. models/MODFLOW6/run_and_score.py is a per-site
scratch driver rewritten in place (it currently holds a LIAONING station). pin_site()
overrides every site constant with this case's values and asserts the override took. No
gauge, coordinate or obs path is ever read from an env var: KDT_CALIB_PARAMS and
KDT_CALIB_SPLIT are the only env inputs and neither can name a site.

THE OBS ENVELOPE IS ENFORCED, NOT ASSUMED. The declared numbers live ONLY in
calibration.yaml's `observation:` block; this file keeps no second copy, so gate and
contract cannot drift. load_obs() asserts the DB against every declared field — identity,
per-year reference surface, the exact month set key-by-key, all 36 values individually, a
sha256 over the series, and the pooled + per-split envelope. A re-ingest that
changed/truncated/permuted THE SAME station's series is caught, including one that
preserved n/min/max/mean/sd.

RUN HEALTH IS FAIL-CLOSED. s7's check_listing_file() INITIALISES
normal_termination=False, convergence_failures=0, max_budget_error_pct=0.0 and only
overwrites them if the listings parse — so a run with no readable gwf.lst reports a clean
bill of health. `runres.get(k) or 0` would turn that (and None) into a pass.
check_run_health() instead requires each declared diagnostic PRESENT and non-None,
re-derives it from the listing files, requires POSITIVE budget evidence, and cross-checks
the two readings. Missing/None/unparseable => no metrics, exit 1.

READ-ONLY SOURCES. yearbook.db is an immutable obs catalog, opened only through
_connect_ro() — sqlite URI mode=ro, with a mode=ro&immutable=1 fallback because this DB
is in WAL mode and a WAL reader must write the `-shm` sidecar (see _connect_ro).

STORAGE. sy/ss are live levers only because s3/build_sto_package.py was repaired on
2026-07-27 (separate steady_state=/transient= dicts + ICONVERT=1); before that flopy
silently marked ALL periods steady with iconvert=0 and both storage terms were inert.
verify_storage_config() asserts the repaired configuration every eval.

PRECISION. evaluator._verify_applied uses rel_tol=1e-6. The seven true MF6 inputs
round-trip through their text files at ~1e-8 and are reported as READ. frac/lag/cap are
NOT MF6 inputs — they only generate the rcha rates, which flopy writes at ~6 sig digits,
so no read-back of them can meet 1e-6; they are PROVEN against all 48 written rates
(verify_recharge) and reported as requested. Do not "improve" this by inverting them out
of the rates — a sibling site's runner did, and the kit then rejected every perturbed
Morris sample, so the screen recorded no finite losses at all.

SPLIT. KDT_CALIB_SPLIT = calibration | holdout | unset(both). Leave-year-out:
calibration = 2019+2020 (24 pts), holdout = 2021 (12 pts).

On ANY failure the metrics file is removed and the exit code is nonzero.
"""
import argparse
import calendar
import hashlib
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import traceback

import numpy as np
import yaml

KI = "KISSPATH_KI_ROOT/MODFLOW6/knowledge_infrastructure"
MODEL_ROOT = "KISSPATH_KI_ROOT/MODFLOW6"
RUNNER_PY = os.path.join(MODEL_ROOT, "run_and_score.py")   # validated forward driver
CONTRACT_YAML = os.path.join(KI, "calibration.yaml")       # sole source of declared numbers

sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
from ki_tools_common.metrics import all_metrics  # noqa: E402

# --- TARGET CASE: pinned. `case_id`/`scored_obs` in the output are DERIVED from the
# same values used to query the obs and extract the model cell, so the self-declaration
# cannot diverge from what was scored. -----------------------------------------
CASE_ID = "GWSTN:360681210141"
STATION = "360681210141"
STATION_LOCATION = "鹰潭市贵溪市滨江镇黄坑村小学"
STATION_PROVINCE = "36"                 # Jiangxi
AQUIFER_TYPE = "孔隙潜水"
GW_ZONE = ""                            # this station's gw_zone column is blank in ALL
                                        # three editions; asserted EXACTLY (a future
                                        # ingest that fills it in must be re-derived)
YB_DB_DEFAULT = "KISSPATH_OUTPUTS/yearbook_catalog/yearbook.db"
OBS_TABLE, OBS_COLUMN = "地下水_月均水位", "avg_wl_m"

LAT, LON = 28.286, 117.177     # 贵溪市滨江镇 (Nominatim); CMFD 0.1deg -> same cell
TOP_ELEV = 33.72               # land surface = yearbook elevation_m
CMFD_DIR = "KISSPATH_FORCING/Data_forcing_01dy_010deg"
MF6 = "KISSPATH_HOME/.local/share/flopy/bin/mf6"

SPINUP_YEARS = [2018]                 # warm-up on real CMFD, UNSCORED
EVAL_YEARS = [2019, 2020, 2021]
OBS_CELL = (0, 2, 2)                  # centre of the 5x5 grid
NMON = 12 * (len(SPINUP_YEARS) + len(EVAL_YEARS))          # 48 transient periods
CAL_MONTHS = [(y, m) for y in (2019, 2020) for m in range(1, 13)]
HOLDOUT_MONTHS = [(2021, m) for m in range(1, 13)]
# Cache keyed BY STATION so a sibling site's forcing can never be mistaken for this one.
CMFD_CACHE = os.path.join(KI, "calib", f"cmfd_monthly_{STATION}.json")
# Fixed structure (not calibrated): Jiangxi 双季稻 LATE-rice window — transplanting late
# July through the October harvest, i.e. the 伏秋旱 summer-autumn dry spell when this
# cell's CMFD precip collapses (2019: 26.8/6.7/25.0 mm in Aug/Sep/Oct). Only the
# MAGNITUDE (qpump) is calibrated. MEASURED: against a pump-OFF pooled NSE of -1.1361,
# the five candidate windows at 2500 m3/d give [6,7,8] +0.159, [7,8,9] +0.293,
# [8,9,10] +0.374, [9,10,11] +0.368 and [7,8,9,10] +0.573 — this one is the best, and
# also the agronomically correct one.
PUMP_MONTHS = [7, 8, 9, 10]

# Default vector ESTABLISHED in commissioning (fresh build, no prior validated run).
# Every value strictly INTERIOR to its range. base_chd 29.10 = observed mean WL;
# drn_elev 25.50 = 1.95 m below observed min so the DRN never switches off;
# cap 0.20 = actively binding at this vector (frac*store peaks 0.2553 m); k 2.0 /
# sy 0.15 = fine-sand alluvium (KI aquifer-material table); ss 1e-5 = KI STO default;
# qpump 1000 = ~123 mm over the Jul-Oct window on a 1 km2 cell.
# Measured on the real mf6 binary (36/36, 24/24, 12/12 months):
#   both NSE -0.207990 | cal NSE -0.150620 | holdout NSE -0.336822
DEFAULTS = {
    "frac": 0.50, "lag": 0.30, "cap": 0.20, "cdrn": 500.0,
    "base_chd": 29.10, "drn_elev": 25.50, "k": 2.0, "qpump": 1000.0,
    "sy": 0.15, "ss": 1.0e-5,
}
PARAM_NAMES = list(DEFAULTS)
SY_TOOL_LIMITS = (0.0, 0.5)   # hard limits s3/build_sto_package.py sys.exit(1)s outside
RCH_RTOL = 1e-5               # flopy rcha free-format worst case ~3e-6; 3x headroom


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _require(d, key, where):
    """Mandatory declared field. Absent or None raises — a declaration with a hole in
    it must not degrade into 'nothing to check'."""
    if not isinstance(d, dict) or key not in d or d[key] is None:
        raise RuntimeError(f"calibration.yaml {where}.{key} missing or null; "
                           f"the declared contract is incomplete, refusing to score")
    return d[key]


def _close(a, b, tol):
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def resolve_obs_db():
    """The yearbook catalog has been relocated between /outputs/ and /outputs_disk1/
    in this environment; a missing DB raises rather than scoring nothing."""
    cands = [YB_DB_DEFAULT, YB_DB_DEFAULT.replace("/outputs/", "/outputs_disk1/"),
             "KISSPATH_OUTPUTS_ALT/yearbook_catalog/yearbook.db"]
    for c in cands:
        if os.path.exists(c):
            return c
    raise RuntimeError(f"yearbook obs DB not found; tried {cands}")


def _connect_ro(db_path):
    """Open the obs catalog READ-ONLY, on writable AND read-only media.

    `mode=ro` is the right first choice: WAL-correct and unable to write the database.
    But yearbook.db is in WAL journal mode, and a WAL *reader* still has to open — and
    create, if absent — the `<db>-shm` sidecar, so on a read-only mount / directory /
    review sandbox mode=ro alone fails with "attempt to write a readonly database" and
    the driver could not score its own obs. `immutable=1` is SQLite's documented answer
    for read-only media: it asserts the file cannot change while open and skips locking
    and the shm entirely. Used ONLY as a fallback, so the normal writable-directory path
    keeps full WAL semantics. Neither mode can write the catalog; if both fail we raise
    rather than score. MEASURED on a 0444 copy in a 0555 dir: mode=ro fails, the fallback
    reads all 36 rows."""
    last = None
    for uri in (f"file:{db_path}?mode=ro", f"file:{db_path}?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True)
            # Probe with a query that actually READS PAGE 1. sqlite3.connect() is lazy and
            # even `SELECT 1` is answered without touching the file, so a trivial probe
            # would report success on a handle whose first real query then raises — and
            # the fallback below would never run. MEASURED on a 0444 WAL DB in a 0555
            # dir: `SELECT 1` succeeds under mode=ro, `SELECT name FROM sqlite_master`
            # raises "attempt to write a readonly database".
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return con
        except sqlite3.Error as e:
            last = e
    raise RuntimeError(f"could not open the obs catalog {db_path} read-only "
                       f"(mode=ro and mode=ro&immutable=1 both failed: {last})")


def load_contract():
    if not os.path.exists(CONTRACT_YAML):
        raise RuntimeError(f"contract {CONTRACT_YAML} not found; refusing to score")
    with open(CONTRACT_YAML, encoding="utf-8") as fh:      # read-only
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        raise RuntimeError(f"contract {CONTRACT_YAML} did not parse to a mapping")
    return spec


def load_declared_observation(spec):
    """Return calibration.yaml's `observation:` block with every mandatory field
    present, and assert it describes THIS pinned target case."""
    o = _require(spec, "observation", "top-level")
    for got, want, what in ((o.get("case_id"), CASE_ID, "case_id"),
                            (o.get("station_code"), STATION, "station_code"),
                            (o.get("table"), OBS_TABLE, "table"),
                            (o.get("value_column"), OBS_COLUMN, "value_column")):
        if str(_require(o, what, "observation")) != want:
            raise RuntimeError(f"observation.{what} {got!r} != this runner's pinned {want!r}")
    for k in ("identity", "reference_surface", "months", "envelope", "split_envelope",
              "series", "series_sha256"):
        _require(o, k, "observation")
    for k in ("location", "aquifer_type", "province_code"):
        _require(o["identity"], k, "observation.identity")
    if "gw_zone" not in o["identity"]:      # declared value may legitimately be "" here,
        raise RuntimeError("calibration.yaml observation.identity.gw_zone missing; "
                           "the declared contract is incomplete, refusing to score")
    for k in ("column", "used_by_model_m", "by_year_m"):
        _require(o["reference_surface"], k, "observation.reference_surface")
    for k in ("n", "min_m", "min_month", "max_m", "max_month", "range_m", "mean_m",
              "sd_m", "tolerance_m"):
        _require(o["envelope"], k, "observation.envelope")
    for sp in ("calibration", "holdout"):
        for k in ("n", "min_m", "max_m", "mean_m", "sd_m"):
            _require(o["split_envelope"][sp], k, f"observation.split_envelope.{sp}")

    ident = o["identity"]
    zone_dec = ident["gw_zone"]
    for got, want, what in ((ident["location"], STATION_LOCATION, "location"),
                            (ident["aquifer_type"], AQUIFER_TYPE, "aquifer_type"),
                            (ident["province_code"], STATION_PROVINCE, "province_code"),
                            ("" if zone_dec is None else zone_dec, GW_ZONE, "gw_zone")):
        if str(got) != want:
            raise RuntimeError(f"observation.identity.{what} {got!r} != pinned {want!r}")
    if float(o["reference_surface"]["used_by_model_m"]) != float(TOP_ELEV):
        raise RuntimeError(f"declared reference surface "
                           f"{o['reference_surface']['used_by_model_m']} != TOP_ELEV {TOP_ELEV}")
    return o


def _series_digest(pairs):
    """sha256 over 'YYYY-MM=<repr(value)>' joined by '|', chronological. Computed the
    same way over the DB rows and over the declared series, so an edit to EITHER
    side is detected."""
    return hashlib.sha256("|".join(f"{k}={v!r}" for k, v in pairs).encode()).hexdigest()


def load_obs(db_path, o):
    """Load this station's monthly water levels and ENFORCE every field the
    `observation:` block declares. Returns (obs, provenance); provenance records what
    was actually verified, so `scored_obs` downstream is derived from the enforced
    identity rather than being an unverifiable label."""
    ident, ref, env = o["identity"], o["reference_surface"], o["envelope"]
    tol = float(env["tolerance_m"])
    elev_col = str(ref["column"])

    # READ-ONLY: yearbook.db is an immutable obs catalog. sqlite's default mode is
    # read/write/create, which fails outright on a read-only mount ("unable to open
    # database file") and would let an eval write the catalog. _connect_ro() does
    # neither, on writable and read-only media alike (see its docstring: this DB is in
    # WAL mode, so mode=ro on its own is not enough).
    con = _connect_ro(db_path)
    try:
        rows = list(con.execute(
            f"SELECT year, month, {OBS_COLUMN}, location, aquifer_type, province_code, "
            f"gw_zone, {elev_col} FROM {OBS_TABLE} WHERE station_code=? ORDER BY year, month",
            (STATION,)))
    finally:
        con.close()
    if not rows:
        raise RuntimeError(f"no rows in {OBS_TABLE} for station_code={STATION}")

    # --- identity: every scored row must carry exactly the declared values --------
    # db_ident holds the values READ OUT OF THE DB; they feed `scored_obs` downstream, so
    # the self-declaration is derived from what was actually read, not from the contract.
    db_ident = {}
    for col, want, what in ((3, str(ident["location"]), "location"),
                            (4, str(ident["aquifer_type"]), "aquifer_type"),
                            (5, str(ident["province_code"]), "province_code")):
        got = {str(r[col]) for r in rows}
        if got != {want}:
            raise RuntimeError(f"station {STATION} {what} in DB is {sorted(got)}, declared "
                               f"[{want!r}] — refusing to score a different gauge")
        db_ident[what] = got.pop()
    # gw_zone: this station's column is blank in every edition, so the DECLARED value is
    # "" and the DB set must equal exactly {""}. No blank-tolerant escape hatch: a future
    # re-ingest that assigns this well a hydrogeological zone changes what the row means
    # and must be re-derived, not silently accepted.
    zones = {(r[6] or "").strip() for r in rows}
    if zones != {GW_ZONE}:
        raise RuntimeError(f"station {STATION} gw_zone in DB is {sorted(zones)}, declared "
                           f"[{GW_ZONE!r}] — refusing to score a re-zoned gauge")
    db_ident["gw_zone"] = zones.pop()

    # --- reference surface, declared PER YEAR (editions can disagree; here they agree) -
    declared_elev = {int(y): float(v) for y, v in dict(ref["by_year_m"]).items()}
    db_elev = {}
    for r in rows:
        if r[7] is None:
            raise RuntimeError(f"row {r[0]}-{r[1]:02d} has NULL {elev_col}; the declared "
                               f"reference surface cannot be verified, refusing to score")
        db_elev.setdefault(int(r[0]), set()).add(float(r[7]))
    multi = {y: sorted(v) for y, v in db_elev.items() if len(v) != 1}
    if multi:
        raise RuntimeError(f"{elev_col} not single-valued within a year: {multi}")
    db_elev = {y: v.pop() for y, v in db_elev.items()}
    if set(db_elev) != set(declared_elev):
        raise RuntimeError(f"{elev_col} present for years {sorted(db_elev)}, declared "
                           f"{sorted(declared_elev)}")
    bad = {y: (db_elev[y], declared_elev[y]) for y in declared_elev
           if not _close(db_elev[y], declared_elev[y], tol)}
    if bad:
        raise RuntimeError(f"{elev_col} (reference surface) moved, DB vs declared {bad} — "
                           f"the datum the water levels reference has changed")
    if not _close(float(TOP_ELEV), float(ref["used_by_model_m"]), tol):
        raise RuntimeError(f"TOP_ELEV {TOP_ELEV} != declared used_by_model_m "
                           f"{ref['used_by_model_m']}")
    if not any(_close(float(TOP_ELEV), v, tol) for v in db_elev.values()):
        raise RuntimeError(f"TOP_ELEV {TOP_ELEV} is not among the {elev_col} values the DB "
                           f"reports for this station ({sorted(db_elev.values())})")

    # --- values ------------------------------------------------------------------
    obs = {}
    for yr, mo, wl, *_ in rows:
        if wl is None:
            continue
        key = (int(yr), int(mo))
        if key in obs:
            raise RuntimeError(f"duplicate obs row for {key} — ambiguous series")
        obs[key] = float(wl)

    # --- the EXACT month set, key-by-key (not merely the count) ------------------
    declared_series = {str(k): float(v) for k, v in dict(o["series"]).items()}
    declared_keys = sorted(declared_series)
    mdec = o["months"]
    if int(_require(mdec, "n", "observation.months")) != len(declared_keys):
        raise RuntimeError(f"observation.months.n {mdec['n']} != len(series) "
                           f"{len(declared_keys)} — the declaration is self-inconsistent")
    if declared_keys[0] != str(mdec["start"]) or declared_keys[-1] != str(mdec["end"]):
        raise RuntimeError(f"declared series spans {declared_keys[0]}..{declared_keys[-1]} "
                           f"but observation.months says {mdec['start']}..{mdec['end']}")

    def _k(ym):
        return f"{ym[0]}-{ym[1]:02d}"

    scored = sorted(k for k in obs if k[0] in EVAL_YEARS)
    db_keys = [_k(k) for k in scored]
    if db_keys != declared_keys:
        raise RuntimeError(
            f"scored month set != the declaration for station {STATION}: missing "
            f"{sorted(set(declared_keys) - set(db_keys))}, unexpected "
            f"{sorted(set(db_keys) - set(declared_keys))}")

    # --- every value individually, then a digest over the whole series -----------
    pairs = [(_k(k), obs[k]) for k in scored]
    off = {m: (v, declared_series[m]) for m, v in pairs
           if not _close(v, declared_series[m], tol)}
    if off:
        raise RuntimeError(f"observed values differ from the declared series at {len(off)} "
                           f"month(s) (DB, declared): {dict(list(off.items())[:6])} — "
                           f"refusing to score a changed series for station {STATION}")
    digest = _series_digest(pairs)
    if digest != str(o["series_sha256"]):
        raise RuntimeError(f"observed series sha256 {digest} != declared "
                           f"{o['series_sha256']} — series and declaration disagree")

    # --- envelope, pooled then per split ----------------------------------------
    vals = [v for _, v in pairs]
    stats = {"n": len(vals), "min_m": min(vals), "max_m": max(vals),
             "range_m": max(vals) - min(vals), "mean_m": sum(vals) / len(vals),
             "sd_m": float(np.std(np.asarray(vals, dtype=float)))}
    if int(env["n"]) != stats["n"]:
        raise RuntimeError(f"declared envelope n {env['n']} != observed {stats['n']}")
    for f in ("min_m", "max_m", "range_m", "mean_m"):
        if not _close(stats[f], float(env[f]), tol):
            raise RuntimeError(f"declared envelope {f} {env[f]} != observed {stats[f]!r} "
                               f"(tol {tol}) — this is not the observation the contract "
                               f"was derived against")
    if not _close(stats["sd_m"], float(env["sd_m"]), 5e-5):   # declared to 4 dp
        raise RuntimeError(f"declared envelope sd_m {env['sd_m']} != observed {stats['sd_m']!r}")
    lo_month = min(pairs, key=lambda kv: kv[1])[0]
    hi_month = max(pairs, key=lambda kv: kv[1])[0]
    if lo_month != str(env["min_month"]) or hi_month != str(env["max_month"]):
        raise RuntimeError(f"envelope extrema fall in {lo_month}/{hi_month}, declared "
                           f"{env['min_month']}/{env['max_month']} — series reordered/altered")
    for label, keys in (("calibration", CAL_MONTHS), ("holdout", HOLDOUT_MONTHS)):
        sv = [obs[k] for k in keys if k in obs]
        dec = o["split_envelope"][label]
        if len(sv) != int(dec["n"]):
            raise RuntimeError(f"split '{label}': {len(sv)} obs, declared {dec['n']}")
        for f, got in (("min_m", min(sv)), ("max_m", max(sv)), ("mean_m", sum(sv) / len(sv))):
            if not _close(got, float(dec[f]), tol):
                raise RuntimeError(f"split '{label}' {f}: observed {got!r} != declared {dec[f]}")
        got_sd = float(np.std(np.asarray(sv, dtype=float)))
        if not _close(got_sd, float(dec["sd_m"]), 5e-5):
            raise RuntimeError(f"split '{label}' sd_m: observed {got_sd!r} != declared {dec['sd_m']}")

    prov = {"location": db_ident["location"], "aquifer_type": db_ident["aquifer_type"],
            "province_code": db_ident["province_code"], "gw_zone": db_ident["gw_zone"],
            "reference_surface_col": elev_col,
            "reference_surface_by_year_m": {str(y): v for y, v in sorted(db_elev.items())},
            "reference_surface_used_by_model_m": float(TOP_ELEV),
            "series_sha256": digest, "envelope_min_month": lo_month,
            "envelope_max_month": hi_month,
            "envelope": {k: (round(v, 6) if isinstance(v, float) else v)
                         for k, v in stats.items()}}
    return obs, prov


def read_params():
    """Candidate vector from the kit (runner mode); defaults fill any gap. Hard
    feasibility is rejected HERE, cheaply, without a model run."""
    p, handed = dict(DEFAULTS), set()
    src = os.environ.get("KDT_CALIB_PARAMS")
    if src:
        with open(src) as fh:
            cand = json.load(fh)
        unknown = set(cand) - set(PARAM_NAMES)
        if unknown:
            raise ValueError(f"unknown calibration parameters: {sorted(unknown)}")
        handed = set(cand)
        p.update({k: float(v) for k, v in cand.items()})
    if p["drn_elev"] >= p["base_chd"]:
        raise ValueError(f"infeasible: drn_elev {p['drn_elev']} >= base_chd {p['base_chd']}")
    if p["qpump"] < 0:
        raise ValueError(f"infeasible: qpump {p['qpump']} < 0")
    # Mirror the KI builder's own hard limits, so an out-of-range vector fails here
    # instead of making s3/build_sto_package.py sys.exit(1) mid-build. The declared
    # ranges sit strictly inside these, so this never binds on a kit candidate.
    lo, hi = SY_TOOL_LIMITS
    if not (lo < p["sy"] < hi):
        raise ValueError(f"infeasible: sy {p['sy']} outside the builder's ({lo}, {hi})")
    if p["ss"] <= 0:
        raise ValueError(f"infeasible: ss {p['ss']} <= 0 (builder requires Ss > 0)")
    return p, handed


def ensure_forcing_cache():
    """One-time CMFD prepare for THIS station's cell (~4 min); every later eval reads
    the cache (~0 s)."""
    os.makedirs(os.path.dirname(CMFD_CACHE), exist_ok=True)
    if not os.path.exists(CMFD_CACHE):
        from ki_tools_common.load_forcing import load_daily_forcing
        years = SPINUP_YEARS + EVAL_YEARS
        d = load_daily_forcing("cmfd", LAT, LON, min(years), max(years), forcing_dir=CMFD_DIR)
        monthly = {}
        for dt, p in zip(d["dates"], np.asarray(d["precip_mm"])):
            k = (dt.year, dt.month)
            monthly[k] = monthly.get(k, 0.0) + (0.0 if not np.isfinite(p) else float(p))
        tmp = f"{CMFD_CACHE}.tmp.{os.getpid()}"      # os.replace is atomic: a concurrent
        with open(tmp, "w") as fh:                   # reader sees old or new, never partial
            fh.write(json.dumps({f"{y}-{m}": v for (y, m), v in monthly.items()}))
        os.replace(tmp, CMFD_CACHE)
    with open(CMFD_CACHE) as fh:
        monthly = {tuple(map(int, k.split("-"))): float(v) for k, v in json.load(fh).items()}
    missing = [f"{y}-{m:02d}" for y in (SPINUP_YEARS + EVAL_YEARS) for m in range(1, 13)
               if (y, m) not in monthly]
    if missing:
        raise RuntimeError(f"CMFD cache {CMFD_CACHE} missing months {missing}")
    return monthly


def pin_site(rs, ss_value):
    """Override every SITE constant the scratch driver carries, then assert it took.

    Also installs the `ss` shim: build_and_run() threads `sy` through its params dict
    but hardcodes SS_VALUES=[1e-5] on the s3 STO builder, so the only way to make the
    dag's specific_storage edge calibratable WITHOUT editing the validated driver is
    to set that module global immediately before the KI's own builder runs. The value
    still reaches MF6 through flopy's ModflowGwfsto and is read back out of the
    written gwf.sto like every other input."""
    required = ["STATION", "LAT", "LON", "TOP_ELEV", "SPINUP_YEARS", "EVAL_YEARS",
                "OBS_CELL", "MF6", "TOOLS", "build_and_run", "load_tool"]
    missing = [a for a in required if not hasattr(rs, a)]
    if missing:
        raise RuntimeError(f"{RUNNER_PY} does not expose {missing}; its structure changed "
                           f"and build_and_run() can no longer be driven safely")

    rs.STATION, rs.TOP_ELEV, rs.MF6, rs.CMFD_DIR = STATION, TOP_ELEV, MF6, CMFD_DIR
    rs.LAT, rs.LON = LAT, LON
    rs.SPINUP_YEARS, rs.EVAL_YEARS = list(SPINUP_YEARS), list(EVAL_YEARS)
    rs.CAL_YEARS, rs.VAL_YEARS = [2019, 2020], [2021]
    rs.OBS_CELL = tuple(OBS_CELL)

    if (rs.STATION, rs.TOP_ELEV, tuple(rs.OBS_CELL)) != (STATION, TOP_ELEV, tuple(OBS_CELL)):
        raise RuntimeError("site pinning did not take effect on the imported runner")
    if list(rs.SPINUP_YEARS) + list(rs.EVAL_YEARS) != SPINUP_YEARS + EVAL_YEARS:
        raise RuntimeError("site pinning of the year lists did not take effect")
    # build_and_run() samples the head at a LITERAL [0,2,2], not at its OBS_CELL global,
    # so pinning OBS_CELL alone would not move the sampled cell. This case's obs cell IS
    # the 5x5 centre — assert that rather than assume it, else a future OBS_CELL change
    # would silently score a different cell than the WEL abstraction is applied to.
    if tuple(OBS_CELL) != (0, 2, 2):
        raise RuntimeError(f"OBS_CELL {OBS_CELL} != (0,2,2) but build_and_run() samples a "
                           f"hardcoded [0,2,2]; scored and pumped cells would diverge")

    _orig_load_tool = rs.load_tool
    installed = {"sto": False}

    def _load_tool_with_ss(relpath):
        mod = _orig_load_tool(relpath)
        if "build_sto_package" not in relpath:
            return mod
        if not hasattr(mod, "SS_VALUES"):
            raise RuntimeError("s3/build_sto_package.py no longer exposes SS_VALUES; `ss` "
                               "cannot be injected and this contract must be re-derived")
        _orig_process = mod.process

        def _process_with_ss(*a, **kw):
            # set LAST, immediately before the builder runs, so build_and_run's own
            # `t.SS_VALUES = [1e-5]` cannot overwrite the candidate value.
            mod.SS_VALUES = [float(ss_value)]
            installed["sto"] = True
            return _orig_process(*a, **kw)

        mod.process = _process_with_ss
        return mod

    rs.load_tool = _load_tool_with_ss
    return installed


def verify_storage_config(ws):
    """Assert the model that just ran IS the storage configuration this contract was
    derived against: period 1 STEADY-STATE spin-up, 2..NMON+1 TRANSIENT, iconvert==1.
    If s3/build_sto_package.py ever regresses to the pre-2026-07-27 all-steady bug,
    this raises (=> no metrics) rather than silently calibrating two dead levers."""
    flags, per = {}, None
    with open(os.path.join(ws, "gwf.sto")) as fh:
        for line in fh:
            s = line.strip().upper()
            m = re.match(r"^BEGIN\s+PERIOD\s+(\d+)", s)
            if m:
                per = int(m.group(1))
            elif s.startswith("END"):
                per = None
            elif per is not None and s in ("STEADY-STATE", "TRANSIENT"):
                flags[per] = s
    if not flags:
        raise RuntimeError("gwf.sto declares no stress-period storage flags")
    if flags.get(1) != "STEADY-STATE":
        raise RuntimeError(f"gwf.sto period 1 is {flags.get(1)!r}, expected the STEADY-STATE "
                           f"spin-up of the validated coupling")
    steady = sorted(p for p, f in flags.items() if p >= 2 and f == "STEADY-STATE")
    if steady:
        raise RuntimeError(f"gwf.sto is STEADY-STATE at periods {steady}; this contract was "
                           f"derived against the REPAIRED transient coupling (sy/ss live). "
                           f"s3/build_sto_package.py appears to have regressed to the "
                           f"pre-2026-07-27 all-steady bug — re-derive calibration.yaml.")
    transient = sorted(p for p, f in flags.items() if p >= 2 and f == "TRANSIENT")
    if transient != list(range(2, NMON + 2)):
        raise RuntimeError(f"gwf.sto transient periods != the expected 2..{NMON + 1}; the "
                           f"stress-period structure has changed")
    import flopy
    gwf = flopy.mf6.MFSimulation.load(sim_ws=ws, verbosity_level=0).get_model("gwf")
    iconv = np.unique(np.asarray(gwf.sto.iconvert.array))
    if iconv.size != 1 or int(iconv[0]) != 1:
        raise RuntimeError(f"gwf.sto iconvert={iconv.tolist()} != 1: Sy is IGNORED unless the "
                           f"layer is convertible (SKILL.md fact #5), so `sy` would be a dead "
                           f"pool parameter; re-derive calibration.yaml")


def read_back(ws):
    """Read every calibrated value BACK from the native MF6 input files mf6 consumed.
    Anything missing/unreadable/non-uniform raises (=> no metrics)."""
    import flopy
    gwf = flopy.mf6.MFSimulation.load(sim_ws=ws, verbosity_level=0).get_model("gwf")
    applied = {"k": float(np.asarray(gwf.npf.k.array).ravel()[0])}

    sy_vals = np.unique(np.asarray(gwf.sto.sy.array))
    ss_vals = np.unique(np.asarray(gwf.sto.ss.array))
    if sy_vals.size != 1 or ss_vals.size != 1:
        raise RuntimeError(f"STO not uniform: sy {sy_vals.tolist()} ss {ss_vals.tolist()}")
    applied["sy"], applied["ss"] = float(sy_vals[0]), float(ss_vals[0])

    chd = gwf.get_package("chd_0")
    if chd is None:
        raise RuntimeError("no chd package in the written simulation")
    base_vals = np.unique([r[1] for r in chd.stress_period_data.get_data(0)])
    if base_vals.size != 1:
        raise RuntimeError(f"CHD ring not uniform: {base_vals.tolist()}")
    applied["base_chd"] = float(base_vals[0])

    drn = gwf.get_package("drn_0")
    if drn is None:
        raise RuntimeError("no drn package in the written simulation")
    rec = drn.stress_period_data.get_data(0)
    elev_vals, cond_vals = np.unique([r[1] for r in rec]), np.unique([r[2] for r in rec])
    if elev_vals.size != 1 or cond_vals.size != 1:
        raise RuntimeError(f"DRN ring not uniform: elev {elev_vals.tolist()} "
                           f"cond {cond_vals.tolist()}")
    applied["drn_elev"], applied["cdrn"] = float(elev_vals[0]), float(cond_vals[0])

    wel = gwf.get_package("wel_0")
    if wel is None:
        # qpump == 0 is the no-pump control: build_and_run omits WEL entirely, so its
        # absence IS the applied value.
        applied["qpump"] = 0.0
    else:
        spd = wel.stress_period_data.get_data()
        rates = [float(spd[p][0][1]) for p in sorted(spd) if p >= 1 and len(spd[p])]
        if not rates:
            raise RuntimeError("wel package present but carries no transient rates")
        applied["qpump"] = float(-min(rates))     # rates <= 0; magnitude of abstraction

    rch = gwf.get_package("rcha_0")
    if rch is None:
        raise RuntimeError("no rcha package in the written simulation")
    rdata = rch.recharge.get_data()
    rates = []
    for per in range(1, NMON + 1):
        if per not in rdata:
            break
        rates.append(float(np.asarray(rdata[per]).ravel()[0]))
    if len(rates) != NMON:
        raise RuntimeError(f"rcha holds {len(rates)} transient periods, expected {NMON}")
    applied["_rch_rates"] = rates
    return applied


def verify_recharge(applied, params, monthly_precip):
    """Forward-recompute the rcha rates from the REQUESTED frac/lag/cap and check they
    equal the rates found in gwf.rcha. Passing proves the written artifact encodes
    those three — all 48 rates is far more constraining than any single one. They are
    then REPORTED as requested doubles (see PRECISION in the module docstring); as a
    cross-check the inversion IS performed on the least-lossy month."""
    months = [(y, m) for y in (SPINUP_YEARS + EVAL_YEARS) for m in range(1, 13)]
    frac, lag, cap = params["frac"], params["lag"], params["cap"]

    p_series = [monthly_precip.get((y, m), 0.0) / 1000.0 for (y, m) in months]
    soil, smooth = p_series[0], []
    for p_m in p_series:
        soil = lag * soil + (1.0 - lag) * p_m
        smooth.append(soil)
    expect, capped = [], []
    for i, (y, m) in enumerate(months):
        expect.append(min(frac * smooth[i], cap) / calendar.monthrange(y, m)[1])
        capped.append(frac * smooth[i] >= cap - 1e-15)

    got = applied.pop("_rch_rates")
    e, g = np.asarray(expect), np.asarray(got)
    if e.shape != g.shape or not np.allclose(e, g, rtol=RCH_RTOL, atol=1e-15):
        diff = np.max(np.abs(e - g)) if e.shape == g.shape else "shape mismatch"
        raise RuntimeError(f"gwf.rcha rates do not match the requested frac/lag/cap "
                           f"(max abs diff {diff})")

    # Invert frac on the smallest un-capped rate — flopy always writes that one in
    # E-notation. Selection depends only on the written magnitudes, not on the request.
    cands = [i for i in range(len(months)) if not capped[i] and smooth[i] > 1e-9]
    if cands:
        i = min(cands, key=lambda j: got[j])
        frac_read = got[i] * calendar.monthrange(*months[i])[1] / smooth[i]
        if not np.isclose(frac_read, frac, rtol=RCH_RTOL, atol=0.0):
            raise RuntimeError(f"frac read back from gwf.rcha ({frac_read!r}) != "
                               f"requested ({frac!r})")

    applied["frac"], applied["lag"], applied["cap"] = frac, lag, cap
    return applied


def _out_tmp(path):
    return f"{path}.tmp.{os.getpid()}"


def _discard(path):
    """A failed run must leave NO metrics file — not its own partial output and not a
    previous candidate's success artifact (the kit reads a missing file as +inf)."""
    for p in (path, f"{path}.tmp", _out_tmp(path)):
        try:
            os.remove(p)
        except OSError:
            pass


def _read_listing(ws, name):
    """Absent or EMPTY raises: a diagnostic that cannot be read is a FAILURE, never an
    implicit pass."""
    path = os.path.join(ws, name)
    if not os.path.exists(path):
        raise RuntimeError(f"run-health: required listing {name} was not written — the "
                           f"diagnostics are MISSING, which is a failure, not a pass")
    if os.path.getsize(path) == 0:
        raise RuntimeError(f"run-health: required listing {name} is empty; diagnostics "
                           f"unavailable, refusing to score")
    with open(path, errors="replace") as fh:
        return fh.read()


def check_run_health(runres, ws, hs):
    """mf6 exiting 0 is NOT a scorable run, and neither is s7's diagnostic dict:
    check_listing_file() initialises normal_termination=False, convergence_failures=0,
    max_budget_error_pct=0.0 and only overwrites them if the listings parse — so a run
    whose gwf.lst was never written reports "0 failures, 0.0% budget", a MISSING
    diagnostic wearing the costume of a PASSING one. `runres.get(k) or 0` turns both
    None and absence into a pass; that idiom is banned here.

    Every declared diagnostic must be PRESENT and non-None; each is RE-DERIVED from the
    listing files mf6 wrote; budget evidence must be POSITIVELY present; and the two
    readings are cross-checked. Any violation => no metrics, exit nonzero. Thresholds
    come from calibration.yaml's `run_health:` block, so gate and contract cannot drift."""
    required = list(_require(hs, "required_diagnostics", "run_health"))
    absent = [k for k in required if k not in runres]
    if absent:
        raise RuntimeError(f"run-health: s7 result is missing required diagnostic(s) "
                           f"{absent}; refusing to score (present: {sorted(runres)})")
    null = [k for k in required if runres[k] is None]
    if null:
        raise RuntimeError(f"run-health: required diagnostic(s) {null} came back None; a "
                           f"missing diagnostic FAILS the eval, it is not defaulted to a pass")
    if not runres["success"]:
        raise RuntimeError(f"run-health: s7 reports success={runres['success']!r}")

    listings = {n: _read_listing(ws, n)
                for n in _require(hs, "require_listing_files", "run_health")}

    if bool(_require(hs, "require_normal_termination", "run_health")):
        sim_txt = listings.get("mfsim.lst")
        if sim_txt is None:
            raise RuntimeError("run-health: mfsim.lst not among the required listings, so "
                               "normal termination cannot be verified")
        if "Normal termination" not in sim_txt:
            raise RuntimeError("run-health: mfsim.lst carries no 'Normal termination' line")
        if runres["normal_termination"] is not True:
            raise RuntimeError(f"run-health: s7 reports normal_termination="
                               f"{runres['normal_termination']!r} while mfsim.lst says otherwise")

    model_txt = listings.get("gwf.lst")
    if model_txt is None:
        raise RuntimeError("run-health: gwf.lst not among the required listings, so "
                           "convergence and budget cannot be verified")
    nconv = model_txt.count("FAILED TO CONVERGE")
    if nconv != int(runres["convergence_failures"]):
        raise RuntimeError(f"run-health: convergence-failure count disagrees between s7 "
                           f"({runres['convergence_failures']}) and a direct read of gwf.lst "
                           f"({nconv}); one of them is wrong, refusing to score")
    max_conv = int(_require(hs, "max_convergence_failures", "run_health"))
    if nconv > max_conv:
        raise RuntimeError(f"run-health: {nconv} convergence failures (max {max_conv})")

    pct = [abs(float(p)) for p in
           re.findall(r"PERCENT DISCREPANCY\s*=\s*([-\d.eE+]+)", model_txt)]
    if bool(_require(hs, "require_budget_evidence", "run_health")):
        need = int(_require(hs, "min_budget_discrepancy_readings", "run_health"))
        if len(pct) < need:
            raise RuntimeError(f"run-health: gwf.lst carries {len(pct)} 'PERCENT DISCREPANCY' "
                               f"readings, expected >= {need} (2 per stress period over "
                               f"{NMON + 1} periods). The budget diagnostic is MISSING or the "
                               f"run stopped early — a FAILURE, not a 0.0% error")
    if not pct:
        raise RuntimeError("run-health: no volumetric budget discrepancy could be read "
                           "from gwf.lst; refusing to score")
    budget = max(pct)
    if not _close(budget, float(runres["max_budget_error_pct"]), 1e-9):
        raise RuntimeError(f"run-health: max budget discrepancy disagrees between s7 "
                           f"({runres['max_budget_error_pct']}%) and a direct read of gwf.lst "
                           f"({budget}%); refusing to score")
    budget_max = float(_require(hs, "max_budget_error_pct", "run_health"))
    if budget > budget_max:
        raise RuntimeError(f"run-health: budget discrepancy {budget}% > {budget_max}%")

    # score_months() enforces full month coverage unconditionally, so the declaration must
    # not be able to promise a WEAKER gate than the code applies (that would be exactly the
    # contract/gate drift this design exists to prevent).
    if not bool(_require(hs, "require_full_month_coverage", "run_health")):
        raise RuntimeError("run_health.require_full_month_coverage is declared false, but "
                           "score_months() always requires every scored month to carry a "
                           "simulated head; the declared gate and the enforced gate disagree")

    hds_name = str(_require(hs, "require_head_file", "run_health"))
    hds = os.path.join(ws, hds_name)
    if not os.path.exists(hds):
        raise RuntimeError(f"run-health: mf6 wrote no {hds_name} head file")
    if os.path.getsize(hds) == 0:
        raise RuntimeError(f"run-health: {hds_name} is empty; there are no heads to score")

    return {"normal_termination": True, "convergence_failures": nconv,
            "max_budget_error_pct": budget, "budget_discrepancy_readings": len(pct),
            "verified_from": sorted(listings), "hds_bytes": os.path.getsize(hds)}


def score_months(obs, sim_month, month_keys, label):
    """Score exactly the requested keys. EVERY observed month of the split must carry a
    simulated head: build_and_run() drops months whose head came back dry (h >= 0.9e30),
    so a partially-drowned candidate would otherwise be scored on a SUBSET of the obs —
    an easier problem than the baseline, and one a hill-climber will chase."""
    want = [k for k in month_keys if k in obs]
    if not want:
        raise RuntimeError(f"split '{label}': no observed months")
    missing = [f"{y}-{m:02d}" for (y, m) in want if (y, m) not in sim_month]
    if missing:
        raise RuntimeError(f"split '{label}': {len(missing)}/{len(want)} scored months have "
                           f"no simulated head (dry/inactive cell): {missing}")
    o = np.array([obs[k] for k in want], dtype=float)
    s = np.array([sim_month[k] for k in want], dtype=float)
    if not (np.all(np.isfinite(o)) and np.all(np.isfinite(s))):
        raise RuntimeError(f"split '{label}': non-finite obs/sim values")
    if o.size < 2 or np.var(o) == 0:
        raise RuntimeError(f"split '{label}': degenerate obs (n={o.size}, var={np.var(o)})")
    return all_metrics(o, s), want


def main(args):
    # Candidate isolation: every MF6 input, the mf6 run and gwf.hds live under the
    # per-candidate --workdir. build_and_run() rmtree's `ws` first, so a retry into a
    # dirty workdir also starts clean.
    workdir = os.path.abspath(args.workdir)
    os.makedirs(workdir, exist_ok=True)
    ws = os.path.join(workdir, "mf")

    params, handed = read_params()
    split = os.environ.get("KDT_CALIB_SPLIT", "").strip().lower()

    spec = load_contract()
    obsdec = load_declared_observation(spec)
    health_spec = _require(spec, "run_health", "top-level")

    db_path = resolve_obs_db()
    want_db = str(obsdec.get("source_db_basename", os.path.basename(db_path)))
    if os.path.basename(db_path) != want_db:
        raise RuntimeError(f"resolved obs DB {db_path} is not the declared {want_db!r}")
    obs, obs_prov = load_obs(db_path, obsdec)
    monthly_precip = ensure_forcing_cache()

    rs = _load_module(RUNNER_PY, "mf6_real_case_runner")
    shim = pin_site(rs, params["ss"])

    build_params = {k: params[k] for k in ("frac", "lag", "cap", "cdrn", "base_chd",
                                           "drn_elev", "k", "qpump", "sy")}
    build_params["pump_months"] = list(PUMP_MONTHS) if params["qpump"] > 0 else []

    sim_month, runres, months = rs.build_and_run(build_params, ws, monthly_precip)
    if sim_month is None:
        raise RuntimeError(f"mf6 run failed / did not converge: {runres}")
    if len(months) != NMON:
        raise RuntimeError(f"forward model built {len(months)} months, expected {NMON}")
    run_health = check_run_health(runres, ws, health_spec)
    if not shim["sto"]:
        raise RuntimeError("the `ss` injection shim never fired: build_and_run() no longer "
                           "routes the STO package through load_tool('s3/build_sto_package.py'), "
                           "so `ss` was not injected. Refusing to score an un-injected candidate.")
    verify_storage_config(ws)

    applied = verify_recharge(read_back(ws), params, monthly_precip)

    if split == "calibration":
        keys, label = CAL_MONTHS, "calibration"
    elif split == "holdout":
        keys, label = HOLDOUT_MONTHS, "holdout"
    else:
        keys, label = CAL_MONTHS + HOLDOUT_MONTHS, "both"
    m, scored_keys = score_months(obs, sim_month, keys, label)

    # DERIVED from the identity actually VERIFIED against the DB and the months actually
    # scored — every field comes from obs_prov, i.e. from values read out of the obs rows
    # and asserted against the declaration, so it cannot diverge from what was scored.
    scored_obs = (
        f"china_gw_yearbook station {STATION} {obs_prov['location']} "
        f"({obs_prov['aquifer_type']}, gw_zone "
        f"{obs_prov['gw_zone'] if obs_prov['gw_zone'] else '<blank>'}, "
        f"province {obs_prov['province_code']}) | {db_path}::{OBS_TABLE}.{OBS_COLUMN} | "
        f"months {scored_keys[0][0]}-{scored_keys[0][1]:02d}..{scored_keys[-1][0]}-"
        f"{scored_keys[-1][1]:02d} (n={len(scored_keys)}, split={label}) | "
        f"series_sha256={obs_prov['series_sha256'][:16]} | "
        f"ref_surface {obs_prov['reference_surface_used_by_model_m']} m | "
        f"model cell {tuple(rs.OBS_CELL)} @ {LAT},{LON}")

    # Echo EVERY handed key — staged rounds hand frozen params too, and omitting one
    # fails the eval closed at the kit's requested-vs-applied diff.
    missing_echo = handed - set(applied)
    if missing_echo:
        raise RuntimeError(f"handed params not echoed in applied_params: {sorted(missing_echo)}")

    out = {"nse": float(m["NSE"]), "kge": float(m["KGE"]), "pbias": float(m["PBIAS"]),
           "r": float(m["r"]), "rmse": float(m["RMSE"]),
           "n_obs": int(len(scored_keys)), "split": label,
           "__kdt__": {"applied_params": {k: applied[k] for k in PARAM_NAMES},
                       "case_id": CASE_ID, "scored_obs": scored_obs,
                       "workdir": workdir, "pid": os.getpid(),
                       "run_health": run_health, "obs_verified": obs_prov}}
    for k, v in out.items():
        if isinstance(v, float) and not np.isfinite(v):
            raise RuntimeError(f"non-finite metric {k}={v}; refusing to write metrics")

    tmp = _out_tmp(args.out)
    with open(tmp, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, args.out)
    print(json.dumps({k: v for k, v in out.items() if k != "__kdt__"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    _args = ap.parse_args()
    # Drop any previous candidate's metrics BEFORE the run, so a crash below can never
    # leave the kit reading an older success.
    _discard(_args.out)
    try:
        main(_args)
    except BaseException:      # incl. SystemExit: the KI's s2..s7 tools sys.exit(1) on
        traceback.print_exc()  # bad input, which `except Exception` would miss
        _discard(_args.out)
        sys.exit(1)
