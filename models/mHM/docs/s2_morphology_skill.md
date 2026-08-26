# s2_morphology Skill

## Purpose

Generate every L0 morphological input mHM needs as aligned ESRI ASCII grids and matching classdefinition files: terrain, flow direction/accumulation, soil, geology, land cover/LAI, and gauge grid.

## Inputs

- `config.json` and `domain_info.json`.
- DEM raster for `tools/s2_morphology/prepare_morpho_data.py`.
- Optional MERIT D8 clip from s1 when using `--fdir_source merit`.
- HWSD raster and MDB for soil.
- GLiM shapefile for geology, or a fallback default class.
- AVHRR land-cover raster; this KI expects the UMD legend by default.
- Gauge longitude, latitude, and integer gauge id.

## Outputs

- `input/morph/dem.asc`, `slope.asc`, `aspect.asc`, `fdir.asc`, `facc.asc`.
- `input/morph/soil_class.asc` and `soil_classdefinition.txt`.
- `input/morph/geology_class.asc` and `geology_classdefinition.txt`.
- Land-use grids and `lai_classdefinition.txt`.
- `input/morph/idgauges.asc`.

## Procedure

Create terrain and routing predictors:

```bash
python tools/s2_morphology/prepare_morpho_data.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --dem_path KISSPATH_DATA/china_dem_90m/china_dem_90m.tif \
  --fdir_source merit \
  --merit_dir_tif runs/basin/wangjiaba_merit_dir.tif
```

Create soil, geology, and land-cover inputs:

```bash
python tools/s2_morphology/hwsd_to_mhm_soil.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json

python tools/s2_morphology/glim_to_mhm_geology.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json

python tools/s2_morphology/landcover_to_mhm_luse.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --legend umd
```

Place the gauge id on the L0 grid and validate all morphology headers:

```bash
python tools/s2_morphology/generate_gauge_grid.py \
  --config runs/wangjiaba/config.json \
  --domain_info runs/wangjiaba/domain_info.json \
  --gauge_lat 32.433 \
  --gauge_lon 115.617 \
  --gauge_id 51030

python tools/s2_morphology/validate_morph_grids.py \
  --morph_dir runs/wangjiaba/input/morph
```

## Verification

Every ASCII grid in `input/morph` must share the same header:

```bash
python tools/s2_morphology/validate_morph_grids.py \
  --morph_dir runs/wangjiaba/input/morph
```

Check the D8 code set and classdefinition files:

```bash
test -s runs/wangjiaba/input/morph/soil_classdefinition.txt
test -s runs/wangjiaba/input/morph/geology_classdefinition.txt
python - <<'PY'
from pathlib import Path
vals=set()
for line in Path("runs/wangjiaba/input/morph/fdir.asc").read_text().splitlines()[6:]:
    vals.update(int(float(x)) for x in line.split())
bad=vals - {-9999,0,1,2,4,8,16,32,64,128}
assert not bad, bad
print("fdir codes OK")
PY
```

## Traps

- `dt_r01` in `../diagnostics/triplets.yaml`: mismatched ASCII headers crash mHM.
- `dt_r05` and `dt_r13`: wrong D8 convention or cycles in `fdir.asc` can zero routing or hang mRM startup.
- `dt_r11` and `dt_v003`: DEM nodata handling and geographic cellsize affect DEM-derived slope/aspect.
- `dt_s01`: wrong soil classdefinition column order silently corrupts Ksat and porosity.
- `dt_s12`: AVHRR must use `--legend umd`; uniform land cover disables land-cover MPR behavior.
- `dt_r04` and `dt_v002`: the gauge id must land on the correct valid routing cell.

## Example

For Wangjiaba, pair the MERIT shapefile from s1 with `--fdir_source merit` and `--legend umd`, then run `validate_morph_grids.py` before generating MPR parameters.
