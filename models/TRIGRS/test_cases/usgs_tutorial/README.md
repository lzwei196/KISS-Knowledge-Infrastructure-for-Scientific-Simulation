# TRIGRS foundation test case: usgs_tutorial

## What it is
The official tutorial that USGS ships with TRIGRS. It is a small 10 x 10 cell hillside
(10 m cells) with two soil zones. Rain falls in two periods: a light one for 48 hours
(3e-7 m/s, to t = 172800 s) and a heavy one for 12 hours (9e-5 m/s, to t = 216000 s).
TRIGRS works out pore-water pressure and the factor of safety (FS) of each cell at the end
of each period. Before TRIGRS, the tutorial runs TopoIndex to build the runoff-routing files
(which cell drains into which).

Main result: no cell is unstable after period 1; after period 2, 16 of 100 cells have
FS < 1 (lowest FS 0.9817), and the water table reaches the surface everywhere.

## Source
- USGS landslides-trigrs git, https://code.usgs.gov/usgs/landslides-trigrs
  (also on GitHub as usgs/landslides-trigrs), commit 9bb5ec2a697e161d1b602eb68ffa7acc722d5ee6
  (2022-02-03, "Bug fix to correct water table outputs"), folder `trigrs_full/`.
- `inputs/data/tutorial/*.asc` = all 12 tracked files of `data/tutorial/`;
  `inputs/tpx_in.txt` and `inputs/tr_in.txt` = the tutorial setup files at the repo root.
  All taken with `git show HEAD:<path>`; each file's git blob hash was checked against the repo
  (the server copies of `tpx_in.txt` / `tr_in.txt` had local edits and the tutorial folder had
  leftover local outputs, so the working-tree files were not used).
  `master.asc`, `test1.asc`, `test2.asc` belong to the GridMatch part of the tutorial and are
  not read by this run; they are kept so the folder is complete.
- Licence: public domain (USGS). Two Netlib files (calerf.f, derfc.f) are in the engine source
  (see LICENSE.md in the repo).

## Engine
- TRIGRS 2.1.00c serial (`trg`, build date 02 Feb 2022) and TopoIndex 1.0.14 (`tpx`), built
  from the commit above with gfortran.
- Server paths: `/mnt/disk1/Hydrocraft_server/models/TRIGRS/source/repo/source/trigrs_full/src/TRIGRS/trg`
  (same file, same sha256, as `/mnt/disk1/Hydrocraft_server/models/TRIGRS/bin/trg`) and
  `.../src/TopoIndex/tpx`.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py
#   [--trg-bin PATH] [--tpx-bin PATH] [--keep]
```
Lookup: `--trg-bin` -> `$TRIGRS_BIN` -> `which trg` -> server default; same for
`--tpx-bin` / `$TOPOINDEX_BIN` / `tpx`. Exit 0 = PASS, 2 = checks failed,
3 = engine missing ("MISSING DEPENDENCY: ... NOT run.").

The script copies the inputs into a fresh temp dir (grids into `Data/tutorial/`), runs
TopoIndex, then runs TRIGRS through the KI tool `tools/run_trigrs.py`
(`--skip_compile --skip_topoindex`), reads results with `tools/parse_trigrs_output.py`
plus direct reads, checks `expected.json`, and deletes the temp dir. It takes about 1 second.

### Path settings changed in the temp copies (only these; `inputs/` stay untouched)
| file | shipped line | used line | why |
|---|---|---|---|
| tpx_in.txt | `data/dem.asc` | `Data/tutorial/dem.asc` | point at the tutorial grids |
| tpx_in.txt | `data/directions.asc` | `Data/tutorial/directions.asc` | same |
| tr_in.txt | `Data/tutorial/TIdscelGrid_tutorial.asc` | `Data/tutorial/TIdscelGrid_tutorial.txt` | TopoIndex writes this file with a `.txt` name |

All other paths in `tr_in.txt` (`Data/tutorial/...`, output folder `Data/tutorial/`) are used
as shipped. No physical setting is changed.

About the third edit: with the shipped `.asc` name, TRIGRS cannot find the file, logs
"Skipped runoff-routing computations; Runoff routing input data did not exist", writes no
runoff grids, and gives a different FS at t1 (checked on this server). With the `.txt` name
the runoff routing runs, as the tutorial intends. The script checks that routing really ran.

## Expected results
The USGS repo has no reference outputs for the tutorial (`git ls-files` lists inputs only),
so the values in `expected.json` come from our own real runs. Three clean runs gave
byte-identical output grids and list file, and the same `TrigrsLog.txt` apart from the
date/time lines. Checks (18 numbers plus "finished normally" for both programs and
"runoff routing ran"):

| check | value |
|---|---|
| TopoIndex data cells / downslope links | 100 / 154 |
| FS min, mean at t1 (172800 s) | 1.113, 2.67524 |
| cells with FS < 1 at t1 | 0 |
| FS min, mean at t2 (216000 s) | 0.9817, 2.22815 |
| cells with FS < 1 at t2 | 16 of 100 |
| mean water-table depth t1 / t2 (m) | 1.477 / 0.0 |
| max pressure head at depth of min FS, t2 (m) | 2.0 |
| sum of runoff grid, period 2 (m/s) | 0.0124439 |
| mean infiltration rate, period 2 (m/s) | 7.91644e-05 |
| depth profiles in TRlist_z_p_fs (100 cells x 2 times) | 200 |
| mass balance period 2: infiltration / runoff | 7.9164386e-03 / 1.0835815e-03 |
| mass balance closure, period 2 (relative) | 1.35e-8 (must be < 1e-6) |

Grid values are written with 4 significant digits, so tolerances are set at that level.

Note: the mass balance in the log shows rain rates of 3e-7 and 9e-5 m/s (the `cri` values
in `tr_in.txt`), not the 5e-5 / 7e-5 m/s values in `ri1.asc` / `ri2.asc`. This is how the
shipped tutorial runs; we record it and change nothing.

## KI gaps (status 2026-10-06)
- **Fixed in `dc43a8c`:** `tools/run_trigrs.py` can use a built `tpx` (`--tpx_binary`, `$TOPOINDEX_BIN`, or the server default) and stops if TopoIndex fails. Before: it looked for a `src/TopoIndex/Makefile` (there is none), then ran `make tpx` inside the source tree, so this case runs `tpx` directly and calls the tool with `--skip_topoindex`.
  The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Fixed in `dc43a8c`:** `tools/run_trigrs.py` can take a stand-alone `trg` (`--trg_binary`, `$TRIGRS_BIN`, or the server default `bin/trg`) and only needs a source tree and `gfortran` when it must compile. Before: it needed `trg` inside a `src/TRIGRS/` folder with a Makefile and Fortran files, and `gfortran` on PATH even with `--skip_compile`; `run_reference.py` runs `trg` directly if the binary is not in such a folder.
- **Partly fixed in `dc43a8c`:** `tools/parse_trigrs_output.py` now matches the real runoff and infiltration file names (`TRrunoffPer<N><suffix>`, `TRinfilratPer<N><suffix>`), reads the list-file column header, and no longer counts the "...to avoid early-time errors..." line as an error; not re-checked: whether the pressure-head grid, list file and mass balance numbers now come out right through the tool (this case still reads them directly). Before: its runoff/infiltration name patterns did not match what TRIGRS writes, so those grids, the pressure-head grid, the list file and the mass balance numbers were read directly.
- **Still open:** The KI has no tool that can make the tutorial's DEM, slope, depth or water-table grids, so
  the official grids are used as shipped.
