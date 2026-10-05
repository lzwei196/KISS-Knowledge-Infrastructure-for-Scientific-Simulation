# HydroTrend — foundation test case: "greenland_fjord_default"

Real foundation case: the official **default input** that ships with HydroTrend
(`data/input/HYDRO.IN` + `HYDRO0.HYPS`, title "Greenland Fjord(Mar 2008), 1000 year
simulation"). The HydroTrend repo checks a run of this input against its own reference
output `data/output/HYDROASCII.Q` with an exact `diff`
(`data/hydrotrend_test_with_args.sh.in`). `inputs/` are the unmodified files from git
HEAD; `reference/HYDROASCII.Q` is the unmodified official output.

| | |
|---|---|
| Engine | HydroTrend (prints `3.0.5` for `--version`), built from tag v3.1.4 |
| Source | github.com/csdms-contrib/hydrotrend, commit 813a9f1 (`data/input`, `data/output`) |
| Licence | MIT (Copyright (c) 2014 Albert Kettner) |
| KI | `HydroTrend`, run tool `tools/run_hydrotrend.py` |

What the case does: one epoch, 1908 to 2907 (1000 years), weather made by the model's
own random generator from the monthly climate table in HYDRO.IN, 4 sediment grain
sizes, BQART sediment load. Output is averaged by month (HYDRO.IN line 5 = `M`), so each
`HYDROASCII.*` file has 12000 rows. The random seeds are fixed, so the run repeats
exactly. Runs in about 1.5 s, uses about 12 MB of memory.

## Run
```
python run_reference.py    # finds the binary (or --hydrotrend-bin, $HYDROTREND_BIN); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to `<tempdir>/input/`, then runs the KI's own
`tools/run_hydrotrend.py` from inside the temp dir with `--in-dir input --out-dir output`,
then checks `expected.json` and deletes the temp dir.

## Expected (recorded 2026-10-05)
- `HYDROASCII.Q` is **byte-identical** to the official `reference/HYDROASCII.Q`
  (this is the repo's own test, tolerance zero).
- From the official file: 12000 monthly records; discharge mean 210.2793 m3/s,
  max 765.486, min 16.926, first 21.975, last 60.864.
- From our own run (no official file; two clean runs were byte-identical):
  suspended load mean 23.4475 kg/s (max 439.447), bedload mean 53.3662 kg/s;
  HYDRO.LOG says Qbar 218.20 m3/s, Qsbar 24.33 kg/s, Qpeak 6590.8 m3/s,
  basin area 9440.46 km2.
- Finished normally: return code 0 and the line `HydroTrend 3.0 finished.`

Both server engines pass: `/mnt/disk1/Hydrocraft_server/models/HydroTrend/bin/hydrotrend`
(the preflight one, used to record) and the dissection-toolkit build `_build/hydrotrend`.

## Known KI gaps (noted, not fixed)
1. **Long paths crash the model.** HydroTrend keeps the output path in fixed C buffers
   (98 chars for the out dir, 80 for the file name start). `run_hydrotrend.py` passes the
   paths as given and does not set the working dir, so a normal absolute temp path
   (about 90 chars) makes the model print "output directory is too long", misread
   HYDRO.IN and die with a crash (rc -11). This case works around it by calling the tool
   from inside the temp dir with short relative paths. Results are not changed by this
   (output matches the official file byte for byte).
2. **No tool writes HYDRO.IN.** SKILL.md lists `generate_hydro_in.py` for "Parameter
   Assembly", but it is not in `tools/`. That is why this case uses the shipped example.
3. **`parse_hydrotrend_output.py` assumes daily rows.** On this case (monthly averaging)
   it reports `n_days 12000, n_years 33` instead of 12000 months / 1000 years, gives
   wrong dates, and leaves the `Cs` column empty (HYDROASCII.CS has one column per grain
   size). SKILL.md also calls the ASCII outputs "Daily". So `run_reference.py` reads the
   output files directly instead of using the parse tool.
