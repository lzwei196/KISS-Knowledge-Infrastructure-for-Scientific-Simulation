# S7: Output Parsing and Validation Skill

## Purpose

Parse the raw simulation CSV from `tools/run_hec_hms.py` into the standardized
daily discharge CSV expected by validation, then compare simulated discharge
against observed gauge flow. This stage is implemented by `tools/parse_hms_output.py`
and `tools/validate_hms.py`.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| Raw simulation output | CSV with `q_total_m3s` | `parse_hms_output.py --input_csv` |
| Observed discharge | Bengbu station text file | `validate_hms.py --obs_file` |
| Validation period | `YYYY-MM-DD` | `--start_date`, `--end_date` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| Parsed discharge | CSV with `sim_discharge_m3s` | `parse_hms_output.py --output_csv` |
| Validation figure | PNG | `validate_hms.py --output_figure` |
| Metrics JSON | JSON with NSE, KGE, PBIAS, r, RMSE | `validate_hms.py --output_json` |

## Procedure

1. Parse the model output and trim away the spinup year:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 tools/parse_hms_output.py \
     --input_csv ./output/sim_discharge.csv \
     --output_csv ./output/discharge_daily.csv \
     --start_date 1981-01-01 \
     --end_date 1990-12-31
   ```

2. Validate the parsed discharge against the Bengbu observed-flow file:

   ```bash
   python3 tools/validate_hms.py \
     --sim_csv ./output/discharge_daily.csv \
     --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
     --start_date 1981-01-01 \
     --end_date 1990-12-31 \
     --output_figure ./validation/validation.png \
     --output_json ./validation/metrics.json
   ```

3. Interpret the headline metrics using `docs/validation_convention.yaml`: discharge
   is satisfactory when NSE >= 0.50 and absolute PBIAS <= 15 percent.

## Verification

- Confirm `./output/discharge_daily.csv` contains the column `sim_discharge_m3s`.
- Confirm the parsed period starts no earlier than the validation start date.
- Confirm `./validation/metrics.json` contains NSE, KGE, PBIAS, r, RMSE, and `n_days`.
- Confirm `./validation/validation.png` is produced when `--output_figure` is supplied.

## Traps

- **dt_108**: If parsed discharge is orders of magnitude too large, check basin
  area units passed to `tools/run_hec_hms.py`.
- **dt_114**: A wrong mm-to-m3/s conversion can preserve hydrograph shape while
  corrupting magnitude.
- **dt_109**: Native DSS midnight conventions can shift time series by one day;
  this Python CSV path avoids DSS, but the trap applies if `--dss_file` is used.
- **dt_115**: Empty or short validation windows usually trace back to simulation
  dates outside forcing coverage.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p output validation
python3 tools/parse_hms_output.py \
  --input_csv ./output/sim_discharge.csv \
  --output_csv ./output/discharge_daily.csv \
  --start_date 1981-01-01 \
  --end_date 1990-12-31
python3 tools/validate_hms.py \
  --sim_csv ./output/discharge_daily.csv \
  --obs_file KISSPATH_OBS/BB/51080_bengbu.txt \
  --start_date 1981-01-01 \
  --end_date 1990-12-31 \
  --output_figure ./validation/validation.png \
  --output_json ./validation/metrics.json
```
