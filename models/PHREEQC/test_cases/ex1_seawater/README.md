# PHREEQC — foundation test case: "ex1_seawater"

Official foundation case: **USGS PHREEQC example 1, "Add uranium and speciate seawater"**.
It takes the seawater analysis of Nordstrom and others (1979) plus 3.3 ppb uranium, adds
uranium species and the mineral uraninite in the input file, and works out the speciation,
charge balance and saturation indices at 25 °C. There is no reaction step.
`inputs/` are the unmodified official files; USGS also ships the expected output, kept here
as `reference/ex1.out`.

| | |
|---|---|
| Engine | PHREEQC 3.8.9 (banner date October 13, 2025), built from usgs-coupled/phreeqc3 git 311a485 |
| Source | https://github.com/usgs-coupled/phreeqc3 `examples/ex1`, `examples/ex1.out`, `database/phreeqc.dat` (commit 311a485, 2026-03-03) |
| Database | `phreeqc.dat` from the same tree (the database the official ex1.out was made with) |
| Licence | USGS public software, User Rights Notice (`NOTICE.TXT`, copied unchanged from `doc/NOTICE.TXT`) |
| KI | `PHREEQC` |

## Files
- `inputs/ex1` — official input (`git show 311a485:examples/ex1`)
- `inputs/phreeqc.dat` — official database (`git show 311a485:database/phreeqc.dat`)
- `reference/ex1.out` — official USGS expected output (`git show 311a485:examples/ex1.out`)

## Run
```
python run_reference.py    # finds phreeqc (--phreeqc-bin, $PHREEQC_BIN, PATH, server default); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir and runs `phreeqc ex1 ex1.out phreeqc.dat` there.
It tries the KI tool `tools/run_phreeqc.py` first and runs the engine directly if that tool
fails (it does fail today, see below). The run takes well under a second.

## Expected results
All values come from the official USGS `ex1.out`; tolerance is one unit in the last digit
printed there.
- Whole output: every line equals the official `ex1.out` (338 lines, about 900 numbers),
  except the 3 header lines that show file paths and the final "End of Run after ...
  Seconds" timing lines. On 2026-10-05 the run matched the official file exactly apart
  from those lines; two runs gave the same result.
- Finished normally: return code 0, "End of Run" line, no ERROR.
- Description of solution: pH 8.220, pe 8.451, specific conductance 52918 µS/cm,
  density 1.02326, ionic strength 0.6737, total carbon 2.232e-03, electrical balance
  7.936e-04 eq (0.07 %), 7 iterations, total H 111.0148, total O 55.63069.
- Uranium: total 1.437e-08 mol/kg; main species UO2(CO3)3-4 at 1.267e-08; HCO3- 1.613e-03.
- Saturation indices: 37 phases; calcite 0.78, dolomite 2.49, uraninite -12.77.

## Known KI gaps (not fixed here)
- `tools/run_phreeqc.py` crashes on the official `phreeqc.dat`: its element check opens the
  database as UTF-8, but the file has a Latin-1 degree sign (byte 0xb0), so Python stops
  with `UnicodeDecodeError` before PHREEQC is started. So the case runs the engine directly.
- `tools/parse_output.py` reads the species table correctly (used here for the
  UO2(CO3)3-4 and HCO3- values), but returns empty lists for the saturation index table and
  the solution composition table of this output (it loses its place at the blank line /
  column-header line). Those values are read straight from the output text here.
