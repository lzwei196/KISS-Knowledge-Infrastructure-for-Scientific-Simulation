# Stage 1: Forcing preparation

`convert_forcing_to_topmodel.py` requires complete precipitation and actual temperature samples. Its strict source adapter reads native subdaily CMFD precipitation rates and Kelvin temperatures at the supplied representative point, validates aligned timestamps and every sample against the native step the files DECLARE (CMFD V0200: `03hr` in the file name, "3-hourly" in the title, "Category: B-01: 03hr" in the description; all must agree), then aggregates complete days. The step is never guessed from the timestamps present, so a regularly thinned series (e.g. every other 3-hourly sample) fails instead of passing as 6-hourly. Files with no declared step fail. It uses the sampled temperature minimum/maximum for Hargreaves; it never substitutes mean ±5 °C or turns missing rain/PET into zero.

The older shared daily adapters can discard missing substeps or substitute extrema. They are bypassed here. **The CLI currently supports native subdaily CMFD only**; daily-mean-only files and the legacy MSWX/NASA POWER routes fail rather than claim unsupported source quality. Adding another adapter requires original extrema and completeness checks before aggregation. The conversion function can still consume explicitly supplied, validated daily arrays with Tmin/Tmax/Tmean and a declared calendar.

The spatial selection is the nearest source grid cell to `--lat/--lon`, not an area mean. An optional shapefile is reference geometry only. A representative point outside the source grid is rejected. Use an independently prepared and documented basin-average series through the conversion function when a point sample is inadequate.

Hargreaves uses source Tmin/Tmax/Tmean in °C and FAO-56 extraterrestrial radiation derived from latitude/day of year. Ra is converted from MJ m-2 day-1 to equivalent mm/day with 0.408. Tmin <= Tmean <= Tmax is required; equal extrema legitimately give zero Hargreaves PET. Polar-day/night trigonometry is bounded before arccos. There is no made-up minimum temperature range.

For `N = 24 / --dt-hours` steps/day (an exact positive integer), each row contains **depth per step in metres**:

| Quantity | Conversion |
|---|---|
| Precipitation | daily mm / 1000 / N |
| PET | daily mm / 1000 / N |
| Provided Qobs | Q in m3/s × 86400 / basin area in m2 / N |

Daily amounts are distributed uniformly within a day when N > 1, an explicit temporal assumption recorded in provenance. This is not gap filling. The native BMI header is always `nstep 1.0` because its update routine uses dt as the input-row index increment. Physical step length is separate; rate parameters must use that physical time basis. Existing parameter units must not be changed just to make a run pass.

Supplied observations require complete, finite, nonnegative daily Q and a finite positive basin area. Missing sentinel values fail; true zero discharge is retained. If no observations are supplied, the native Qobs column is a format placeholder of zeros, labeled `not_supplied_placeholder_not_for_scoring` in the sidecar. Do not interpret the native internal objective or these placeholders as observed skill. Score only against independently identified observations, retaining valid dry days.

```bash
python tools/convert_forcing_to_topmodel.py \
  --forcing-dir KISSPATH_FORCING/Data_forcing_03hr_010deg/ \
  --source cmfd --start-date 1980-01-01 --end-date 1990-12-31 \
  --lat 33.0 --lon 117.0 --dt-hours 24 \
  --output data/inputs.dat
```

`inputs.dat.provenance.json` records the source files/point, original timestep, PET method, physical timestep, redistribution assumption, missing-fill count (zero), observation mode and output hash. Keep it with the input file. Validation happens before writing; output/sidecar writes are not a multi-file filesystem transaction. The existing 0.5 m/step rain ceiling is retained. CLI input or output validation errors return a nonzero exit code.
