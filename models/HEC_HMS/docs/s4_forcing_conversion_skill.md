# S4: Forcing conversion

The converter produces daily `precip_mm`, `temp_c`, `pet_mm` columns from complete CMFD source cells and an explicitly supplied PET series. It never truncates to the shorter input, fills missing weather, guesses units from magnitude, or assumes a 10 °C temperature range/radiation to invent PET. All validation completes before output files are created or replaced.

Inputs:

- `--forcing_dir`: NetCDF files named by variable (`prec`, `temp`) and year, with explicit units, daily time coordinates and a regular geographic grid. Geographic lon/lat or CF-described x/y coordinates are supported; every accepted coordinate must declare degree units (`degrees_east`/`degrees_north` or CF variants). Radian, projected or undeclared units fail; they are not converted. A single daily timestamp may label the mean at a non-midnight time (e.g. CMFD 10:30); its calendar date is retained. Multiple samples on a day are rejected, not averaged here. Each value must cover a whole day: declared time bounds must be midnight-to-midnight 24 h on the labelled date; without bounds, labels must be exactly 24 h apart (a file with one label needs global `frequency = day`). A time `cell_methods` other than mean/sum (e.g. `time: point`) fails. A partial-day value, such as one hourly mean per day, is rejected instead of being scaled to a daily total.
- `--basin_shp`: valid basin polygons with a declared CRS. Source grid extent must cover the basin. Covered grid centers are averaged with cos(latitude) area weights. Every selected cell/date must be finite and physically valid; cells outside the basin are excluded explicitly. This center-selection approximation does not resolve fractional boundary cells.
- `--start_date`, `--end_date`: inclusive daily period. No missing, duplicate, reversed or shifted source dates are accepted.
- `--pet_csv`: mandatory `date,pet_mm` file in mm/day covering the requested period. Retain the actual source or chosen derivation and its parameters with this file. Published monthly evaporation may be converted using its documented coefficients and calendar; an absent source must not be replaced by a constant. The tool never switches ET methods.
- `--temperature_mode required` (default) validates temperature. `unused` omits the column and temperature input entirely, only for a native model configured with no temperature-dependent process. It does not write substitute temperatures.

Precipitation units are read from metadata: `kg m-2 s-1`/`mm/s` ×86400, or daily `mm/day`/`mm d-1`/`mm` unchanged. Kelvin is converted by subtracting 273.15; explicitly declared Celsius is unchanged. Unsupported/absent units fail. Negative precipitation and source sentinels are rejected before averaging, as is any active-cell value outside the variable's NetCDF `valid_range`/`valid_min`/`valid_max` (read in packed units when the variable is packed). Valid zero and small positive rain remain unchanged. Subdaily rate files must be converted with a source-aware daily aggregation beforehand.

```bash
python tools/convert_forcing_to_hms.py \
  --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
  --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --start_date 1980-01-01 --end_date 1990-12-31 \
  --pet_csv /path/to/source_documented_daily_pet.csv \
  --output_dir ./forcing_out
```

Outputs are `basin_avg_forcing.csv` and `basin_info.json`. The latter records source hashes, selected cells, spatial method, unit declarations, PET source/hash, zero fill count, period and CSV hash. Both files must travel together. Input validation is complete before writing, but a filesystem I/O failure is not a multi-file transaction.

For native HEC-HMS, import the CSV quantities into the project's matching gages/DSS records with explicit interval, units and temporal support. The CSV is not itself a native HEC-HMS project. The existing `run_hec_hms.py` is a separate Python approximation and does not satisfy the official model execution policy.

The repair tracer uses the official HEC-HMS 4.12 bundled Tifton project, its recorded cumulative rainfall (converted to increments), and its specified monthly-pan PET method. Daily rainfall passes through this converter and returns to DSS using the original observed hourly proportions, preserving those source values. The native run has temperature disabled, consistent with `unused`. A real CMFD read separately checks geographic x/y coordinates and precipitation-rate conversion. This is an input integration test, not a field calibration or equivalence claim for the Python approximation.
