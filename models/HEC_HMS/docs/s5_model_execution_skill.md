# S5-S6: Model Parameters and Execution Skill

## Purpose

Run the REAL HEC-HMS engine (USACE 4.14, Linux, headless) on an HMS project with
`tools/run_hms_engine.py`. This is the only way to get a HEC-HMS result in this KI.

`tools/run_hec_hms.py` is a Python **SURROGATE** (a HydroCraft re-implementation
of SCS-CN loss, SCS UH, Linear Reservoir baseflow and Muskingum). It is kept for
the legacy `calibrate_hms.py` loop only. Its output is NOT a HEC-HMS result and
no equivalence with the real engine has been shown.

## Real engine (model of record)

Engine: `KISSPATH_HOME/engine_builds_20261006/HEC_HMS/run_hms_headless.sh`
(override with env `HMS_ENGINE`; build log next to it in `BUILD_LOG.md`).
Input: an HMS project folder (`<name>.hms`, `.basin`, `.met`, `.control`,
`.gage`, `.run`, DSS files). The tool copies the folder, so the source is
never changed.

```bash
python3 tools/run_hms_engine.py \
  --project /path/castro/castro.hms --run Current --run Future \
  --workdir ./hms_run --export Outlet:FLOW \
  --export_dss "castro.dss::/CASTRO VALLEY/OUTLET/FLOW//10MIN/OBS/" \
  --reference_results /path/castro/results      # optional exact compare
```

Outputs in `--workdir`: `project/` (the computed copy: `<run>.log`, `<run>.dss`,
`results/RUN_<run>.results`), `exports/*.csv` (`datetime,dss_time,value[,value_m3s]`),
`hms_engine_run.json` (all checks, per-element statistics, reference compare).
The last stdout line is a JSON summary.

Safety: `--workdir` may not be the project folder, inside it or a parent of it, and
every run Log File / DSS File must resolve inside the copy, so the source project is
never written to. `--overwrite` replaces only a folder this tool made earlier (marker
file `.run_hms_engine_workdir`) or an empty folder. Before computing, the tool deletes
in the copy the run's old log and `results/RUN_<run>.results`, and only the run's own
`RUN:<run>` records in its DSS file (the DSS file itself is kept, because it may also
hold input gages or paired data). HMS names the results file `RUN_<run>.results` with
spaces in the run name written as `_` (e.g. `RUN_Jan_96_storm.results`); the tool
follows that rule, and reads HEC's `24:00` (midnight) peak times as 00:00 of the next day.

Success means ALL of: engine exit 0, `computeRun` returned without exception,
the run log says `Finished computing simulation run "<run>"`, the log has no
`ERROR <n>:` line, and a fresh `results/RUN_<run>.results` parses. Exit codes:
0 ok, 2 bad arguments, 3 engine failed, 4 output missing/stale, 5 reference mismatch.
The JVM exits 0 even when HMS refuses a run (dt_119), so never judge by the exit
code of the launcher alone.

Official example check (2026-10-06): the castro sample from the 4.14 `samples.zip`
(runs Current and Future) matches the USACE-shipped `RUN_*.results` exactly for all
9 elements (peak, volume, peak time; 54 values): Current Outlet peak 540.2749050 cfs
at 16 Jan 1973 06:55, volume 242.6523187 ac-ft.

Traps: dt_119 (exit 0 on failed compute), dt_120 (DSS E part `5Minute` vs `5MIN`),
dt_121 (English-unit projects: CFS / AC-FT / MI2 / IN), dt_122 (headless launcher).

## Python SURROGATE (legacy, not HEC-HMS)

Everything below runs the surrogate. Use it only to reproduce old surrogate
numbers; label any number it gives as SURROGATE.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| Converted forcing | CSV with `precip_mm` | `--forcing_csv` |
| Soil parameters | JSON from `convert_soil_to_hms.py` | `--soil_params` |
| Basin area | km2 | `--basin_area_km2` |
| Simulation dates | `YYYY-MM-DD` | `--start_date`, `--end_date` |
| Optional overrides | numeric | `--cn`, `--ia_ratio`, `--tp_hr`, `--k_recession`, `--q_base_init`, `--recharge_fraction` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| Simulation CSV | CSV | `--output_csv` |
| `runoff_mm` | mm | SCS-CN loss stage |
| `loss_mm` | mm | SCS-CN loss stage |
| `q_direct_m3s` | m3/s | SCS Unit Hydrograph |
| `q_base_m3s` | m3/s | Linear Reservoir |
| `q_total_m3s` | m3/s | total simulated discharge |

## Procedure

1. Prepare forcing and soil files with the preceding tools:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 tools/convert_forcing_to_hms.py \
     --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --pet_csv /path/to/pet_daily.csv \
     --output_dir ./forcing_out
   # --pet_csv is required: columns date,pet_mm (mm/day) from an identified
   # source or derivation; the converter never computes PET itself.

   python3 tools/convert_soil_to_hms.py \
     --soil_file KISSPATH_STATIC/HWSD_China_Geo.img \
     --landcover_file KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --output_file ./params/soil_params.json
   ```

2. Run the surrogate (NOT HEC-HMS; for real results use `run_hms_engine.py` above).

   ```bash
   python3 tools/run_hec_hms.py \
     --forcing_csv ./forcing_out/basin_avg_forcing.csv \
     --soil_params ./params/soil_params.json \
     --basin_area_km2 121330 \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --ia_ratio 0.05 \
     --k_recession 0.95 \
     --q_base_init 50 \
     --recharge_fraction 0.05 \
     --output_csv ./output/sim_discharge.csv
   ```

3. If calibrated parameters are available from `tools/calibrate_hms.py`, pass their
   values as execution overrides.

## Verification

- Confirm `./output/sim_discharge.csv` exists and contains `q_total_m3s`.
- Confirm the log prints SCS-CN, SCS UH, and baseflow sections.
- Confirm `q_total_m3s` has no negative values and the specific discharge warning
  from `validate_outputs` is absent or explained.
- Discard the first year when evaluating Bengbu 1981-1990 validation, because the
  baseflow state is initialized at `q_base_init`.

## Traps

- **dt_103**: CN must be within the valid range. If `soil_params.json` contains
  bad CN, rerun soil conversion and check raster overlap.
- **dt_104** and **dt_113**: An overly large Ia ratio suppresses runoff from many
  daily storms and biases total volume low.
- **dt_105** and **dt_116**: A daily interval that is too coarse relative to Tp, or
  a Tp unsuitable for Bengbu-scale basin area, clips or shifts peaks.
- **dt_106**: Muskingum K/X choices must keep routing coefficients non-negative.
- **dt_107**: `k_recession` is a dimensionless ratio, not a conductivity or rate.
- **dt_114**: Runoff-depth to discharge conversion must use
  `Q = runoff_mm * area_km2 * 1000 / 86400`.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p output
python3 tools/run_hec_hms.py \
  --forcing_csv ./forcing_out/basin_avg_forcing.csv \
  --soil_params ./params/soil_params.json \
  --basin_area_km2 121330 \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --ia_ratio 0.05 \
  --output_csv ./output/sim_discharge.csv
```
