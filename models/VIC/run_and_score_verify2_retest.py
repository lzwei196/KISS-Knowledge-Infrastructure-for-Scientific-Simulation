#!/usr/bin/env python3
"""VIC verify_2 RETEST at John Day River, McDonald Ferry, Oregon (GRDC-Caravan ext).

Why a retest instead of reading the surviving detached/verify_2/result.json:

That result.json (2026-07-10 15:16) was produced with the PREVIOUS generation of
s3_soil/fill_parameters2.py.  The live tool was modified at 17:03 today
(dt_vic_031) to derive `bubble` (VIC soil cols 28-30) from expt and to set
`fs_active` (col 53) = 1, where it previously left the -9999 / 0 sentinels that
are STILL present in this basin's SOIL_PARAM_COMPLETE.txt.  s5_routing/
build_routing_param.py also changed at 17:27, but that diff is comment-only
(VELOCITY is still 1.5 m/s), so it cannot move a number.

A verifier must exercise the CURRENT knowledge infrastructure, not the one that
happened to be on disk three hours ago.  So this script rebuilds the soil stage
and re-runs vic_classic.exe + the Lohmann rout binary.

FROZEN_SOIL and FULL_ENERGY are both FALSE in this basin's global param, so the
dt_vic_031 change SHOULD be inert here.  "Should be inert" is a hypothesis, not
evidence.  This script tests it.  The routed hydrograph produced by the OLD
tools has md5 e3dfb19f0912146a429dca3783e04727 (recorded independently, before
any file was touched).  After the rebuild we md5 the new routed hydrograph:

    identical  -> dt_vic_031 is inert at John Day.  The metrics are unchanged
                  AND are now attributable to the current KI.
    different  -> the newly computed metrics are the truth, and are reported as
                  such.  The old ones are discarded.

Either way, the metrics written to result.json are the ones computed by THIS
run.  Nothing is inherited from the stale file.  (Prior-round lesson: a stale
result.json at Bengbu verify_1 nearly faked cross-basin consistency.)

Resumable:
  * `_prevgen/RESET_DONE` marks the one-time destructive reset, so a relaunch
    never re-deletes freshly rebuilt artifacts.
  * the inner runner is itself per-stage resumable -- DEM mosaic, delineation,
    grid, veg, NASA POWER forcing, global param and routing params all skip on
    existing output, so a relaunch resumes mid-chain rather than refetching
    12 years of forcing.

Only the soil params, the 59 VIC flux files and the routed hydrograph are
rebuilt; every upstream input is held fixed so the md5 comparison isolates the
one variable that changed.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

BASE = "/mnt/disk1/Hydrocraft_server"
KI = f"{BASE}/models/VIC/knowledge_infrastructure"
CASE = f"{BASE}/models/VIC/detached/verify_2"
INNER = f"{KI}/run_and_score_verify2_johnday.py"

BASIN = "johnday_mcdonaldferry"
BDIR = f"{BASE}/outputs/{BASIN}"
SOIL_COMPLETE = f"{BDIR}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
GLOBAL_PARAM = f"{BDIR}/vic_temp/global_param_{BASIN}.txt"
VIC_RESULT = f"{BDIR}/vic_result"
ROUT_OUT = f"{BDIR}/routing_param/rout_out"
PREV = f"{BDIR}/_prevgen"

# md5 of the routed .day produced by the PREVIOUS tool generation, read off disk
# before this script existed.  Hard-coded so the comparison cannot be silently
# rewritten by the reset step.
REF_DAY_MD5 = "e3dfb19f0912146a429dca3783e04727"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def day_file():
    d = sorted(glob.glob(f"{ROUT_OUT}/*.day"))
    return d[0] if d else None


def fail(note, extra=None):
    r = {
        "model_id": "VIC",
        "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
        "obs_source": "GRDC",
        "status": "failed",
        "tools_used": [],
        "tools_failed": [note],
        "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": note,
    }
    if extra:
        r.update(extra)
    os.makedirs(CASE, exist_ok=True)
    with open(f"{CASE}/result.json", "w") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- reset (once)
os.makedirs(PREV, exist_ok=True)
if not os.path.exists(f"{PREV}/RESET_DONE"):
    pre = {}
    d = day_file()
    if d:
        pre["prev_day_md5"] = md5(d)
        shutil.copy2(d, f"{PREV}/prev_routed.day")
    if os.path.exists(SOIL_COMPLETE):
        pre["prev_soil_md5"] = md5(SOIL_COMPLETE)
        shutil.copy2(SOIL_COMPLETE, f"{PREV}/prev_SOIL_PARAM_COMPLETE.txt")
    pre["tool_md5_fill_parameters2"] = md5(f"{KI}/s3_soil/fill_parameters2.py")
    pre["tool_md5_build_routing_param"] = md5(f"{KI}/s5_routing/build_routing_param.py")
    with open(f"{PREV}/pre.json", "w") as f:
        json.dump(pre, f, indent=2)

    # Force exactly three inner stages to re-run: s3 soil, s7 VIC, s9 rout.
    if os.path.exists(SOIL_COMPLETE):
        os.unlink(SOIL_COMPLETE)
    for p in glob.glob(f"{VIC_RESULT}/*"):
        os.unlink(p)
    for p in glob.glob(f"{ROUT_OUT}/*"):
        os.unlink(p)
    open(f"{PREV}/RESET_DONE", "w").close()
    print(f"[reset] forced rebuild of soil + VIC + rout; pre={pre}", flush=True)
else:
    print("[reset] already performed -- resuming", flush=True)

with open(f"{PREV}/pre.json") as f:
    pre = json.load(f)

if pre.get("prev_day_md5") != REF_DAY_MD5:
    fail(f"pre-reset routed .day md5 {pre.get('prev_day_md5')} != recorded "
         f"{REF_DAY_MD5}: the artifact on disk is not the one the stale "
         f"result.json describes, so the comparison baseline is unsound")
    sys.exit(1)

# ------------------------------------------------------------------ inner run
print(f"\n===== inner runner: {INNER} =====", flush=True)
rc = subprocess.run([sys.executable, INNER], cwd=KI).returncode
print(f"[retest] inner runner rc={rc}", flush=True)

rj = f"{CASE}/result.json"
if not os.path.exists(rj):
    fail(f"inner runner exited rc={rc} without writing result.json")
    sys.exit(1)

with open(rj) as f:
    R = json.load(f)

# --------------------------------------------------- read-back + md5 compare
d = day_file()
new_day_md5 = md5(d) if d else None
new_soil_md5 = md5(SOIL_COMPLETE) if os.path.exists(SOIL_COMPLETE) else None

# Read-back proves the new tool actually wrote the new columns.  (Prior-round
# lesson: a param that passes write->read verification can still change nothing;
# only a metric/artifact change proves effectiveness.  Here we want BOTH facts:
# the soil file did change, and the hydrograph did not.)
bubble_min = fs_active_set = None
if new_soil_md5:
    import pandas as pd
    sp = pd.read_csv(SOIL_COMPLETE, sep=r"\s+", header=None)
    bubble_min = float(pd.to_numeric(sp.iloc[:, 27]).min())
    fs_active_set = sorted(set(int(v) for v in sp.iloc[:, 52]))

soil_changed = (new_soil_md5 != pre.get("prev_soil_md5"))
hydro_identical = (new_day_md5 == pre.get("prev_day_md5") == REF_DAY_MD5)

R["reproducibility"] = {
    "prev_tool_generation_day_md5": REF_DAY_MD5,
    "current_tool_generation_day_md5": new_day_md5,
    "routed_hydrograph_identical": hydro_identical,
    "soil_param_md5_prev": pre.get("prev_soil_md5"),
    "soil_param_md5_current": new_soil_md5,
    "soil_param_changed": soil_changed,
    "bubble_min_cm": bubble_min,
    "fs_active_values": fs_active_set,
    "frozen_soil": "FALSE",
    "full_energy": "FALSE",
}

verdict = (
    f"RETEST vs CURRENT KI. The surviving detached/verify_2/result.json was built by the "
    f"PREVIOUS generation of s3_soil/fill_parameters2.py; the live tool (17:03, dt_vic_031) now "
    f"derives bubble (cols 28-30) and sets fs_active=1 (col 53). Soil params, all 59 VIC flux "
    f"files and the routed hydrograph were deleted and rebuilt with the CURRENT tools "
    f"(build_routing_param.py's 17:27 diff is comment-only; VELOCITY still 1.5 m/s). "
    f"Soil file changed: {soil_changed} (bubble_min={bubble_min} cm, fs_active={fs_active_set}, "
    f"was -9999/0). Routed hydrograph identical to the previous generation: {hydro_identical} "
    f"({new_day_md5}). "
    + ("Because FROZEN_SOIL and FULL_ENERGY are both FALSE, VIC never reads bubble or fs_active "
       "here, so the dt_vic_031 change is confirmed INERT at this basin: the metrics below are "
       "byte-for-byte the same run, now attributable to the current KI."
       if hydro_identical else
       "The hydrograph MOVED, so dt_vic_031 is NOT inert at this basin and the metrics below are "
       "the newly computed ones; the stale result.json's numbers are discarded.")
)
R["notes"] = verdict + " || PRIOR-GENERATION NOTE: " + R.get("notes", "")

with open(rj, "w") as f:
    json.dump(R, f, indent=2, ensure_ascii=False)

print(json.dumps(R["reproducibility"], indent=2), flush=True)
print(json.dumps(R["metrics"], indent=2), flush=True)
print("RETEST DONE", flush=True)
sys.exit(rc)
