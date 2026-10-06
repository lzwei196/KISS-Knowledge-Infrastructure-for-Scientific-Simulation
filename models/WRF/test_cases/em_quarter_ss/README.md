# WRF foundation test case: `em_quarter_ss` (official idealized supercell case)

## What it is
The official WRF idealized case `test/em_quarter_ss`: a 3D supercell thunderstorm. The start state is one
sounding (Weisman and Klemp 1982) with "quarter-circle" wind shear and a warm bubble that starts the storm.
41 x 41 x 40 mass points, dx = dy = 2 km, model top 20 km, time step 12 s, 60 minutes (300 steps), output
every 30 minutes. Kessler warm-rain microphysics; no radiation, boundary layer or land surface.
Upstream description: `inputs/README.quarter_ss`.

WRF builds one case per build: this case needs `ideal` and `wrf` built with `WRF_CASE=EM_QUARTER_SS`. The
KI's em_real build (`real`/`wrf`) cannot run it.

## Source and licence
- Repository: https://github.com/wrf-model/WRF, WRF 4.7.1, commit `f15568ccc1447780e3bd664b9f0196edd784bf33`.
- Licence: public domain (NCAR/UCAR notice, kept here as `LICENSE_WRF.txt` as UCAR asks).
- `inputs/namelist.input`, `inputs/input_sounding` (the run inputs) and `inputs/README.quarter_ss` (information
  only) taken with `git show f15568cc:test/em_quarter_ss/<file>`, unmodified.
- WRF ships **no reference output** for this case.

## Engine
Built on this server on 2026-10-06 in `/home/server/engine_builds_20261006/wrf/`:
`install_quarter_ss/bin/ideal` (sha256 `8fa575b2...652e`) and `install_quarter_ss/bin/wrf`
(sha256 `3d63fcca...e314`). Source: `git archive` of the commit above plus its submodules phys/noahmp
`e5c08598` and phys/MYNN-EDMF `90f36c25`; MMM-physics `0ea59b1c` (tag 20240626-MPASv8.2) cloned by WRF's own
manage_externals step. Configured the official CMake way (`configure_new`): toolchain from the
`arch/configure.defaults` stanza "GNU (gfortran/gcc)", serial (no MPI, no OpenMP), Release, WRF_CORE=ARW,
WRF_NESTING=NONE, WRF_CASE=EM_QUARTER_SS; gfortran/gcc 13.3.0, netCDF from /usr. Build log:
`/home/server/engine_builds_20261006/wrf/BUILD_LOG.md`.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--wrf-install DIR] [--keep]
```
Install folder lookup: `--wrf-install` -> `$WRF_QUARTER_SS_INSTALL` -> server default
`/home/server/engine_builds_20261006/wrf/install_quarter_ss`. Both `bin/ideal` and `bin/wrf` come from that one
folder, so a wrf from another build is never mixed in (the em_real install has no `ideal`, so it gives exit 3).
The script copies the two inputs to a fresh temp dir, runs `ideal` then `wrf` (serial, `OMP_NUM_THREADS=1`),
checks `expected.json`, and deletes the temp dir. Exit 0 = PASS, 2 = checks failed, 3 = engine or dependency
missing. It takes about 10 seconds.

## Expected results
All values are **our own run values** (regression values), not official reference results. Two runs in fresh
folders were identical in every variable of `wrfinput_d01` (179) and `wrfout_d01_0001-01-01_00:00:00` (162);
the wrfout files were byte-identical. Float checks use 1e-6 relative tolerance, which is **provisional**: it is
proven only for this build, not across compilers or machines. Counts use exact match.

Checks: 3 records in one wrfout file (00:00, 00:30, 01:00), last XTIME 60 min, 41 x 41 x 40 = 67240 mass points,
no NaN/Inf; max updraft W 30.18 m/s at 30 min and 43.29 m/s at 60 min; min W -12.71 m/s; T (theta - 300 K) min
-7.18 K (cold pool) and max 190.67 K (near the model top); max QRAIN 0.01530 kg/kg; max QCLOUD 0.00774 kg/kg;
RAINNC max 36.61 mm and domain mean 1.046 mm; max |U| 53.90 m/s (all at 60 min unless said, whole domain, W and
U on their staggered grids). Finished check: both programs return 0 and print
`SUCCESS COMPLETE IDEAL INIT` / `SUCCESS COMPLETE WRF`.

PASS output tail (2026-10-06):
```
  OK u_absmax_60min: 53.90291214
PASS: WRF em_quarter_ss matches expected.json.
```

## Known KI gaps (not fixed here)
- `tools/run_wrf.py` has no ideal-case stage: it needs `real.exe` even when the real step is skipped, so it
  cannot run this case. This case runs `ideal` and `wrf` directly.
- `tools/parse_wrfout.py` reads points or surface slices at one time; it cannot give the whole-volume maxima
  used here, so the case reads wrfout with netCDF4 directly.
- The KI default programs (preflight, SKILL.md) stay the em_real build; the ideal build path is only named here.
  The live KI was not changed.
