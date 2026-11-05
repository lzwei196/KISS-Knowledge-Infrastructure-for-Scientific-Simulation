# s7 Output parsing

## Purpose
Turn the engine's text report (and PRINT = 3 CSV files) into numbers in known units.

## Inputs
A KINEROS2 `.out` file; optional PRINT = 3 element CSV files.

## Outputs
JSON with: run header and multipliers; engine warnings; per printed element (PRINT >= 1) contributing
area, peak flow + time, peak sediment discharge, element water/sediment balance, and the hydrograph
table for PRINT = 2 (`time_min, rain_rate, outflow_rate, discharge[, sediment_discharge]`); the event
volume summary; the tabular summary; and `si` (m3/s, m3, mm, ha, t/ha). Optional CSV per hydrograph.

## Procedure
`tools/parse_kineros2_output.py run.out --json parsed.json --hydrograph-dir hyd/ [--csv CHAN2.CSV]`
(`run_kineros2_engine.py` already does this for every run.)

## Verification
- Exit 3 when the output shows an engine failure or has no event summary.
- On EX1 (PRINT 2/3 variants): plane 1 peak 0.7407505 m3/s at 35 min, peak sediment 24.39 kg/s at 36 min,
  201 hydrograph rows; channel CSV 201 rows, columns Time, Rainfall, Outflow (mm/hr), Outflow (cu m /s),
  Total Sed, three class columns.

## Units as printed (ENGLISH in brackets)
| Quantity | Unit |
|---|---|
| discharge (hydrograph, peak) | cu m /s [cu ft/s] |
| rain_rate, outflow_rate, peak rate | mm/hr [in/hr] over the element's contributing area |
| event depths | mm [in] over the TOTAL watershed area |
| event volumes | cu m [cu ft] |
| sediment yield | tons/ha [tons/ac = short tons per acre] |
| sediment discharge | kg/s [lb/s] |
| areas | ha [ac] in the summary; m^2 [ft^2] in the tabular summary |

## Traps
- Event depths are over the MODEL area; a gauge's mm-per-area series uses the gauge's nominal area.
  Compare in absolute units (dt_kineros2_033).
- The peak in the "Peak flow =" line is from the compute steps (WG11 668.4023 cfs at 64.7 min); the
  3-min table's largest value is lower (665.28 cfs at 66 min). Report the line for peaks, use the table
  for NSE (dt_kineros2_048).
- "rating exceeded" warnings are expected for any flowing channel unless CHR = Y (dt_kineros2_038).
- PRINT = 3 file names are upper-cased (dt_kineros2_034); their header fields are padded before quotes.

## Example
```
python3 tools/parse_kineros2_output.py out/wg11/wg11.out --json out/wg11/parsed.json --hydrograph-dir out/wg11/hyd
```
