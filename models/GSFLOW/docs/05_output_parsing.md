# Stage 7: Output Parsing

## Purpose
Extract simulated time series from GSFLOW output files and convert to
standard CSV format for analysis, visualization, and validation against
observed data.

## Inputs
- GSFLOW output files:
  - CSV basin summary (from `csv_output_file` control parameter)
  - Statvar output (from `stat_var_file` control parameter)
  - MODFLOW listing file (water budget)
  - SFR gage files (streamflow at specified segments)
- Basin area (km²) for runoff→discharge conversion

## Outputs
- Clean CSV time series: `date, variable1, variable2, ...`
- Converted discharge in m³/s (if runoff in inches, converted using basin area)

## Procedure

1. **Identify output format:**
   - CSV output: most straightforward, comma-delimited with header
   - Statvar output: fixed-width, needs header parsing
   - MODFLOW listing: volumetric budget summaries, text parsing

2. **Parse CSV basin summary:**
   ```python
   import pandas as pd
   df = pd.read_csv("basin_summary.csv")
   # Columns may include: Date, basin_cfs, basin_ppt, basin_actet, ...
   ```

3. **Parse statvar output:**
   ```python
   # Header: n_vars, then var_name element_id pairs
   # Data: YYYY MM DD HH MM SS MS val1 val2 ...
   records = parse_statvar_output("statvar.out")
   ```

4. **Convert units for validation:**
   - `basin_cfs` (ft³/s) → m³/s: multiply by 0.028317
   - `basin_stflow` (inches/day) → m³/s:
     `Q = stflow_in × basin_area_km² × 25.4 × 1000 / 86400`
   - `basin_ppt` (inches) → mm: multiply by 25.4

5. **Handle multiple output segments:**
   - SFR gage files provide flow at specific stream segments
   - Match segment ID to outlet location for validation

6. **Quality checks on extracted data:**
   - No constant values (indicates parsing error)
   - No negative streamflow
   - Date continuity (no gaps)
   - Values within physically reasonable ranges

## Verification
- Output CSV has expected number of records (= simulation days)
- Date range matches simulation period
- Streamflow values are non-negative
- Mean annual discharge is physically plausible:
  - Bengbu (~121,330 km²): ~500–2000 m³/s mean annual
  - Sagehen Creek (~27 km²): ~0.1–1.0 m³/s mean annual
- Water balance: precipitation ≈ ET + runoff + ΔStorage (within 10%)

## Traps
- **Column ordering:** CSV column names may vary between GSFLOW versions.
  Always parse by column name, not position.
- **Date format:** May be `YYYY-MM-DD` or `YYYY,MM,DD` depending on
  GSFLOW version and control file settings.
- **Scientific notation:** Values may be in scientific notation (e.g., `1.5E+02`).
  Python's `float()` handles this, but custom parsers may not.
- **Unit mismatch in validation:** If you compare `basin_cfs` directly
  to observed m³/s without converting, results will be off by ~35×.
- **Spinup period:** Discard first 1–3 years from analysis.
  Including spinup artificially degrades validation metrics.
- **Missing data gaps:** If GSFLOW fails mid-run, output may be truncated.
  Check that output covers the full simulation period.
- **Multiple output files:** Different control file settings produce
  different output files. Check which output mechanism is enabled:
  - `basinOutON_OFF` → basin CSV output
  - `statsON_OFF` → statvar output
  - Both may be enabled simultaneously

## Example
```bash
# Parse GSFLOW CSV output and compute NSE
python parse_gsflow_output.py \
    --csv-file output/prms/basin_summary.csv \
    --csv-out extracted_discharge.csv \
    --variables basin_cfs \
    --basin-area-km2 121330

# Compare with observations
python -c "
import pandas as pd
sim = pd.read_csv('extracted_discharge.csv', parse_dates=['date'])
obs = pd.read_csv('/path/to/observations.txt', sep='\t',
                   names=['stcd','date','z','Q','name'],
                   parse_dates=['date'])
merged = pd.merge(sim, obs, on='date')
nse = 1 - ((merged['basin_cfs_cms'] - merged['Q'])**2).sum() / \
          ((merged['Q'] - merged['Q'].mean())**2).sum()
print(f'NSE = {nse:.3f}')
"
```
