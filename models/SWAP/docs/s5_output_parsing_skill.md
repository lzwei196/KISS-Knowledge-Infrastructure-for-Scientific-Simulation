# S5: SWAP Output Parsing

## Purpose
Extract and structure SWAP output files into standardized CSV format for analysis, visualization, and comparison with observations.

## Inputs
- **SWAP output directory**: Contains result.blc, result.inc, result.vap, result.csv, etc.
- **Output prefix**: Value of OUTFIL parameter (default: "result")

## Outputs
- `water_balance.csv`: Annual water balance components (cm)
- `daily_increments.csv`: Daily flux increments (cm)
- `swap_timeseries.csv`: Custom CSV output (if SWCSV=1)
- `summary.json`: Simulation summary with totals

## Procedure
1. **Parse .blc file** (detailed yearly water balance):
   - Extract components: Rain, Irrigation, Runoff, Transpiration, Evaporation, Drainage
   - All values in cm (centimeters of water)
   - Check balance closure: Sum_In ≈ Sum_Out + ΔStorage

2. **Parse .inc file** (water balance increments):
   - Daily or output-interval records
   - Columns vary by SWAP version; common: date, daynr, rain, irrig, interc, runoff, drainage, dstor, epot, eact, tpot, tact, qbottom, gwl
   - Units: cm for depths, cm for cumulative fluxes

3. **Parse .vap file** (soil profiles):
   - Profiles at each output date
   - Columns: depth (cm), theta (m³/m³), h (cm), K (cm/d)
   - Multiple profiles per file, separated by date headers

4. **Parse native CSV** (if SWCSV=1):
   - Comma-separated with header row
   - Units specified in comment line above header
   - Variables as listed in INLIST_CSV

5. **Generate summary JSON**:
   - Total rainfall, ET, drainage over simulation
   - Number of years, daily records
   - Key ratios: ET/Rain, Drainage/Rain

## Verification
- Water balance closure: |Sum_In - Sum_Out - ΔStorage| < 0.1 cm per year
- No NaN values in parsed output
- Daily records count matches simulation days
- Soil moisture values in 0-1 range (not negative, not > OSAT)

## Traps

### TRAP 1: .blc balance includes storage change
The In/Out sums in .blc may not be equal because storage change is implicit. The difference (In - Out) equals the change in soil water storage over the balance period.

### TRAP 2: Units in .inc are cumulative
The .inc file reports cumulative values over the output interval (set by PERIOD). To get daily rates, divide by the interval length. If PERIOD=1, values are daily.

### TRAP 3: Mixed unit conventions
- Rainfall, ET, drainage in .blc: cm (centimeters)
- Soil moisture (theta): dimensionless (cm³/cm³)
- Pressure head (h): cm (negative = unsaturated)
- Hydraulic conductivity (K): cm/day
- GWL: cm below surface (negative)

### TRAP 4: Date format in output
SWAP outputs dates as DD-Mon-YYYY (e.g., "01-Jan-2002") or as day number. Parsing must handle both formats.

### TRAP 5: Multiple drainage levels
If DRAMET=3 (multi-level), drainage appears as separate entries per level in .blc. Sum all levels for total drainage.

## Example
```python
# Parse water balance from .blc
# Expected output for Hupselbrook 2002:
# {"year": 2002, "rain": 84.18, "irrigation": 0.50,
#  "interception": 3.74, "transpiration": 38.17,
#  "soil_evaporation": 16.69, "drainage": 22.11,
#  "sum_in": 84.68, "sum_out": 80.72}
```
