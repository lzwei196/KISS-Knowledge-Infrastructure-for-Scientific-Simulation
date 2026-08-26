# Stage 2: Soil Parameter Setup

## Purpose
Create the four-layer VELMA parameter JSON used by `tools/run_velma.py`. The converter maps texture, HWSD/SoilGrids CSV extracts, or manual soil values into layer porosity, field capacity, wilting point, saturated hydraulic conductivity, routing defaults, snow parameters, and calibration bounds.

## Inputs
- One soil source: `--texture`, `--soil-csv`, or manual `--ks-mm-d` plus optional hydraulic properties.
- Soil depth in centimeters, defaulting to 300 cm.
- Ksat source unit, one of `mm/h`, `cm/h`, or `mm/d`.
- References: `SKILL.md` Sections 7-8, `dag.yaml`, `docs/format_spec.yaml`, and `diagnostics/triplets.yaml`.

## Outputs
- A parameter JSON file with `parameters.layer_thickness_mm`, `layer_porosity`, `layer_fc_frac`, `layer_wp_frac`, `layer_ks_mm_d`, `layer_cap_mm`, `layer_fc_mm`, `layer_wp_mm`, process parameters, and calibration bounds.

## Procedure
Run from the KI root with a texture lookup:

```bash
python tools/convert_soil_to_velma.py \
  --texture "silt loam" \
  --depth-cm 300 \
  --output params.json
```

Or convert a soil CSV extract:

```bash
python tools/convert_soil_to_velma.py \
  --soil-csv /path/to/hwsd_extract.csv \
  --ks-unit mm/h \
  --depth-cm 300 \
  --output params.json
```

Inspect supported options:

```bash
python tools/convert_soil_to_velma.py --help
```

## Verification
- The tool exits with `status: success`.
- `n_layers` is 4.
- `layer_thickness_mm` is `[100, 400, 1000, 1500]`.
- For every layer, `layer_wp_mm < layer_fc_mm < layer_cap_mm`.
- Percolation and lateral-flow coefficients generally decrease with depth unless a documented calibration reason overrides that pattern.
- The console output lists capacities, field capacity, and Ksat for L1-L4 without `[CRITICAL]` messages.

## Traps
- `dt_velma_005`: Ksat left in `mm/h`, making percolation 24x too slow.
- `dt_velma_006`: porosity or retention values supplied as percent instead of fraction.
- `dt_velma_024`: layer thickness handled as centimeters instead of millimeters, making L1 capacity too small.
- `dt_velma_012`: routing `split` too high, producing peaks with little baseflow.
- `dt_velma_013`: `pet_scale` outside a physically useful range, breaking ET magnitude.
- `dt_velma_014`: deep drainage coefficients too low, allowing L4 storage to grow for years.

## Example
Create initial Bengbu parameters from the silt-loam default used in the KI quick start:

```bash
python tools/convert_soil_to_velma.py \
  --texture "silt loam" \
  --depth-cm 300 \
  --output params_bengbu.json
```
