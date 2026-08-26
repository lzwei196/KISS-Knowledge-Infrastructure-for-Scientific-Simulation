# s5_parameter_setup

## Purpose

Create `par.txt` for HYPE from the `GeoClass.txt` land-use and soil dimensions, using this KI's climate-zone defaults or WWH parameter extraction. The file must provide exactly the right number of values for land-use-dependent, soil-dependent, and general parameters.

## Inputs

- `modelfiles/GeoClass.txt` from s2
- Climate zone label for defaults: `--climate`
- Optional latitude/longitude when extracting WWH defaults

## Outputs

- `modelfiles/par.txt`
- Optional WWH default parameter range file such as `par_wwh_defaults.txt`

## Procedure

Generate the standard HYPE parameter file:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s5_parameter_setup/setup_parameters.py \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --output outputs/hype_run/modelfiles/par.txt \
  --climate humid_subtropical
```

Optionally extract WWH defaults for the basin location:

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s5_parameter_setup/extract_wwh_params.py \
  --lat 31.0 \
  --lon 117.0 \
  --climate humid_subtropical \
  --output outputs/hype_run/modelfiles/par_wwh_defaults.txt
```

## Verification

- Every land-use parameter line has `max(landuse ID in GeoClass.txt)` values.
- Every soil parameter line has `max(soil ID in GeoClass.txt)` values.
- General parameter lines have one value.
- Soil water parameters satisfy `wcwp < wcfc < wcep` for each soil type.
- `par.txt` remains tab-separated and stays in the same `modelfiles/` directory as `GeoClass.txt`.

## Traps

- `dt_r02`: `par.txt` has too few values for a land-use or soil-dependent parameter.
- `dt_s03`: `wcfc >= wcep` prevents effective percolation and can produce zero discharge.
- `dt_s09`: N/P is enabled in `info.txt`, but `par.txt` lacks nutrient-specific parameters; use s9 before execution when simulating nutrients.

## Example

```bash
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s5_parameter_setup/setup_parameters.py \
  --geoclass outputs/hype_run/modelfiles/GeoClass.txt \
  --output outputs/hype_run/modelfiles/par.txt \
  --climate humid_subtropical

grep -E 'wcwp|wcfc|wcep' outputs/hype_run/modelfiles/par.txt
```
