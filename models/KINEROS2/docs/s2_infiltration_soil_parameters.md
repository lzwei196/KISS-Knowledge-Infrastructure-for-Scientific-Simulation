# s2 Infiltration and soil parameters

## Purpose
Set each pervious element's Smith-Parlange infiltration parameters (KS, G, DIST, POR, ROCK, CV, SAT,
optional second layer) so the engine partitions rain into infiltration and runoff.

## Inputs
- Site lat/lon (HWSD lookup) or a USDA texture class.
- The parameter file to fill (copy-first).
- Event antecedent moisture for SAT (not derivable from soil maps).

## Outputs
JSON with KS (mm/hr or in/hr), G (mm or in), DIST, POR, ROCK and their provenance; optionally a
copied parameter file with these values written into the chosen elements.

## Procedure
1. `tools/kineros2_soil_params.py --hwsd --lat 31.72 --lon -110.06 --units english --json soil.json`
   - POR, DIST, G from the KINEROS2 manual's Table 1 (Infilt.pdf; Rawls et al. 1982, G in cm -> mm).
   - KS from `lookup_hwsd()['hydraulics']['ksat_cm_hr']` (Rawls class value) x (1 - ROCK), as the manual instructs;
     ROCK = HWSD gravel volume % / 100.
2. To write them: add `--apply-to case.par --out case_soil.par [--elements PLANE|10,136]`. Only the
   upper-layer value (index 1) is replaced; a second layer stays as it was (edit with
   `edit_kineros2_par.py set --set ID:KS:2=...`).
3. Set SAT per element (`edit_kineros2_par.py set --set PLANE:SAT=0.2`) or per gage in the .pre.
4. Channels: bed material is not hillslope soil -- set channel KS/G from field data (WG11 uses KS ~8-11 in/hr, G ~2.2-2.8 in).

## Verification
- The tool validates DIST <= 1.5 and re-validates the written file with the engine's rules.
- Run the case and read `event_summary.plane_infiltration` vs rainfall in `run_result.json`.

## Traps
- Texture-class KS is far below the field-calibrated WG11 values: HWSD at 31.72N, 110.06W gives sandy clay loam,
  KS 0.135 in/hr after the rock factor, while the ARS WG11 file uses 0.40-0.52 in/hr (before its 0.5 multiplier).
  Treat class values as a starting point for calibration, not truth (dt_kineros2_053).
- G = 0 makes the element infiltrate at constant KS and skips SAT/DIST/POR.
- KS = 0 (or missing) makes the element IMPERVIOUS -- a missing KS tag is not an error.
- `KE` is read before `KS` and also switches the element to the RHEM sediment method (dt_kineros2_043).
- SAT >= SMAX (default 0.95) sets G to 0 inside the engine (saturated start).
- ALF picks the infiltration function: <= 0.04 Green-Ampt, >= 0.96 Smith-Parlange, else 3-parameter (default 0.8).

## Example
```
python3 tools/kineros2_soil_params.py --texture loam --units metric --apply-to examples/ars_samples/EX1.PAR --out ex1_loam.par
python3 tools/run_kineros2_engine.py --par ex1_loam.par --rain examples/ars_samples/EX1.PRE --tfin 200 --dt 1 --out-dir out/ex1_loam
# plane infiltration 41.51 -> 32.27 mm, outflow 35.30 -> 44.51 mm (loam KS 13.2 mm/hr, G 110 mm vs EX1's 10 mm/hr, 500 mm)
```
