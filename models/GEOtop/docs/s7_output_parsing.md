# s7: Output Parsing

## Purpose

Extract and interpret GEOtop model outputs from the various output file formats
into tidy, analysis-ready CSV files. Compute summary statistics and prepare data
for validation against observations.

## Inputs

| Input                | Source               | Format    | Notes                |
|----------------------|----------------------|-----------|----------------------|
| Basin output         | output-tabs/basin*.txt | CSV     | Basin-averaged series|
| Point output         | output-tabs/point*.txt | CSV     | Per-point series     |
| Soil profiles        | output-tabs/soilTz*.txt | CSV    | Matrix format        |
| Snow profiles        | output-tabs/snowT*.txt  | CSV    | Matrix format        |
| Discharge            | output-tabs/discharge*.txt | CSV | Flow time series     |

## Outputs

| Output               | File                    | Format   | Notes               |
|----------------------|-------------------------|----------|---------------------|
| Tidy basin CSV       | results/basin.csv       | CSV      | Long format          |
| Tidy point CSV       | results/point.csv       | CSV      | Long format          |
| Soil profile CSV     | results/soil_profile.csv| CSV      | Long format          |
| Summary JSON         | results/summary.json    | JSON     | Run statistics       |

## Procedure

### 1. Parse Basin Output

GEOtop basin files have headers like `Tair[C]`, `LE[W/m2]`.

```bash
python parse_output.py \
    --sim-dir /path/to/sim_folder \
    --output-type basin \
    --variables "Tair,LE,H,SWin,LWin,Evap_surface,Prain_below_canopy" \
    --output results/basin.csv
```

**Key basin variables:**

| Variable                  | Unit   | Description                         |
|---------------------------|--------|-------------------------------------|
| Prain_below_canopy        | mm     | Rainfall reaching ground            |
| Psnow_below_canopy        | mm     | Snowfall reaching ground            |
| Pnet                      | mm     | Net precipitation                   |
| Tair                      | C      | Air temperature                     |
| Tsurface                  | C      | Surface temperature                 |
| Evap_surface              | mm     | Surface evaporation                 |
| Transpiration_canopy      | mm     | Canopy transpiration                |
| LE                        | W/m2   | Latent heat flux                    |
| H                         | W/m2   | Sensible heat flux                  |
| SW                        | W/m2   | Net shortwave radiation             |
| LW                        | W/m2   | Net longwave radiation              |
| SWin                      | W/m2   | Incoming shortwave                  |
| LWin                      | W/m2   | Incoming longwave                   |
| Mass_balance_error        | mm     | Numerical water balance error       |
| Mean_Time_Step            | s      | Adaptive time step (if < 900, solver struggled) |

### 2. Parse Soil Profiles

Soil profiles are in matrix format: each row is a time step, each column a soil layer.

```bash
python parse_output.py \
    --sim-dir /path/to/sim_folder \
    --output-type soil_profile \
    --point 1 \
    --variables "temperature,liquid_water" \
    --output results/soil_profile.csv
```

Output format (long/tidy):
```
datetime,variable,layer,value,unit
02/10/2009 01:00,temperature,1,12.5,C
02/10/2009 01:00,temperature,2,11.8,C
02/10/2009 01:00,liquid_water,1,0.35,-
```

### 3. Parse Snow Profiles

```bash
python parse_output.py \
    --sim-dir /path/to/sim_folder \
    --output-type snow_profile \
    --point 1 \
    --output results/snow_profile.csv
```

### 4. Generate Run Summary

```bash
python parse_output.py \
    --sim-dir /path/to/sim_folder \
    --output-type summary \
    --output results/summary.json
```

## Verification

- [ ] Output CSV has correct datetime parsing (European DD/MM/YYYY)
- [ ] No residual -9999 values in parsed data (should be NaN)
- [ ] Temperature values are physically reasonable
- [ ] Energy balance closure: |Rn - G - H - LE| is small
- [ ] Mass balance error is negligible (< 0.1 mm/day)
- [ ] Mean_Time_Step is close to the configured value (900s) -- if much smaller,
      the solver was struggling

## Traps

| Trap ID | Description                                      | Severity |
|---------|--------------------------------------------------|----------|
| dt_019  | Date parsed as MM/DD instead of DD/MM in output  | silent   |
| dt_020  | Output columns shifted if optional vars present  | silent   |

## Diagnostic Checks

### Energy Balance Closure
```python
# Rn = SW + LW (net shortwave + net longwave)
# Rn = H + LE + G
# Check: abs(SW + LW - H - LE) should be small
closure = df['SW'] + df['LW'] - df['H'] - df['LE']
print(f"Energy balance residual: {closure.mean():.1f} W/m2")
```

### Water Balance Check
```python
# P_in = ET + Q + dS + error
total_precip = df['Pnet'].sum()
total_et = df['Evap_surface'].sum() + df['Transpiration_canopy'].sum()
mass_error = df['Mass_balance_error'].sum()
print(f"Precip: {total_precip:.1f} mm, ET: {total_et:.1f} mm, Error: {mass_error:.3f} mm")
```

### Soil Moisture Sanity
```python
# All values should be between residual and saturated content
theta = soil_df[soil_df['variable'] == 'liquid_water']['value']
print(f"Soil moisture: min={theta.min():.3f}, max={theta.max():.3f}")
# Expect: 0.02 < min, max < 0.60
```

## Example

After running Matsch B2 test case:
```bash
python parse_output.py \
    --sim-dir tests/1D/Matsch_B2_Ref_007 \
    --output-type summary \
    --output results/matsch_summary.json
```

Expected summary output:
```json
{
  "sim_dir": "tests/1D/Matsch_B2_Ref_007",
  "success_marker": true,
  "output_files": {
    "basin0001.txt": {"n_lines": 745, "size_bytes": 98234},
    "point0001.txt": {"n_lines": 745, "size_bytes": 156789}
  }
}
```
