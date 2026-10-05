# GSFLOW — foundation test case: "sagehen_gsflow_pcg"

Authentic foundation case: the official USGS **Sagehen Creek sample problem** that ships
with GSFLOW (github.com/rniswon/gsflow_v2, `GSFLOW/data/sagehen`, commit cec18ae),
**condition 1**: full GSFLOW mode (PRMS + MODFLOW coupled), PCG solver, PRMS parameters in
five files, with the subbasin module. 16 water years, 1980-10-01 to 1996-09-30, daily
(5844 steps). This is also the Sagehen run listed in the official autotest
(`autotest/t001_test.py`: `sagehen/windows/gsflow.control`).

`inputs/` holds only the files this run reads, unmodified (taken with `git show HEAD:`),
in the official folder layout:

- `windows/gsflow.control` — the official control file
- `input/prms/` — `sagehen.data`, `gsflow.params`, `gis.params`, `gvr.params`,
  `ncascade.params`, `subbasin.params`
- `input/modflow/` — `sagehen.nam` and the files it lists (`.bas .oc .dis .lpf .pcg .uzf .sfr .gag`)
- `Readme.sagehen.txt` — the official notes for the example

The large `*.day` climate files (≈44 MB) belong to the other conditions (climate_hru) and
are not used by this run, so they are not included.

| | |
|---|---|
| Engine | GSFLOW 2.4.0 (02/01/2025), MODFLOW-NWT 1.3.0, PRMS 6.0.0 — the binary the KI preflight resolves |
| Source | USGS GSFLOW, gsflow_v2 commit cec18ae99e4093b5cdf10714ace0f5d1d9fe632d |
| Licence | USGS software, public domain (U.S. Government work) |
| KI | `GSFLOW` |
| Size | inputs ≈ 1.2 MB |

## Run
```
python run_reference.py    # finds gsflow (or $GSFLOW_BIN, --gsflow-bin); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, makes `output/modflow` and `output/prms`, and runs
`gsflow gsflow.control` from `windows/`, as the official `gsflow.bat` does. It takes about
15 minutes on one core (the official log also says 14 min 44 s).

One path-only change is made, **only in the temp copy**: the official control file and the
MODFLOW name file use Windows paths (`..\input\...`). On Linux these are changed to `../`.
The official autotest (`autotest/t001_test.py`) makes the same change on non-Windows. No
values change.

## Expected
All expected values come from the **official reference output** that ships with the
example, `GSFLOW/data/sagehen/output-test/1_GSFLOW_mode.PCG` (made by USGS with GSFLOW
2.4.0). The tolerance is 1 % relative, the threshold used by the official GSFLOW autotest
(`autotest/t002_test.py`, `validate()`). Counts are exact.

Checks: finished normally (return code 0 and "Normal termination of simulation"); 5844 daily
rows in `gsflow.csv`; mean and peak basin outflow (31 770 and 1 469 218 m3/d); total
precipitation; mean recharge to the water table; last-day saturated storage; mean
infiltration; 5844 time steps and 0 non-converged steps in `gsflow.out`; whole-run budget
error −0.02 % (±0.05); cumulative UZF recharge, stream leakage out and surface leakage out
from the MODFLOW list file; mean and last flow at the outlet SFR gage
(`sagehen_sfrseg17.out`, segment 15).

## Result on this server (2026-10-05)
`run_reference.py` PASSED: all 15 numeric checks plus the "finished normally" check, run
time 628 s (about 10.5 min), about 210 MB RAM. All summary values match the official
output within 0.002 % (largest gap: last-day outlet gage flow, 6134.23 vs 6134.12; peak
outflow, total precipitation and the budget error are identical).

The day-by-day series are very close but not byte-identical to the official files (likely
a different compiler/build). In `gsflow.csv`, 0.3 % or fewer of the days differ by more
than 1 % in a few small soil/unsaturated-zone flow columns (`SoilDrainage2Unsat_Q`,
`Stream2Unsat_Q`, `Grav_S`) and in the iteration count `KKITER`. These are not used as
checks; the case checks whole-run summary values instead.

## Known KI gaps
- `tools/run_gsflow.py` cannot drive this official case. Its pre-run check treats every
  file named in the control file as a required input, except names containing "output".
  So it stops on `stat_var_file`, `var_init_file` and `var_save_file`, even though this
  control file switches them off (`statsON_OFF 0`, `init_vars_from_file 0`,
  `save_vars_to_file 0`) and the files are not meant to exist. It also does not handle the
  Windows `..\` paths of official GSFLOW examples. So `run_reference.py` runs the gsflow
  binary directly.
- `tools/parse_gsflow_output.py --csv-file gsflow.csv` writes its CSV but then crashes in
  its own output check: it expects dates as `YYYY-MM-DD`, but GSFLOW 2.4.0 writes
  `MM/DD/YYYY`. So `run_reference.py` reads `gsflow.csv`, `gsflow.out`, the MODFLOW list file
  and the gage file directly.
- The KI build tools (control file, PRMS day files, soil parameters) do not make HRU,
  MODFLOW or SFR files, so the KI cannot build this case from raw data; the case uses the
  official files as they are.
