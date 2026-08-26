# S4 Inflow

## Purpose

Convert upstream discharge into a DLBreach `Upstream_Reservoir_Inflow` card. In HydroCraft this normally means extracting CaMa-Flood `outflw` at the dam grid cell and disaggregating daily discharge to hourly DLBreach inflow.

## Inputs

- CaMa-Flood `outflw` NetCDF via `--cama_outflw_nc`, plus `--dam_lat`, `--dam_lon`, and optional date bounds.
- Or a manual CSV via `--manual_csv` with first column time in hours and second column discharge in m3/s.
- Optional `--sim_start_sec`, which is converted internally to hours for the inflow card offset.

## Outputs

- JSON containing `inflow_card`, `peak_q_m3s`, `peak_time_hr`, `n_points`, `total_volume_m3`, `mean_q_m3s`, `source`, and `status`.
- A DLBreach `Upstream_Reservoir_Inflow` multiline card for S5 assembly.

## Procedure

For CaMa-Flood coupling:

```bash
python3 tools/s4_inflow/convert_cama_to_inflow.py \
  --cama_outflw_nc /path/to/o_outflw2020.nc \
  --dam_lat 35.0 \
  --dam_lon 110.0 \
  --start_date 2020-07-01 \
  --end_date 2020-07-05 \
  --sim_start_sec 0 \
  --output outputs/demo/inflow.json
```

For observed or scenario inflow:

```bash
python3 tools/s4_inflow/convert_cama_to_inflow.py \
  --manual_csv /path/to/inflow_time_hr_q_m3s.csv \
  --dam_lat 35.0 \
  --dam_lon 110.0 \
  --output outputs/demo/inflow.json
```

Read `docs/model_couplings.yaml` for `coupling_cama_to_dlbreach_inflow`.

## Verification

- `status` is `success`.
- `n_points` matches the expected event duration.
- `peak_q_m3s` and `peak_time_hr` are credible for the basin and event.
- For CaMa input, check that the nearest cell is hydrologically representative of the dam location.

## Traps

- `dt_007`: DLBreach uses mixed time units. Inflow card times are hours; `Time_Step` and `Simulation_Period` are seconds.
- `dt_016`: nearest CaMa grid cell can be on the wrong branch or dry cell. Compare the selected `outflw` magnitude with design or observed inflow.
- `dt_026`: manual CSV first column must already be hours, not seconds.
- `dt_005`: after S5 assembly, keep the multiline `Upstream_Reservoir_Inflow` block free of blank lines and comments between data rows.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s4_inflow/convert_cama_to_inflow.py \
  --manual_csv /tmp/inflow_time_hr_q_m3s.csv \
  --dam_lat 35.0 \
  --dam_lon 110.0 \
  --output outputs/example_case/inflow.json
```

