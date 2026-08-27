# s1_domain Skill

## Purpose

Define the true catchment and the three mHM grids: L0 morphology, L1 hydrology, and L11 routing. This KI treats MERIT-Hydro area snapping as the first domain action for flat or engineered basins.

## Inputs

- Approximate gauge longitude and latitude.
- Published drainage area for the gauge.
- Search bounding box for MERIT-Hydro clips.
- `config.json` from `docs/s0_config_skill.md`.
- Basin shapefile path, either user supplied or emitted by `tools/s1_domain/delineate_basin_merit.py`.

## Outputs

- MERIT-derived basin shapefile, plus `<stem>_dir.tif`, `<stem>_upa.tif`, and `<out_shp>.mask.tif`.
- `<run_dir>/domain_info.json` with L0/L1/L11 ESRI ASCII headers.
- `<run_dir>/input/latlon/latlon_1.nc`.

## Procedure

For flat basins or any basin where the supplied shapefile area disagrees with the gauge documentation, delineate from MERIT-Hydro first:

```bash
python tools/s1_domain/delineate_basin_merit.py \
  --outlet_lon 115.617 \
  --outlet_lat 32.433 \
  --target_area_km2 30630 \
  --bbox 112.5 31.0 116.2 34.4 \
  --snap_deg 0.06 \
  --out_shp runs/basin/wangjiaba_merit.shp
```

Then compute mHM's grid headers from the run config:

```bash
python tools/s1_domain/setup_mhm_domain.py \
  --config runs/wangjiaba/config.json \
  --shp_path runs/basin/wangjiaba_merit.shp
```

Write the lat/lon NetCDF expected by the namelist:

```bash
python tools/s1_domain/generate_latlon_files.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json
```

## Verification

Check the MERIT area metadata and the square L0 constraint:

```bash
python - <<'PY'
import json
d=json.load(open("runs/wangjiaba/domain_info.json"))
h=d["header_L0"]
assert h["ncols"] == h["nrows"], h
for level in ("header_L1","header_L11"):
    r=d[level]["cellsize"]/h["cellsize"]
    assert abs(r-round(r)) < 0.05, (level, r)
print("domain headers OK")
PY
test -f runs/wangjiaba/input/latlon/latlon_1.nc
```

## Traps

- `dt_s09` in `../diagnostics/triplets.yaml`: a truncated shapefile can produce good timing but about -50 percent PBIAS; calibrating cannot restore missing drainage area.
- `dt_r12`: L0 must be padded to a square grid or mHM can abort with `L2_variable_init: size mismatch in grid file for level2`.
- `dt_r02`: L1 and L11 resolutions must be exact integer multiples of L0.
- `dt_s07`: `resolution_Routing` in `mhm.nml` must match the actual L11 spacing or peaks shift by days.

## Example

The Wangjiaba notes in `SKILL.md` report the supplied shapefile at about 15,952 km2 versus a documented 30,630 km2. The example MERIT command above snaps to about 30,844 km2 and writes the D8/UPA clips consumed by s2.
