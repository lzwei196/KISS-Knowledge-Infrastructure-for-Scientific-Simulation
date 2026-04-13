# Skill: Parameter Estimation

## Purpose

Generate an initial parameter vector (theta) and initial storage vector (S0)
for a chosen MARRMoT model structure by mapping catchment soil and land
properties to hydrologically meaningful parameter values within the model's
defined ranges.

MARRMoT models have between 1 and 24 parameters, each with defined min/max
bounds stored in the model's `parRanges` property. This skill produces a
physically plausible starting point for calibration or exploratory runs.

## Inputs

| Input               | Source            | Format        | Unit            |
|---------------------|-------------------|---------------|-----------------|
| Model name          | User choice       | String        | e.g. m_29_hymod |
| Soil depth          | HWSD / SoilGrids  | Scalar        | cm              |
| Porosity            | HWSD / SoilGrids  | Scalar (0-1)  | -               |
| Clay fraction       | HWSD / SoilGrids  | Scalar (0-1)  | -               |
| Sand fraction       | HWSD / SoilGrids  | Scalar (0-1)  | - (optional)    |
| Catchment properties| Shapefile / DEM   | Various       | Various         |

## Outputs

| Output          | Format | Contents                                     |
|-----------------|--------|----------------------------------------------|
| `params.json`   | JSON   | theta, S0, parameter details, soil properties|

JSON structure:
```json
{
  "model": "m_29_hymod_5p_5s",
  "theta": [200, 1.5, 0.7, 0.15, 0.01],
  "S0": [0, 0, 0, 0, 0],
  "param_details": {
    "Smax": {"value": 200, "min": 1, "max": 2000, "unit": "mm"}
  }
}
```

## Procedure

1. **Look up model metadata**: Load model's parameter count, store count,
   and parameter ranges from the internal database.

2. **Read soil properties**: From HWSD extract or SoilGrids CSV.
   Key properties: soil depth (cm), porosity (0-1), clay fraction (0-1).

3. **Estimate storage parameters (Smax)**:
   - Convert soil depth from cm to mm: `depth_mm = depth_cm * 10`
   - **NOT from m to mm** — HWSD is in cm, SoilGrids in mm. Verify source units (dt_008).
   - Estimate available water capacity: `AWC = FC - WP`
     where FC ≈ 0.1 + 0.3*clay + 0.2*porosity, WP ≈ 0.05 + 0.15*clay
   - `Smax = depth_mm * AWC`
   - Clip to model's [parRanges(1,1), parRanges(1,2)]

4. **Estimate rate parameters (k)**:
   - Baseflow k: decreases with clay content (clay retains water)
   - `k_slow ≈ 0.5 * (1 - clay_frac) * depth_factor`
   - Fast flow k: typically 3-5x slow flow
   - Clip to model's valid ranges

5. **Set fraction/threshold parameters** to default midpoints:
   - Flow split (alpha): 0.7 (70% to fast flow)
   - Non-linearity (beta/b): range midpoint
   - Temperature thresholds: 0 deg C
   - Fraction parameters: 0.5

6. **Set S0**: Default to zeros (dry start). For warm-up, run 1+ year
   of spin-up before the analysis period.

7. **Validate**: Check theta length == model.numParams and
   S0 length == model.numStores (dt_012).

## Verification

| Check                               | Expected           | Trap  |
|--------------------------------------|-------------------|-------|
| len(theta) == numParams              | True               | dt_012 |
| len(S0) == numStores                 | True               | dt_012 |
| All theta within [parMin, parMax]    | True               | -      |
| Smax in mm (not m, not cm)           | 10-2000 mm typical | dt_008 |
| Rate constants 0-1 for daily step    | True               | dt_009 |

## Traps

- **dt_008**: Storage parameter in wrong unit. HWSD soil depth is in cm.
  If treated as m and multiplied by 1000, Smax is 10x too large.
  If already in mm and multiplied by 10, also wrong.
  Always verify the source unit before converting.

- **dt_012**: S0 vector too short or too long. Too short causes MATLAB
  index-out-of-bounds error. Too long: extra elements are silently ignored,
  meaning a store starts uninitialized. Always check `m.numStores`.

- **dt_009**: If calibrating with sub-daily time step, rate constants (k)
  must be adjusted. k=0.5/d is equivalent to k≈0.02/h. Passing daily k
  values with hourly delta_t drains stores 24x too fast.

## Example

```bash
python tools/convert_parameters.py \
  --model m_29_hymod_5p_5s \
  --soil-depth-cm 150 \
  --porosity 0.40 \
  --clay-frac 0.25 \
  --output params.json
```

Expected output:
```json
{
  "model": "m_29_hymod_5p_5s",
  "theta": [210.0, 5.0, 0.7, 0.188, 0.037],
  "S0": [0.0, 0.0, 0.0, 0.0, 0.0],
  "n_params": 5,
  "n_stores": 5
}
```
