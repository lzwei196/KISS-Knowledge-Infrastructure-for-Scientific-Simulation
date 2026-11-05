# SWAN — foundation test case: "refrac_a11"

Authentic foundation case: the official SWAN test case **refrac** (`a11refr`), one of the
test cases published by Delft University of Technology on the SWAN download page
(https://swanmodel.sourceforge.io/download/zip/refrac.tar.gz, sha256 `440994427d45…a7d8`).
A 1 m, 10 s wave train comes in at 120 deg over a beach that slopes from 20 m depth to dry
land. Only refraction and shoaling are on (no wind, quadruplets, breaking or whitecapping),
so the answer can be compared with an exact analytical solution (Ris, 1997).

`inputs/` are the unmodified official files: `a11refr.swn` (command file), `a11refr.bot`
(bottom), `a11refr.loc` (output points). `reference/` holds the official output that ships
with the case (`a11ref01.tab`, `a11ref01.tbl`, `a11ref01.spc`, `a11refr.prt`, written by
SWAN 41.10), the analytical solution `a11refr.ana` and the case notes `refrac.txt`.

| | |
|---|---|
| Engine | SWAN 41.45, serial `swan.exe` (server build of the SWAN source in ADCIRC git `thirdparty/swan`, commit c622c78) |
| Source | SWAN official test cases, Delft University of Technology |
| Licence | SWAN: GNU GPL v3 or later |
| KI | `SWAN` (run with `tools/run_swan.py binary`, output read with `tools/parse_swan_output.py`) |
| Run time | about 1.5 s |

## Run
```
python run_reference.py    # finds swan.exe (--swan-bin, $SWAN_BIN, PATH, server default); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, also copies `a11refr.swn` to `INPUT` (exactly what
the official `swanrun` script does, since `swan.exe` always reads the file `INPUT`), runs
the case through the KI's own `tools/run_swan.py`, reads the output tables with the KI's
`tools/parse_swan_output.py`, checks `expected.json`, and deletes the temp dir.
Use a python that can import `pyswan` (e.g. the HydroCraft python_env), because
`run_swan.py` imports it at start.

## Expected
All expected values come from the **official files** in `reference/`. The official case
gives no tolerance, so tolerances are set to the printed precision of those files.
- run finished: KI tool `Status: OK` and SWAN `Normal end of run A11`
- curve table: 101 points, 100 wet; Hs max 2.402 m (y = 3960 m), Hs min 0.9997 m;
  direction turns from 120 to 94.68 deg; mean Tm01 10.038 s
- the whole curve table (101 x 6) must match the official `a11ref01.tab` within 0.0005
- 13 point outputs: Hs 1.00012 m (deep) to 2.31343 m (shallow), Tm01 10.0806 s;
  the whole point table (13 x 5) must match the official `a11ref01.tbl` within 1e-5
- Hs differs from the analytical solution by at most 0.0025 m along the curve

A clean run on 2026-10-05 with the server's SWAN 41.45: `a11ref01.tab` was byte-identical
to the official file; `a11ref01.tbl` differed only in the version header and by 1e-6 in a
few FSpr values; `a11ref01.spc` differed in one value in the 4th digit. Two clean runs
gave byte-identical outputs.

## KI gaps (status 2026-10-06)
- **Fixed in `dd78254`:** `tools/run_swan.py binary` now copies the case file to the command file `swan.exe` reads (`INPUT`, or the name in `swaninit`), as `swanrun` does. Before: it called `swan.exe <name>`, which ignores the name, so the run stopped at once; this case makes `INPUT` before calling the tool.
  The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Fixed in `dd78254`:** `tools/run_swan.py` now exits with code 1 on any status other than OK. Before: it returned 0 even on FAIL, so this case checks the printed `Status: OK` line.
- **Fixed in `dd78254`:** `pyswan` is now imported only in pyswan mode. Before: it was imported at start, even for binary mode.
