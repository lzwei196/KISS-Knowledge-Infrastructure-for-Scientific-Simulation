# s0_config Skill

## Purpose

Create the mHM run directory tree and `config.json` for one basin. This stage fixes the basin name, period, three-grid resolutions, forcing source, PET mode, and mHM binary path used by all later tools.

## Inputs

- Basin shapefile, preferably from `tools/s1_domain/delineate_basin_merit.py` when MERIT-Hydro drainage area is needed.
- Simulation start and end years.
- L0, L1, and optional L11 resolutions in meters; L1 and L11 must be integer multiples of L0.
- Forcing dataset name: `CMFD` or `MSWX`.
- PET method code compatible with later `tools/s4_forcing/convert_forcing_to_mhm.py`.
- mHM binary, normally `KISSPATH_BINARIES/mhm/mhm`.

## Outputs

- `<output_dir>/<basin_name>/config.json`
- mHM input/output directories including `input/morph`, `input/meteo/pre`, `input/meteo/tavg`, `input/meteo/pet`, `input/gauge`, `input/latlon`, `output_b1`, and `restart`.

## Procedure

Run the preflight first from the KI root:

```bash
python preflight_check.py
```

Create the run scaffold with the validated s0 tool:

```bash
python tools/s0_config/configure_mhm_basin.py \
  --basin_name wangjiaba \
  --output_dir runs \
  --shp_path runs/basin/wangjiaba_merit.shp \
  --start_year 1980 \
  --end_year 1990 \
  --resolution_l0 1000 \
  --resolution_l1 24000 \
  --resolution_l11 24000 \
  --forcing CMFD \
  --pet_method 0 \
  --mhm_binary KISSPATH_BINARIES/mhm/mhm
```

Use `--pet_method 0` when daily temperature-only forcing will be converted to input PET by `tools/s4_forcing/convert_forcing_to_mhm.py`.

## Verification

Check that `config.json` exists and that the directories referenced in it were created:

```bash
test -f runs/wangjiaba/config.json
test -d runs/wangjiaba/input/morph
test -d runs/wangjiaba/input/meteo/pre
test -d runs/wangjiaba/output_b1
python -m json.tool runs/wangjiaba/config.json >/dev/null
```

Confirm the resolution ratios before moving to s1:

```bash
python - <<'PY'
import json
c=json.load(open("runs/wangjiaba/config.json"))
for k in ("resolution_L1_m","resolution_L11_m"):
    r=c[k]/c["resolution_L0_m"]
    assert abs(r-round(r)) < 0.01, (k, r)
print("resolution ratios OK")
PY
```

## Traps

- `dt_r10` in `../diagnostics/triplets.yaml`: very fine L0 on a large basin makes mHM run about 10x slower because MPR processes every L0 cell.
- `dt_s02` and `dt_s11`: PET method and forcing variables must agree; daily CMFD with only mean temperature should use PET method 0 and Oudin PET from s4.
- `dt_r02`: L1 and L11 must be integer multiples of L0 or mHM fails with a resolution mismatch.

## Example

For the Wangjiaba setup described in `SKILL.md`, use a MERIT-derived catchment shapefile, L0 about 0.01 degrees and L1/L11 about 0.25 degrees via `1000/24000` meter settings, CMFD forcing, and `--pet_method 0`.
