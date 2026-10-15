#!/usr/bin/env python
"""SWAT+ calibration driver for 淮滨 Huaibin — System 1 W4 distributed arm.

THIN WRAPPER, by design: it imports the KI's commissioned `calib_run.py` and re-pins the case
constants before calling its main(). The parameter contract, injection, read-back verification,
execution and scoring code stay the KI's — only the case (gauge, deck, guard box, splits) changes.
Same pattern as the HBV KI's calib_run_huaibin.py (W4, 2026-08-29).

Two case-specific overrides beyond constants:
  1. SPLITS are YEAR SETS, not contiguous ranges — System 1's holdout-v2 split (declared in
     HOLDOUT_V2_DECLARATION.md and used by all 14 lumped structures) trains on
     {1982,1984,2002,2003,2007,2010} and holds out {1991,2005,2008,2017,2018}. The KI's
     pair_and_window() assumes a date range, so it is replaced with a year-set version.
  2. The deck-identity guard is re-pinned to the Huaibin delineation (61 channels, its own bbox);
     a deck outside that box must never be scored against the Huaibin gauge.

usage (identical to the KI driver): calib_run_huaibin.py --workdir <dir> --out <metrics.json>
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calib_run as base   # noqa: E402  the KI's commissioned driver

# ===========================================================================
# PIN — the target case. Module constants, never environment-derived.
# ===========================================================================
base.CASE_ID = "SITE:huaibin"
base.GAUGE_ID = "huaibin_50229350"
base.GAUGE_NAME = "淮滨"
base.OBS_STCD = "50229350"
base.OBS_FILE = Path("KISSPATH_DATA/china_water_level/淮河txt/淮滨.txt")
base.OBS_SOURCE = "china_gaugeflux"

# The CLCD deck (2026-09-02): 61 channels, 139 HRUs, 61 CMFD stations 1:1 with routing units,
# real channel topology. Its untuned run is the contract's reference_run.
base.CASE_ROOT = Path("KISSPATH_OUTPUTS/swatplus_huaibin")
base.BASE_DECK = base.CASE_ROOT / "TxtInOut_clcd"
base.PRISTINE_ROOT = base.CASE_ROOT / "_calib_pristine_clcd"
base.PRISTINE_DECK = base.PRISTINE_ROOT / "TxtInOut_clcd"

# Deck-identity guard: the Huaibin delineation's channel.con box is
# lat 31.630..32.592, lon 113.419..115.377 (measured 2026-09-02); margin added.
base.BASIN_BBOX = (31.4, 32.9, 113.2, 115.6)      # lat_min, lat_max, lon_min, lon_max
base.EXPECT_N_CHANNELS = 61

# Scoring: time.sim 1979-2018 with nyskip 3 => printed record starts 1982.
YEARS = {
    "calibration": {1982, 1984, 2002, 2003, 2007, 2010},          # holdout-v2 train
    "holdout":     {1991, 2005, 2008, 2017, 2018},                # holdout-v2 held-out
    "full":        set(range(1982, 2019)),
}
base.SPLITS = {k: ("year-set", sorted(v)) for k, v in YEARS.items()}   # kept for provenance only
base.MIN_PAIRED_DAYS = 300


def pair_and_window(obs_d, obs_q, sim_d, sim_q, split: str):
    """Year-set replacement for the KI's contiguous-range windowing.

    Mirrors the KI's pair_and_window exactly — same intersect-on-common-dates logic, same
    finite filter, same (dates, obs, sim) return triple that main() unpacks — but selects the
    split's YEARS instead of a [lo, hi] date range. Dates are numpy datetime64, so the year is
    taken by casting to datetime64[Y], never by attribute access.
    """
    import numpy as np
    if split not in YEARS:
        base.fail(2, f"unknown split {split!r}; expected one of {sorted(YEARS)}")
    keep = YEARS[split]
    common = np.intersect1d(obs_d, sim_d)
    if common.size:
        years = common.astype("datetime64[Y]").astype(int) + 1970
        common = common[np.isin(years, sorted(keep))]
    if common.size == 0:
        base.fail(3, f"no overlapping days between obs and sim in split {split} "
                     f"(years {sorted(keep)})")
    oi = {d: i for i, d in enumerate(obs_d)}
    si = {d: i for i, d in enumerate(sim_d)}
    o = np.array([obs_q[oi[d]] for d in common])
    s = np.array([sim_q[si[d]] for d in common])
    good = np.isfinite(o) & np.isfinite(s)
    if int(good.sum()) < base.MIN_PAIRED_DAYS:
        base.fail(3, f"only {int(good.sum())} paired days in split {split} "
                     f"(need {base.MIN_PAIRED_DAYS}); years {sorted(keep)}")
    return common[good], o[good], s[good]


base.pair_and_window = pair_and_window


def verify_weather_wiring(deck):
    """Every station referenced by any .con file must exist in weather-sta.cli.

    codex HIGH (2026-09-02): the KI's deck-identity guard checks the channel bbox and channel
    count only, so a deck whose `wst` columns point at stations that do not exist — the exact
    state both Huaibin decks were in after a partial station remap (channel.con and aquifer.con
    were missed) — passes the guard and runs anyway. Checked here, fail closed, every eval.
    """
    from pathlib import Path as _P
    deck = _P(deck)
    cli = deck / "weather-sta.cli"
    if not cli.exists():
        base.fail(2, "weather-sta.cli missing from the deck")
    defined = {l.split()[0] for l in cli.read_text().splitlines()[2:] if l.split()}
    bad = {}
    for fn in ("rout_unit.con", "hru.con", "channel.con", "aquifer.con", "reservoir.con"):
        p = deck / fn
        if not p.exists():
            continue
        for ln in p.read_text().splitlines()[2:]:
            t = ln.split()
            if len(t) >= 10 and t[8] not in defined and t[8] not in ("0", "null"):
                bad.setdefault(fn, set()).add(t[8])
    if bad:
        base.fail(2, "deck references undefined weather stations: "
                     + "; ".join(f"{k}: {sorted(v)[:5]}" for k, v in bad.items()))


_base_verify = base.verify_deck_is_target_case


def verify_deck_is_target_case(deck):
    """KI identity guard (bbox + channel count) PLUS the weather-wiring check."""
    info = _base_verify(deck)
    verify_weather_wiring(deck)
    return info


base.verify_deck_is_target_case = verify_deck_is_target_case

if __name__ == "__main__":
    base.main()
