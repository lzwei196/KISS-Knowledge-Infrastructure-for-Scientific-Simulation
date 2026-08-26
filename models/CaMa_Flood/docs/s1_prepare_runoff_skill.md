# Stage 1: Prepare Runoff Skill

Thin wrapper for the preserved detailed note: [s1_prepare_runoff.md](s1_prepare_runoff.md).

## Purpose

Create CaMa-Flood yearly forcing NetCDFs named `{basin}_runoff_1d_YYYY.nc` with `Runoff(time, lat, lon)` in `mm/day` and descending latitude. This stage adapts VIC, wflow, HYPE, or generic NetCDF runoff into the exact forcing contract consumed by `MAIN_cmf`.

## Inputs

- `tools/prepare_runoff_input.py`
- Source runoff files selected by `--source vic`, `--source wflow`, `--source hype`, or `--source netcdf`
- Existing Bengbu CaMa-ready forcing directory for this KI example: `KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input`
- `docs/format_spec.yaml`
- `diagnostics/triplets.yaml`

## Outputs

- Yearly NetCDF files such as `KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input/bengbu_runoff_1d_2000.nc`
- Variable `Runoff` with units `mm/day`
- Dimensions `(time, lat, lon)`
- North-to-South latitude order

## Procedure

For a generic NetCDF source that already exists in this KI's Bengbu case, run the converter into a disposable output directory:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/prepare_runoff_input.py \
  --source netcdf \
  --input_dir KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input \
  --output_dir /tmp/cama_stage1_probe \
  --basin_name bengbu_probe \
  --start_year 2000 --end_year 2000 \
  --netcdf_var Runoff \
  --netcdf_pattern 'bengbu_runoff_1d_{year}.nc' \
  --scale_factor 1.0
```

For VIC text fluxes, use the same tool with `--source vic`, `--input_dir` pointing at the VIC flux directory, and `--file_prefix` matching the flux filename prefix. Do not convert runoff depth to `m3/s`; CaMa-Flood performs the area conversion internally.

## Verification

Inspect one produced or existing forcing file:

```bash
python -c 'import xarray as xr; p="KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input/bengbu_runoff_1d_2000.nc"; ds=xr.open_dataset(p); print(list(ds.data_vars)); print(ds.Runoff.dims, ds.Runoff.attrs.get("units")); print(float(ds.lat.values[0]), float(ds.lat.values[-1]), float(ds.Runoff.max()))'
```

Expected checks: `Runoff` exists, its dimensions are `('time', 'lat', 'lon')`, units are `mm/day`, the first latitude is greater than the last latitude, and runoff values are plausible daily depths.

## Traps

- `dt_003`: the forcing NetCDF does not contain capitalized variable `Runoff`, while generated namelists set `CVNROF = 'Runoff'`.
- `dt_004`: runoff was pre-converted to `m3/s`, causing implausibly huge discharge after CaMa-Flood applies its own area conversion.
- `dt_005`: generic NetCDF runoff is still a flux rate such as `m/s`; rerun with a checkable `--scale_factor` such as `86400000` for `m/s` to `mm/day`.
- `dt_006`: sub-daily source values were passed as daily depths without aggregation, biasing hydrograph volume by a fixed time-step factor.
- `dt_007`: latitude is ascending south-to-north, but the Stage 2 input matrix assumes `OLAT = NtoS`.
- `dt_009`: a padded zero source grid reduces effective runoff after remapping.
- `dt_010`: wflow routed `Q` was used as lateral runoff, double-routing the hydrograph.

## Example

```bash
ls KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input/bengbu_runoff_1d_2000.nc
```

