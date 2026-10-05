# RZWQM2 — foundation test case: "corn_akron_irr1_1985"

Official foundation case: the **Corn-Akron / Irr-1-85DS** example scenario that ships in the
`DATA` example library of the USDA-ARS RZWQM2 Windows release (the user guide says "Other
example projects are located in the DATA directory"). It is one year (1 Jan - 31 Dec 1985) of
irrigated corn at the USDA-ARS Central Great Plains Research Station, Akron, Colorado,
with the CERES-Maize crop model (DSSAT 4.0 inside RZWQM2).
`inputs/` are the unmodified release files.

| | |
|---|---|
| Engine | RZWQM2 Version 4.6 Intel Fortran (September 2, 2025), Linux build `main_ryzen_patched` |
| Source | USDA-ARS RZWQM2 Windows release: `C:\RZWQM2\data\Corn-Akron\` (scenario `Irr-1-85DS`, `Meteorology\akron.*`, `Project.rzp`) and `C:\RZWQM2\DATABASES\DSSAT\` (4 files). Input headers say V4.20. Server copy of the install folders: `/home/server/RZWQM2/RZWQM2/data/data/Corn-Akron` and `.../data/databases/DSSAT` |
| Licence | USDA-ARS public software (US Government work), free download after registration at ars.usda.gov (softwareid=412) |
| KI | `RZWQM2` |

## What is in inputs/
- `Irr-1-85DS/`: `ipnames.dat` (file list + dates), `cntrl.dat`, `rzwqm.dat`, `rzinit.dat`,
  `plgen.dat`, `mzdssat.rzx` (DSSAT control), `mzcer040.cul` (cultivar), `expdssat.MZA`,
  `expdata.dat` (measured field data, read by the model for its model-vs-measured tables),
  `RZCropSel.rzq`, `Scenario.rzp`.
- `Meteorology/`: `akron.met` (daily weather), `akron.brk` (breakpoint rain), `akron.sno` (snow).
- `DSSAT/`: `DATA.CDE`, `DETAIL.CDE`, `MZCER040.ECO`, `MZCER040.SPE` from the release DSSAT database.
- `Project.rzp`: the project description from the release.

These are exactly the files the engine opens for this scenario (checked with `strace`).
The GUI-only files of the scenario (`rzzzzz.*`, `state.bin`) and the old `DSSATWTH.WTH`
(the engine writes it new) are left out; a test run with `state.bin` gave the same `.ana`.
Total size about 350 KB.

## Run
```
python run_reference.py    # finds the engine ($RZWQM2_BIN, --rzwqm2-bin, PATH, server default); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, runs the engine through the KI's own
`tools/s8_execution/run_rzwqm2.py`, reads the daily `.ana` file with the KI's own
`tools/s9_result_parsing/parse_ana_output.py`, reads `MASSBAL.OUT`, checks
`expected.json`, and deletes the temp dir. One run takes about 1-2 seconds.

Only the temp copy is changed, and only in the way the RZWQM2 interface itself does before
every run (it rewrites the paths in IPNAMES.DAT and *DSSAT.RZX):
- `ipnames.dat` -> `IPNAMES.DAT` and `mzdssat.rzx` -> `MZDSSAT.RZX` with the
  `C:\RZWQM2\...` paths made relative (`./`, `../Meteorology/`, `../DSSAT/`).
- The Linux engine opens some files by UPPER-CASE name (`IPNAMES.DAT`, `MZDSSAT.RZX`,
  `MZCER040.CUL`, `EXPDATA.DAT`, `EXPDSSAT.MZA`). Windows ignores case, Linux does not,
  so upper-case copies are made. No numbers in any file are changed.

## Expected (recorded 2026-10-05 from our own runs; deterministic: two clean runs gave a byte-identical .ana)
The release ships no model output for this scenario (its `Analysis` folder is empty), so the
values come from real runs of the engine above. `expdata.dat` is measured field data, not
model output, so it is not used as the reference.
- 366 daily records (day 0 + 365 days), last day 1985 DOY 365; return code 0
- rain 45.311 cm, irrigation 7.0 cm, soil evaporation 23.769 cm, transpiration 27.395 cm,
  runoff 0.785 cm, soil water on 31 Dec 24.019 cm
- peak above-ground biomass 14159 kg/ha, peak grain 6329 kg/ha, peak LAI 2.215,
  peak grain N 112.1 kg N/ha, N mineralization 66.47 kg N/ha
- model's own end-of-run balance errors (MASSBAL.OUT): water 3.5e-6 cm, N 7.1e-4 kg N/ha

## Notes
- The engine prints `sh: 1: copy: not found` twice (a Windows `copy` shell call; harmless
  on Linux) and `check your expdata.dat file (daily data)` (about the observation table).
  Neither changes the checked results.
- The server's `models/RZWQM2/example_run` (Ohio "TM2_Ohio" project, 2011-2021) is NOT
  used: it is a user project (`C:\RZWQM2\projects\TM2_Ohio`, weather files named
  "Ohio_TM_2_modified - Copy2011added.MET" and "OhioTMSiteHourlyDataFeb32023.BRK"), not part
  of the release DATA library. The Bengbu wheat template the KI SKILL.md points to is a
  local project setup and is not used either.

## Known KI gaps
- `run_rzwqm2.py` reads `ipnames.dat` before `IPNAMES.DAT` and checks the paths in it, but the
  Linux engine itself opens only `IPNAMES.DAT` (and other files by upper-case name). A release
  scenario folder with Windows paths and lower-case names therefore does not run as-is; the
  tool does not do the path / upper-case step that the RZWQM2 interface does. This case does
  that step itself in the temp copy.
- `run_rzwqm2.py` default `BINARY_PATH` points to `/home/server/RZWQM2/RZWQM2/linux/main_ryzen_patched`,
  not the preflight engine `/mnt/disk1/Hydrocraft_server/model/rzwqm2/main_ryzen_patched`;
  this case always passes the binary path explicitly.
