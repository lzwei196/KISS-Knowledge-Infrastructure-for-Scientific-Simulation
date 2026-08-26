# S5: Calibration Skill

## Purpose

Calibrate this KI's SCS-CN, abstraction, baseflow, recharge, and timing parameters
against observed discharge using the GLUE-style random sampler implemented in
`tools/calibrate_hms.py`. The calibration stage uses the same core functions as
`tools/run_hec_hms.py`; it is not a separate model.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| Converted forcing | CSV with `precip_mm` | `--forcing_csv` |
| Observed discharge | Bengbu station text file | `--obs_file` |
| Basin area | km2 | `--basin_area_km2` |
| Calibration dates | `YYYY-MM-DD` | `--start_date`, `--end_date` |
| Sample count | integer >= 10 | `--n_samples` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| Calibrated parameters | JSON | `--output_params` |
| `best_kge` | dimensionless | `tools/calibrate_hms.py` |
| `best_params` | JSON object | `tools/calibrate_hms.py` |
| `param_ranges_tested` | JSON object | `tools/calibrate_hms.py` |

## Procedure

1. Generate the forcing CSV first:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 tools/convert_forcing_to_hms.py \
     --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --output_dir ./forcing_out
   ```

2. Run GLUE-style calibration on the post-spinup validation window:

   ```bash
   python3 tools/calibrate_hms.py \
     --forcing_csv ./forcing_out/basin_avg_forcing.csv \
     --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
     --basin_area_km2 121330 \
     --start_date 1981-01-01 \
     --end_date 1990-12-31 \
     --n_samples 500 \
     --output_params ./params/calibrated_params.json
   ```

3. Re-run `tools/run_hec_hms.py` with the values in `best_params`: `cn`,
   `ia_ratio`, `k_recession`, `q_base_init`, `recharge_fraction`, and the
   time-to-peak multiplier converted to an explicit `--tp_hr` if needed.

## Verification

- Confirm `./params/calibrated_params.json` contains `status: success`,
  `best_kge`, `best_params`, and `param_ranges_tested`.
- Confirm `n_samples` in the JSON matches the command line.
- Confirm `best_params.cn` remains inside the calibrated range in
  `tools/calibrate_hms.py`.
- After applying parameters, validate with `tools/validate_hms.py` and
  `docs/validation_convention.yaml`.

## Traps

- **dt_104**: Calibrating Ia ratio matters because 0.20 can understate runoff
  volume in humid/semi-humid basins.
- **dt_107**: `k_recession` is dimensionless. Parameter samples are ratios, not
  hydraulic conductivity values.
- **dt_116**: Peak timing errors are controlled by the time-to-peak scale; an
  implausible Tp for Bengbu basin area can give a good volume but wrong timing.
- **dt_105**: The execution timestep must still resolve the calibrated Tp.
- **dt_115**: Calibration silently loses information if forcing and observation
  periods do not overlap for the requested dates.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p params
python3 tools/calibrate_hms.py \
  --forcing_csv ./forcing_out/basin_avg_forcing.csv \
  --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
  --basin_area_km2 121330 \
  --start_date 1981-01-01 \
  --end_date 1990-12-31 \
  --n_samples 500 \
  --output_params ./params/calibrated_params.json
```
