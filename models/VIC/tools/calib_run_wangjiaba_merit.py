#!/usr/bin/env python3
"""Driver for the CORRECTED Wangjiaba domain (MERIT-Hydro delineation, 69 cells).

Thin wrapper over calib_run_wangjiaba.py, like the modern-era wrapper: the validated
inject / run / route / score / run-health machinery is imported untouched and only the
things the domain and era change are patched.

What the corrected domain changes
  * soil / veg / global-param template -> outputs/wangjiaba_merit (69 cells, built through
    the KI on data/shp/wangjiaba_merit_shp, 30,876 km2 = 101% of the registered 30,630)
  * routing -> outputs/wangjiaba_merit/routing (MERIT-Hydro D8 upscaled with pyflwdir)
  * forcing -> one of two era builds, chosen by the split year unless SYS1_FORCING_ROOT
    says otherwise (that env var is how forecast-rain variants are run)
  * FORCEYEAR -> the era's first forcing year (the base driver never substitutes it)
  * splits for BOTH eras, obs envelope for the modern ones
  * forcing cache keyed on the source path, not a fixed name

n_expected (the run-health flux-file count) is read from the injected soil table by the
base driver, so 69 cells need no change there.

DOMAIN GATE. Before anything runs, the routing fraction area is checked against the
registered drainage area (5% tolerance, fail-closed). This is the check whose absence
let a 52% domain go unnoticed through Phases 0-9.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _drop_stale_out() -> None:
    """codex structure_sync r1 #8: remove the --out metrics file BEFORE any check that can
    fail (obs sha1 at import, input/domain checks in main), so a failed retry can never
    leave an earlier success readable. The base driver repeats this; doing it twice is harmless."""
    argv = sys.argv[1:]
    for i, t in enumerate(argv):
        v = argv[i + 1] if t == "--out" and i + 1 < len(argv) else (t[6:] if t.startswith("--out=") else None)
        if v:
            try:
                Path(v).unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                sys.exit(f"[calib_run] FAIL: cannot remove stale metrics file {v!r}: {e}")


if __name__ == "__main__":
    _drop_stale_out()
_spec = importlib.util.spec_from_file_location("calib_run_wangjiaba",
                                               HERE / "calib_run_wangjiaba.py")
base = importlib.util.module_from_spec(_spec)
sys.modules["calib_run_wangjiaba"] = base
_spec.loader.exec_module(base)

# W5: domain root and cell prefix from the environment (defaults = the 0.25 build).
# For 0.1: SYS1_DOMAIN_ROOT=.../wangjiaba_merit_010, SYS1_CELL_PREFIX=wangjiaba_0.1deg_
DOMAIN = os.environ.get("SYS1_DOMAIN_ROOT", f"{base.BASE}/outputs/wangjiaba_merit")
CELL_PREFIX = os.environ.get("SYS1_CELL_PREFIX", "wangjiaba_0.25deg_")
REGISTERED_AREA_KM2 = 30630.0
AREA_TOL = 0.05

# The base driver caches the routing unit-hydrograph grid (uh_s) keyed on BASIN name and
# (velocity, diffusivity) only. uh_s is a GRID — it depends on the direction file and the
# domain shape — so the old 10x6 kernel must never be served to this 10x10 domain.
# codex W5 HIGH: uh_s is a GRID kernel; key its cache on the routing files' content
# (frac + direc + xmask), so a rebuilt or re-resolved network can never be served a
# stale kernel that only matched on velocity/diffusivity.
def _routing_key(rdir: str, sta: str) -> str:
    h = hashlib.sha1()
    # codex structure_sync r2 #2: key on EVERY routing input rout reads when it builds the uh_s grid
    # (MAKE_GRID_UH folds UH.all in; staloc names the station) — not only frac/direc/xmask
    # r4: hash EXACTLY the set the base driver copies into each routing run (run_rout: every
    # <STA>_*.txt by glob, plus UH.all and rout_global.txt), name + content, so a file referenced
    # under another name (e.g. <STA>_xmask_alt.txt) is covered too.
    names = sorted(p.name for p in Path(rdir).glob(f"{sta}_*.txt")) + ["UH.all", "rout_global.txt"]
    for nm in names:
        h.update(nm.encode() + b"\0")
        h.update(Path(f"{rdir}/{nm}").read_bytes() if Path(f"{rdir}/{nm}").exists() else b"MISSING")
        h.update(b"\0")
    return h.hexdigest()[:10]


base.UH_CACHE_DIR = os.environ.get(
    "KDT_VIC_UH_CACHE",
    f"/dev/shm/kdt_vic_calib/uh_s_wangjiaba_merit_{_routing_key(f'{DOMAIN}/routing', 'WJB')}")

base.SOIL_SRC = f"{DOMAIN}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
base.VEG_SRC = f"{DOMAIN}/vic_temp/veg/vic_veg_param_final.txt"
base.GP_SRC = f"{DOMAIN}/vic_temp/global_param_{Path(DOMAIN).name}.txt"
base.ROUT_SRC = f"{DOMAIN}/routing"
base.FORCING_PREFIX = CELL_PREFIX

ERA = {  # first forcing year -> forcing dir
    1980: f"{DOMAIN}/vic_temp/forcing/forcing_final_1980_1998",
    2000: f"{DOMAIN}/vic_temp/forcing/forcing_final_2000_2018",
}
base.SPLITS = {
    "1982": {"sim": (1980, 1982), "score": ("1982-01-01", "1982-12-31")},
    "1984": {"sim": (1982, 1984), "score": ("1984-01-01", "1984-12-31")},
    "1991": {"sim": (1989, 1991), "score": ("1991-01-01", "1991-12-31")},
    "1996": {"sim": (1994, 1996), "score": ("1996-01-01", "1996-12-31")},
    "1998": {"sim": (1996, 1998), "score": ("1998-01-01", "1998-12-31")},
    "2002": {"sim": (2000, 2002), "score": ("2002-01-01", "2002-12-31")},
    "2003": {"sim": (2001, 2003), "score": ("2003-01-01", "2003-12-31")},
    "2005": {"sim": (2003, 2005), "score": ("2005-01-01", "2005-12-31")},
    "2007": {"sim": (2005, 2007), "score": ("2007-01-01", "2007-12-31")},
    "2008": {"sim": (2006, 2008), "score": ("2008-01-01", "2008-12-31")},
    "2010": {"sim": (2008, 2010), "score": ("2010-01-01", "2010-12-31")},
    "2017": {"sim": (2015, 2017), "score": ("2017-01-01", "2017-12-31")},
}
base.OBS_ENVELOPE.update({
    "2002": {"n_days": 365, "q_min": 15.3, "q_max": 5230.0, "q_sum": 109823.40000000001, "q_mean": 300.8860273972603},
    "2003": {"n_days": 365, "q_min": 41.0, "q_max": 7250.0, "q_sum": 222526.3, "q_mean": 609.6610958904109},
    "2005": {"n_days": 365, "q_min": 39.7, "q_max": 6770.0, "q_sum": 204232.0, "q_mean": 559.5397260273973},
    "2007": {"n_days": 365, "q_min": 41.0, "q_max": 7700.0, "q_sum": 185345.80000000002, "q_mean": 507.79671232876717},
    "2008": {"n_days": 366, "q_min": 41.3, "q_max": 4140.0, "q_sum": 133763.1, "q_mean": 365.4729508196721},
    "2010": {"n_days": 365, "q_min": 32.1, "q_max": 4260.0, "q_sum": 96635.5, "q_mean": 264.75479452054793},
    "2017": {"n_days": 365, "q_min": 63.8, "q_max": 4240.0, "q_sum": 158669.6, "q_mean": 434.71123287671236},
})

split = os.environ.get("KDT_CALIB_SPLIT", "")
era_start = 2000 if split and int(split) >= 2000 else 1980
base.FORCING_SRC = os.environ.get("SYS1_FORCING_ROOT", ERA[era_start])
_key = hashlib.sha1(base.FORCING_SRC.encode()).hexdigest()[:10]
base.FORCING_CACHE = f"/dev/shm/kdt_vic_calib/forcing_wangjiaba_merit_{_key}"

_orig_write_gp = base.write_global_param


def write_global_param(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1):
    _orig_write_gp(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1)
    lines, out, seen = Path(dst).read_text().splitlines(keepends=True), [], False
    for l in lines:
        tok = l.split()
        if tok and tok[0] == "FORCEYEAR" and not l.lstrip().startswith("#"):
            out.append(f"FORCEYEAR\t\t\t{era_start}\n"); seen = True
        else:
            out.append(l)
    if not seen:
        raise base.Fail("global param template has no FORCEYEAR line")
    Path(dst).write_text("".join(out))


base.write_global_param = write_global_param


def domain_gate() -> dict:
    """Routed area vs registered drainage area. Fail-closed."""
    fr = np.loadtxt(f"{base.ROUT_SRC}/WJB_frac.txt", skiprows=6)
    hdr = dict(l.split() for l in open(f"{base.ROUT_SRC}/WJB_frac.txt").readlines()[:6])
    n_lat = float(hdr["yllcorner"]) + int(hdr["nrows"]) * float(hdr["cellsize"])
    cs = float(hdr["cellsize"])
    lats = np.array([n_lat - (i + 0.5) * cs for i in range(fr.shape[0])])
    area_row = cs * 111.32 * np.cos(np.radians(lats)) * cs * 110.57
    routed = float((fr * area_row[:, None]).sum())
    rel = abs(routed - REGISTERED_AREA_KM2) / REGISTERED_AREA_KM2
    rep = {"routed_area_km2": round(routed, 0), "registered_km2": REGISTERED_AREA_KM2,
           "rel_error": round(rel, 4), "tolerance": AREA_TOL, "pass": bool(rel <= AREA_TOL)}
    if not rep["pass"]:
        raise base.Fail(f"DOMAIN GATE: routed area {routed:.0f} km2 vs registered "
                        f"{REGISTERED_AREA_KM2:.0f} ({100*rel:.1f}% off, tol {100*AREA_TOL:.0f}%)")
    return rep


_orig_main = base.main


def main() -> int:
    _drop_stale_out()        # codex structure_sync r1 #8: before every fallible check
    ss = os.environ.get("KDT_VIC_SPINUP_START")
    if ss and int(ss) < era_start:
        raise base.Fail(f"KDT_VIC_SPINUP_START={ss} precedes this era's forcing ({era_start})")
    for p in (base.SOIL_SRC, base.VEG_SRC, base.GP_SRC, base.FORCING_SRC,
              f"{base.ROUT_SRC}/WJB_frac.txt", f"{base.ROUT_SRC}/WJB_direc.txt"):
        if not Path(p).exists():
            raise base.Fail(f"corrected-domain input missing: {p}")
    gate = domain_gate()
    print(f"[merit] domain gate PASS: routed {gate['routed_area_km2']:.0f} km2 vs "
          f"registered {REGISTERED_AREA_KM2:.0f} ({100*gate['rel_error']:.1f}% off)", flush=True)
    print(f"[merit] forcing {base.FORCING_SRC} (FORCEYEAR {era_start})", flush=True)
    return _orig_main()


if __name__ == "__main__":
    sys.exit(main())
