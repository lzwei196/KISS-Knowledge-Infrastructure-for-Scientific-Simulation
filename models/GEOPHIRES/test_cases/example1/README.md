# GEOPHIRES — foundation test case: "example1"

Authentic foundation case: the official **example1** that ships with GEOPHIRES-X
(`tests/examples/example1.txt`). It is an EGS (enhanced geothermal) electricity case:
a multiple parallel fractures reservoir at 3 km depth (50 degC/km), 2 production and
2 injection wells at 55 kg/s, Ramey wellbore heat loss, a supercritical ORC power plant,
30-year life and fixed charge rate economics.

GEOPHIRES-X ships the official expected result next to it (`tests/examples/example1.out`),
and its own test suite checks every run against that file. This case does the same.
`inputs/example1.txt` and `reference/example1.out` are the unmodified files from the
GEOPHIRES-X git tree (taken with `git show HEAD:...`).

| | |
|---|---|
| Engine | GEOPHIRES-X 3.11.25 (NREL), run as `python -m geophires_x` |
| Source | NREL/GEOPHIRES-X, `tests/examples/example1.txt` + `example1.out`, commit 870971c8 |
| Licence | MIT (GEOPHIRES-X, NREL) |
| KI | `GEOPHIRES` (run tool `tools/run_geophires.py`, parse tool `tools/parse_geophires_output.py`) |

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=engine missing
```
It needs a Python that can import `geophires_x` and `geophires_x_client`. Lookup order:
`--geophires-python` -> `$GEOPHIRES_PYTHON` -> `python3` on PATH -> server default
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GEOPHIRES/venv/bin/python`
(GEOPHIRES-X is not installed in python_env). The script copies `inputs/example1.txt` to a
fresh temp dir, runs it through the KI's own `tools/run_geophires.py`, checks the result,
then deletes the temp dir. It takes about 3 seconds.

## How the result is checked
1. **Finished normally**: the run tool exits 0 with status `success`, and the `.out` starts
   with the `***CASE REPORT***` banner.
2. **Official comparison** (same as GEOPHIRES-X `tests/test_geophires_x.py::test_geophires_examples`):
   both the new `.out` and `reference/example1.out` are read with
   `geophires_x_client.GeophiresXResult`, the `metadata` and `Simulation Metadata` parts
   (version, date, run time) are dropped, and the two result dicts must be **exactly equal**.
   example1 is not on the suite's "almost equal" list, so no tolerance is allowed.
3. **14 numeric checks** (values taken from the official `example1.out`, tolerance 0):
   - average net electricity 5.39 MW; electricity breakeven price (LCOE) 8.82 cents/kWh
   - project NPV -35.81 MUSD; project IRR -2.85 %
   - production temperature max 167.3 / min 165.3 degC; average reservoir heat extraction 53.52 MW
   - total capital costs 47.99 MUSD; total O&M 1.35 MUSD/yr; average annual net electricity 42.51 GWh
   - power profile has 30 years; year-30 net power 5.4179 MW; year-30 share of heat mined 14.07 %;
     final project net cashflow -18.35 MUSD
4. **KI parser cross-check**: `tools/parse_geophires_output.py` must give the same net power,
   LCOE, NPV and IRR as the official parser.

Recorded 2026-10-05. Two clean runs both matched the official file exactly; only the
version/date/run-time lines differ (the official file was written by GEOPHIRES 3.9.28 and
the suite still uses it unchanged for 3.11.25), plus whitespace that the official parser ignores.

## Known KI gaps (not fixed here)
- `tools/parse_geophires_output.py` does not find the year-by-year production profile in a
  GEOPHIRES-X 3.11 `.out` ("Production profile section not found"), so `--csv` writes nothing.
  It still exits 0. The case therefore uses the official `GeophiresXResult` parser for the
  checks and uses the KI parser only for the four headline numbers it reads correctly.
- The same parser splits the text value "End-Use Option: Electricity" into value `E` and
  unit `lectricity`.
- `tools/run_geophires.py` has no engine lookup of its own: it uses `--venv <dir>` or the
  Python that starts it. `run_reference.py` starts it with the engine Python.
