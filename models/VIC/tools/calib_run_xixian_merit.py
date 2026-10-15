#!/usr/bin/env python3
"""Driver for XIXIAN (息县, 10,190 km², the Huai headwater gauge) on its MERIT domain.

Both reviewers named this the single next action after the holdout verdict: run the
Huaibin common θ at Xixian for 2016–2018. If Xixian over-produces in 2017 like Huaibin,
the 2017 miss is basin-wide hydrology; if Xixian is clean, the error is between Xixian
and Huaibin. Xixian is a mountain headwater with little abstraction, so it is the cleanest
discriminator available.

Same thin-wrapper pattern as the Huaibin driver. Obs is the CNGF 息县 file, stcd
50225601 — NOT the 51012 file the MADR archive names, which the identity check showed to be
a different (physically impossible) series. The gauge coordinate used for delineation is
the MERIT main-stem pixel (114.7296E, 32.3263N; 10,211 km² upstream), 700 m from the
registered point, which snaps to a 472 km² side stream.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
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
_spec = importlib.util.spec_from_file_location("calib_run_wangjiaba", HERE / "calib_run_wangjiaba.py")
base = importlib.util.module_from_spec(_spec)
sys.modules["calib_run_wangjiaba"] = base
_spec.loader.exec_module(base)

DOMAIN = os.environ.get("SYS1_DOMAIN_ROOT", f"{base.BASE}/outputs/xixian_merit")
CELL_PREFIX = os.environ.get("SYS1_CELL_PREFIX", "xixian_0.25deg_")
REGISTERED_AREA_KM2 = 10190.0
AREA_TOL = 0.05

base.BASIN, base.STA = "xixian", "XX"
base.OBS_FILE = "KISSPATH_DATA/china_water_level/淮河txt/息县.txt"
base.TARGET_CASE = {
    "case_id": "SITE:xixian", "dataset": "CNGF (china_gaugeflux) 淮河txt", "obs_file": base.OBS_FILE,
    "station_code": 50225601, "station_name": "息县", "variable": "Q", "units": "m3 s-1",
    "missing_sentinel": -99.0, "gauge_lon": 114.7296, "gauge_lat": 32.3263, "routed_station_id": "XX",
}
base.CASE_BY_STATION = {50225601: "SITE:xixian"}
base.SOIL_SRC = f"{DOMAIN}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
base.VEG_SRC = f"{DOMAIN}/vic_temp/veg/vic_veg_param_final.txt"
base.GP_SRC = f"{DOMAIN}/vic_temp/global_param_{Path(DOMAIN).name}.txt"
base.ROUT_SRC = f"{DOMAIN}/routing"
base.FORCING_PREFIX = CELL_PREFIX
ERA = {1980: f"{DOMAIN}/vic_temp/forcing/forcing_final_1980_1998",
       2000: f"{DOMAIN}/vic_temp/forcing/forcing_final_2000_2018"}


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
    "KDT_VIC_UH_CACHE", f"/dev/shm/kdt_vic_calib/uh_s_xixian_merit_{_routing_key(f'{DOMAIN}/routing', 'XX')}")

_ENV = json.loads((HERE / "xixian_obs_envelope.json").read_text())
_prov = _ENV.pop("__provenance__", None)
if not _prov or not _prov.get("obs_sha1"):
    raise base.Fail("xixian_obs_envelope.json carries no obs_sha1 provenance — regenerate it")
_sha_now = hashlib.sha1(Path(base.OBS_FILE).read_bytes()).hexdigest()
if _sha_now != _prov["obs_sha1"]:
    raise base.Fail(f"obs file sha1 {_sha_now[:12]} != envelope's {_prov['obs_sha1'][:12]} — re-declare")
base.OBS_ENVELOPE = _ENV
base.SPLITS = {y: {"sim": (int(y) - 2, int(y)), "score": (f"{y}-01-01", f"{y}-12-31")} for y in _ENV}

split = os.environ.get("KDT_CALIB_SPLIT", "")
era_start = 2000 if split and int(split) >= 2000 else 1980
base.FORCING_SRC = os.environ.get("SYS1_FORCING_ROOT", ERA[era_start])
# An alternative forcing root (e.g. an MSWX-forced era, kimi X6) may start in a different
# year; FORCEYEAR must match the first record of that root, so allow an explicit override
# only together with SYS1_FORCING_ROOT.
if "SYS1_FORCEYEAR" in os.environ:
    if "SYS1_FORCING_ROOT" not in os.environ:
        raise base.Fail("SYS1_FORCEYEAR is only valid together with SYS1_FORCING_ROOT")
    era_start = int(os.environ["SYS1_FORCEYEAR"])
    if split and int(split) - 2 < era_start:
        raise base.Fail(f"split {split} needs forcing from {int(split)-2} but the root starts {era_start}")
base.FORCING_CACHE = f"/dev/shm/kdt_vic_calib/forcing_xixian_merit_{hashlib.sha1(base.FORCING_SRC.encode()).hexdigest()[:10]}"

_orig_write_gp = base.write_global_param


def write_global_param(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1):
    _orig_write_gp(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1)
    out, seen = [], False
    for l in Path(dst).read_text().splitlines(keepends=True):
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
    fr = np.loadtxt(f"{base.ROUT_SRC}/XX_frac.txt", skiprows=6)
    hdr = dict(l.split() for l in open(f"{base.ROUT_SRC}/XX_frac.txt").readlines()[:6])
    cs = float(hdr["cellsize"]); n_lat = float(hdr["yllcorner"]) + int(hdr["nrows"]) * cs
    lats = np.array([n_lat - (i + 0.5) * cs for i in range(fr.shape[0])])
    routed = float((fr * (cs * 111.32 * np.cos(np.radians(lats)) * cs * 110.57)[:, None]).sum())
    rel = abs(routed - REGISTERED_AREA_KM2) / REGISTERED_AREA_KM2
    if rel > AREA_TOL:
        raise base.Fail(f"DOMAIN GATE: routed {routed:.0f} vs registered {REGISTERED_AREA_KM2:.0f} ({100*rel:.1f}% off)")
    return {"routed_km2": round(routed), "rel_error": round(rel, 4)}


_orig_main = base.main


def main() -> int:
    _drop_stale_out()        # codex structure_sync r1 #8: before every fallible check
    if split not in base.SPLITS:
        raise base.Fail(f"KDT_CALIB_SPLIT={split!r} has no Xixian obs envelope (available: {sorted(base.SPLITS)})")
    for p in (base.SOIL_SRC, base.VEG_SRC, base.GP_SRC, base.FORCING_SRC, f"{base.ROUT_SRC}/XX_frac.txt", f"{base.ROUT_SRC}/XX_direc.txt"):
        if not Path(p).exists():
            raise base.Fail(f"xixian input missing: {p}")
    g = domain_gate()
    print(f"[xixian] domain gate PASS: routed {g['routed_km2']} km2 vs {REGISTERED_AREA_KM2:.0f} "
          f"({100*g['rel_error']:.1f}% off); forcing {base.FORCING_SRC} (FORCEYEAR {era_start})", flush=True)
    return _orig_main()


if __name__ == "__main__":
    sys.exit(main())
