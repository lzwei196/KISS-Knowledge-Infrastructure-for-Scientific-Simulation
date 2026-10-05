# APEX — foundation test case: "riesel_tx"

Authentic foundation case: the official **Riesel, Texas** example (`ex1_RiselTX`) that
Texas A&M AgriLife ships in the "APEX v.0806 Editor" download. It is the same example
the KI copies as its template (`tools/s1_setup_workspace.py`). One 10-year run
(1998-2007) of a small Blackland watershed with 4 subareas: three crop fields with
corn / wheat / oats / sorghum rotations and one rangeland area.
`inputs/` are the unmodified official files (41 files, CRLF line ends kept).

| | |
|---|---|
| Engine | APEX0806 (`APEX0806.exe`, Windows PE32, 2015-05-01 build), run with wine 9.0 |
| Source | https://epicapex.tamu.edu/media/1xid5waj/apex-0806-editor-09232015.zip, folder `ApexEditor(09232015)/ex1_RiselTX` (zip sha256 `4295d621...cbde`) |
| Licence | Free public download from Texas A&M AgriLife; the zip has no licence file |
| KI | `APEX` (run with `tools/s6_run_apex.py`, read with `tools/s7_parse_output.py`) |

## Run
```
python run_reference.py    # needs wine + APEX0806.exe (--apex-bin, $APEX_BIN, PATH, or server default); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` and the engine to a fresh temp dir, runs APEX through the KI's
`tools/s6_run_apex.py`, checks the results, then deletes the temp dir. A run takes
about 3 seconds.

## Expected results
**Official reference.** The download also ships four small side outputs that the APEX
team's own run wrote on 2015-09-04: `fort.102` (end-of-run totals, manure and
fertilizer balance), `fort.108` (yearly watershed water/nutrient balance, 10 years x
56 columns), `fort.112` (outflow) and `fort.128`. They are kept in `reference/`. Our run
must give the same printed numbers in all four (tolerance 0). It does: the files are
byte-identical.

**Own run (recorded 2026-10-05).** The download has no `OUTPUT.*` files, so these values
come from our run. Two clean runs gave identical outputs apart from the date/time
stamp lines.
- finished normally: rc=0, no EPICERR error, `OUTPUT.OUT` has both end balances and "TOTAL RUN TIME"
- water balance error printed by APEX (PER): -0.000295 %
- `OUTPUT.ACY`: 51 crop-year rows, years 1998-2007
- corn: 14 harvests, mean yield 6.26 t/ha, max 9.68 t/ha, mean biomass 18.50 t/ha
- `OUTPUT.AWS`: total outlet flow QTS over 10 years 2482.91 mm

A missing engine, wine or pandas is reported (exit 3), never faked.

## KI gaps (status 2026-10-06)

No KI tool fix for APEX has landed in this checkout since the case was made (last APEX commit `8856df7`), so every item below is still open.

- **Still open:** The KISS copy of the KI has no `examples/ex1_RiselTX/` and no `reference/APEX0806.exe`
  (`models/APEX/examples/` holds a different, older pasture file set). So
  `tools/s1_setup_workspace.py` cannot run from the KISS checkout; this case copies its
  own `inputs/` instead and calls `s6` directly.
- **Still open:** `SKILL.md` says the example data come from pyAPEXSCU (Marena, Oklahoma grazing study).
  The live template is in fact this Texas A&M Riesel TX example.
- **Still open:** `s6_run_apex.py` and `s7_parse_output.py` texts and error messages still say "apex1501",
  but they run and read APEX0806.
- **Still open:** `s7_parse_output.parse()` puts tables from `OUTPUT.OUT` and `OUTPUT.ACY` in one frame
  (here 931 + 51 rows, with mixed columns). This case keeps only rows where
  `__source__ == "OUTPUT.ACY"`.
- **Still open:** The disk1 KI folder `examples/ex1_RiselTX/` also holds leftover `OUTPUT.*` and `fort.*`
  from local runs; `s1` deletes them after copying. Its input files are identical to
  the official download.
