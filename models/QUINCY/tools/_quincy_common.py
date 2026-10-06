"""Shared helpers for the QUINCY real-engine tools (not a public tool).

Facts used here were read from the engine source
(KISSPATH_HOME/engine_builds_20261006/QUINCY/src/src, tag qs-2026.04-public):

* the engine calendar is 365 days (mo_jsb_math_constants: one_year = 365), and
  climate.dat is read LINE BY LINE with no date matching
  (mo_qs_atmland_forcing.f90 read_or_calculate_forcing) -> Feb 29 must be dropped;
* the solar clock is LOCAL solar time (mo_qs_atmland_constants: angle_at_GMT = .FALSE.);
* the engine reports success with the text "End QUINCY model" and writes errors to
  quincy_standalone.err (mo_exception finish()).
"""
from __future__ import annotations

import datetime as dt
import math
import os
import re
from pathlib import Path

KI_DIR = Path(__file__).resolve().parent.parent
# QUINCY_ENGINE_ROOT: the engine build folder (binary, src/data, src/src, run_builtin_* references)
ENGINE_ROOT = Path(os.environ.get("QUINCY_ENGINE_ROOT", "KISSPATH_HOME/engine_builds_20261006/QUINCY")).expanduser().absolute()
ENGINE_BIN = Path(os.environ.get("QUINCY_BIN", ENGINE_ROOT / "src/x86_64-gfortran/bin/qs.bin")).expanduser().absolute()
ENGINE_DATA = ENGINE_ROOT / "src/data"
LCTLIB = ENGINE_DATA / "lctlib_quincy_nlct14.def"
TEMPLATE_NML = KI_DIR / "templates" / "qs.namelist.template"

# QUINCY PFT numbers (lctlib_quincy_nlct14.def header)
PFT_IDS = {"BEM": 1, "BED": 2, "BDR": 3, "BDS": 4, "BNE": 5, "NE": 5, "BNS": 6, "NS": 6,
           "TEH": 7, "TRH": 8, "TEP": 9, "TRP": 10, "TEC": 11, "TRC": 12, "BSO": 13, "UAR": 14}

SUCCESS_TEXT = "End QUINCY model"


def finite(value, name, lo=None, hi=None):
    """Return float(value) or raise ValueError if it is NaN/inf or outside [lo, hi]."""
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name}={value!r} is not a finite number")
    if lo is not None and v < lo:
        raise ValueError(f"{name}={v} is below {lo}")
    if hi is not None and v > hi:
        raise ValueError(f"{name}={v} is above {hi}")
    return v


def noleap_dates(start_year: int, n_days: int) -> list[dt.date]:
    """Real calendar dates for n_days engine days, starting 1 Jan start_year, skipping Feb 29."""
    out, d = [], dt.date(start_year, 1, 1)
    while len(out) < n_days:
        if not (d.month == 2 and d.day == 29):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def noleap_doy(d: dt.date) -> int:
    """Day of year in the 365-day engine calendar (Mar 1 is always day 60)."""
    doy = d.timetuple().tm_yday
    leap = d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)
    return doy - 1 if (leap and d.month > 2) else doy


def fmt_nml(value) -> str:
    if isinstance(value, bool):
        return ".TRUE." if value else ".FALSE."
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, int) else f"{value:.10g}"
    s = str(value)
    if s.upper() in (".TRUE.", ".FALSE.") or re.fullmatch(r"[-+]?\d+(\.\d*)?([eEdD][-+]?\d+)?", s):
        return s
    return "'" + s.strip("'\"") + "'"


def set_nml(text: str, group: str, key: str, value) -> str:
    """Set key=value inside &group ... / of a namelist text. Adds the key (or group) if absent."""
    line = f"  {key} = {fmt_nml(value)}"
    m = re.search(rf"(?ims)^&{re.escape(group)}[ \t]*$(.*?)^/[ \t]*$", text)
    if not m:
        return text.rstrip("\n") + f"\n&{group}\n{line}\n/\n"
    body = m.group(1)
    pat = re.compile(rf"(?im)^[ \t]*{re.escape(key)}[ \t]*=.*$")
    body = pat.sub(line, body, count=1) if pat.search(body) else body + line + "\n"
    return text[:m.start(1)] + body + text[m.end(1):]


def get_nml(text: str, group: str, key: str):
    m = re.search(rf"(?ims)^&{re.escape(group)}[ \t]*$(.*?)^/[ \t]*$", text)
    if not m:
        return None
    k = re.search(rf"(?im)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(.*?)[ \t]*$", m.group(1))
    return k.group(1) if k else None


def engine_status(run_dir: Path, returncode: int, stdout: str) -> list[str]:
    """Return the list of reasons the run FAILED (empty list = engine finished cleanly)."""
    reasons = []
    if returncode != 0:
        reasons.append(f"engine exit code {returncode}")
    if SUCCESS_TEXT not in stdout:
        reasons.append(f"'{SUCCESS_TEXT}' not printed")
    log = run_dir / "quincy_standalone.log"
    if log.exists():
        warn = [ln.strip() for ln in log.read_text(errors="replace").splitlines() if "Please check" in ln]
        if warn:
            reasons.append(f"engine consistency warning ({len(warn)}x): {warn[0][:300]}")
    err = run_dir / "quincy_standalone.err"
    if err.exists() and err.read_text(errors="replace").strip():
        reasons.append("quincy_standalone.err not empty: " + err.read_text(errors="replace").strip()[:300])
    return reasons
