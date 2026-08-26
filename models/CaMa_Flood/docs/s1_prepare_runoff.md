# Stage 1: Prepare Runoff Input

## Purpose

Convert source hydrology output from VIC, wflow, HYPE, or a generic NetCDF into CaMa-Flood yearly forcing files with `Runoff(time, lat, lon)` in `mm/day` and latitude ordered North-to-South.

## Inputs

- `tools/prepare_runoff_input.py`
- Source model output directory supplied with `--input_dir`
- Source selector: `--source vic`, `--source wflow`, `--source hype`, or `--source netcdf`
- Basin name and inclusive year range
- Optional generic NetCDF controls: `--netcdf_var`, `--netcdf_pattern`, and `--scale_factor`

## Outputs

- Yearly NetCDF files named `{basin_name}_runoff_1d_YYYY.nc`
- Each output contains:
  - variable `Runoff`
  - units `mm/day`
  - dimensions `(time, lat, lon)`
  - descending latitude coordinate

## Procedure

Run from the KI root. For VIC flux text files:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/prepare_runoff_input.py \
  --source vic \
  --input_dir /path/to/vic_result \
  --output_dir /path/to/cama_input \
  --basin_name bengbu \
  --start_year 2000 --end_year 2005 \
  --file_prefix huaihe_fluxes_
```

For an already gridded NetCDF source:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/prepare_runoff_input.py \
  --source netcdf \
  --input_dir /path/to/source_nc \
  --output_dir /path/to/cama_input \
  --basin_name bengbu \
  --start_year 2000 --end_year 2005 \
  --netcdf_var runoff \
  --netcdf_pattern 'runoff_{year}.nc' \
  --scale_factor 1.0
```

Use `--scale_factor` only to convert the source values into `mm/day`. Do not convert to `m3/s`.

## Verification

Check one produced file:

```bash
python -c 'import xarray as xr; p="/path/to/cama_input/bengbu_runoff_1d_2000.nc"; ds=xr.open_dataset(p); print(list(ds.data_vars)); print(ds.Runoff.dims, ds.Runoff.attrs); print(float(ds.lat.values[0]), float(ds.lat.values[-1]), float(ds.Runoff.max()))'
```

Expected results:

- `Runoff` appears in the variable list.
- `Runoff.dims` is `('time', 'lat', 'lon')`.
- `Runoff.units` is `mm/day`.
- The first latitude is greater than the last latitude.

## Traps

- `dt_cama_007`: latitude order mismatch. `tools/prepare_runoff_input.py` writes descending latitude; bypassing it can make `generate_inpmat` map runoff to the wrong cells.
- `dt_cama_009`: runoff pre-converted from `mm/day` to `m3/s`. This causes discharge to be orders of magnitude too high.
- `dt_cama_006`: padded zero runoff grid. Build the NetCDF from actual source coordinates, then regenerate the input matrix against that exact grid.
- `dt_010`: wflow routed `Q` used as lateral runoff. Use lateral runoff or `total_runoff`, not already routed discharge.

## Example

The KI has CaMa-ready Bengbu forcing in:

```bash
ls KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input/bengbu_runoff_1d_2000.nc
```

Use the same filename pattern when passing Stage 2 `--runoff_dir` and `--runoff_prefix`.
