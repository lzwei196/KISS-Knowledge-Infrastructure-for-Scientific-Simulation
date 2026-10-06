# LPJmL — foundation test case: "testcase_2cell"

Official foundation case: the **2-cell test case** that ships with LPJmL (`testcase_2cell/`)
and is run by the upstream `make test` target. It is a full LPJmL run (natural vegetation,
crops, land use, fire, river routing, methane, nitrogen) on 2 grid cells: a 3800-year
spinup, then a transient run from the restart file (output years 1481–2019). Upstream ships
the expected outputs `globalflux_spinup.csv` and `globalflux.csv` in the same folder.
`inputs/` holds the unmodified official files from the upstream git tree.

| | |
|---|---|
| Engine | LPJmL C Version 6.1.9 (git 4595764), built on this server from a clean checkout (see below) |
| Source | https://github.com/PIK-LPJmL/LPJmL tag `v6.1.9`, commit `4595764150e981da2dd5672621544c41e77b1c6a` (2026-09-01) |
| Licence | LPJmL code and config: AGPL-3.0-or-later. Input data: licence in each `.clm.json` (CC-BY 4.0, CC0 1.0, one ODbL 1.0) |
| KI | `LPJmL` (run tool `tools/run_lpjml.py`) |

## What is in `inputs/`
Taken with `git archive` from tag v6.1.9 (all 94 files byte-identical to the git tree, sha256 in `manifest.json`):
- `testcase_2cell/` — all 81 files: 2-cell inputs (`*.clm` + `.clm.json`), CO2 / CH4 text files,
  `input_testcase_2cell.cjson`, and the official reference outputs `globalflux_spinup.csv`,
  `globalflux.csv` (+ `.json`).
- `lpjml_config.cjson` and `par/` — the official main config and parameter files the run reads.
- `include/soilpar.h`, `include/managepar.h`, `include/conf.h` — headers that `par/*.cjson` include.

## Run
```
python run_reference.py     # 0 = PASS, 2 = run or checks failed, 3 = engine/dependency missing
python run_reference.py --lpjml-bin /path/to/lpjml   # or set $LPJML_BIN
```
It copies `inputs/` to a fresh temp dir (same layout as the LPJmL source tree), links
`bin/lpjml` to the engine, removes `LPJINPATH`/`LPJROOT`/other `LPJ*` path variables from the
environment, and runs the two `make test` commands through the KI's own `tools/run_lpjml.py`:
```
lpjml -DTESTCASE_2CELL lpjml_config.cjson                  # spinup  (~2 min)
lpjml -DFROM_RESTART -DTESTCASE_2CELL lpjml_config.cjson   # transient (~6 min)
```
Both must return 0 and print `lpjml successfully terminated, 2 grid cells processed`.
Time limit 1200 s for both runs together; memory ~35 MB. The temp dir is deleted
(`--keep` keeps it, `--save-csv DIR` copies the two output CSVs).
The binary must report version 6.1.9; another version is reported as missing (exit 3), never run.

## Expected results
Expected values come from the **official reference files** in `inputs/testcase_2cell/`
(made by PIK with LPJmL 6.1.9). `run_reference.py` recomputes them from those files and
stops if `expected.json` does not match them.

Exact checks: both runs finish normally; names and units rows identical; Year columns
identical (3800 spinup rows, years −2099..1700; 539 transient rows, 1481..2019); the pass-through columns `prec`
(both files) and `area` (transient) identical; every number finite.

Tolerance checks (relative, `|run − ref| <= tol × |ref|`):

| check | official value | tol |
|---|---|---|
| spinup GPP, mean of last 300 years | 0.0073787 | 1e-3 |
| spinup VegC, mean of last 300 years | 0.040444 | 1e-3 |
| spinup SoilC, mean of last 300 years | 0.075545 | 1e-3 |
| transient GPP mean 1481–2019 | 0.0035571 | 1e-2 |
| transient NPP mean | 0.0015701 | 1e-2 |
| transient VegC mean | 0.013886 | 1e-2 |
| transient SoilC mean | 0.049622 | 1e-2 |
| transient transpiration mean | 0.0010932 | 1e-2 |
| transient discharge mean | 0.0021054 | 1e-2 |

(units: 1e15 gC/yr, 1e15 gC, 1e15 dm3/yr, sums over the 2 cells)

**Why a tolerance, and why these numbers.** Upstream has no comparison script and no
tolerance. Its merge-request rule is: run `make test` and commit the new globalflux files,
so upstream expects a fresh run on its own build to give these files (it does not promise
bit-for-bit repeats). On this server (gcc 13.3) they are not
byte-identical: the first 3 spinup years match bit for bit, then small differences grow
through threshold logic (fire, establishment, random cell order). We built the same v6.1.9
source a second time with other gcc options (`-O2 -march=native -ffp-contract=fast`); the two
builds differ from each other by about as much as either differs from the official files.
So the results are sensitive to compiler options and the differences are consistent with
floating-point effects. This does not prove there is no other build difference (the official
files name a PIK-internal git hash `86db983`, and PIK's exact build settings are not
published). The largest relative difference seen across the three result sets was 5.59e-5
(spinup end means) and 2.86e-3 (transient means), so the tolerances are 1e-3 and 1e-2.
**These tolerances are chosen locally, not by upstream.** Single-year values are not checked:
they differ by up to ~4% between builds. These checks prove the run works and agrees in
aggregate; they do not prove year-by-year agreement of every output.

Our result (2026-10-06, engine below): all checks PASS; spinup end means within ~4e-5 and
transient means within ~1.6e-3 of the official values. Repeat: 5 clean runs of this engine (trial + 4 `run_reference.py` runs) gave byte-identical `globalflux_spinup.csv` (sha256 7bd5d737…) and `globalflux.csv` (sha256 2486285c…), so the engine is deterministic here.

## Engine (built for this case)
The KI's preflight engine is LPJmL **v6.0.0** (`cdfae44`). The test case was added in 6.0.7,
v6.0.0 has no `TESTCASE_2CELL` config, and the reference files were made by 6.1.9, so this
case uses a separate v6.1.9 build:
`/home/server/engine_builds_20261006/lpjml_v6.1.9/LPJmL/bin/lpjml`
(build notes and logs: `/home/server/engine_builds_20261006/lpjml_v6.1.9/BUILD_NOTES.txt`).
- Clean clone of tag v6.1.9, no source edits. Official `./configure.sh -nompi -noerror`
  (`-noerror` because gcc 13 stops on a `warn_unused_result` warning under `-Werror`).
- All official compile flags kept (`-DSAFE -DUSE_RAND48 -DWITH_FPE -DUSE_NETCDF
  -DUSE_UDUNITS -DPERMUTE -DSTRICT_JSON -O2`). Only include/library paths were added to
  `Makefile.inc`: json-c 0.16 and netCDF 4.8.1 from `miniconda3/envs/lisflood_official`,
  udunits2 from `miniconda3`.
- **json-c trap:** do not link json-c 0.18. With `-DSTRICT_JSON`, json-c 0.18 rejects the
  valid UTF-8 (en dash, degree sign) in the official `kbf_testcase_2cell.clm.json` and the run
  stops with `ERROR228 ... invalid string sequence`. json-c 0.16 and 0.17 read it fine.

## Known KI gaps
- The KI's engine (v6.0.0) cannot be used for this case: different version than the one that
  made the reference files, and no `TESTCASE_2CELL` set-up.
- `tools/run_lpjml.py` runs `<lpjroot>/bin/lpjml` with the working dir set to `lpjroot`, so the
  case links the engine into `bin/` of the temp dir. It prints only the first and last 20 lines
  of the model output and does not save the full log (`run_reference.py` saves what the tool
  prints). Its exit code is only 0/1. It puts `-DFROM_RESTART` before `-DTESTCASE_2CELL`
  (the Makefile has the reverse order; same macros, same result).
- The tool's output summary counts "globalflux years" as lines − 1 of the first file it finds,
  which is wrong for these CSVs (they have a names row and a units row).
- `tools/parse_lpjml_output.py` reads binary/CLM output, not the `globalflux` CSV files, so
  `run_reference.py` reads the CSVs directly.
