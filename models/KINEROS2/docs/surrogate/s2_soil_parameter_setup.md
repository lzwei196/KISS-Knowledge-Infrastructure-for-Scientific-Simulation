# s2 Soil Parameter Setup

## Purpose

Create the eight-parameter JSON used by the lumped KINEROS2 implementation: `Ks`, `psi_f`, `Smax`, `fc`, `k_fast`, `k_slow`, `f_slow`, and `alpha`. `tools/convert_soil_to_kineros2.py` can estimate these from a USDA texture class, a soil CSV, or direct Green-Ampt inputs.

## Inputs

- A USDA soil texture class such as `silt loam`, or a CSV with soil fields such as `Ks`, `psi_f`, `porosity`, `field_capacity`, and `wilting_point`.
- Soil depth in centimeters via `--depth-cm`.
- The source saturated hydraulic conductivity unit for CSV inputs: `mm/h`, `cm/h`, or `mm/d`.
- Optional direct values `--ks-mm-d`, `--psi-f-mm`, and `--porosity`.

## Outputs

- A parameter JSON containing `status: success`, `model: KINEROS2`, a `parameters` object with all eight model parameters, `bounds`, `param_details`, and a log.
- The file is read by `tools/run_kineros2.py` in `--mode simulate`.

## Procedure

1. Confirm the converter interface:

   ```bash
   python tools/convert_soil_to_kineros2.py --help
   ```

2. Generate initial parameters from a texture lookup:

   ```bash
   python tools/convert_soil_to_kineros2.py \
     --texture "silt loam" \
     --depth-cm 150 \
     --output work/params.json
   ```

3. For a soil CSV, specify the source `Ks` unit so the tool can convert to daily `mm/d`:

   ```bash
   python tools/convert_soil_to_kineros2.py \
     --soil-csv /path/to/hwsd_extract.csv \
     --ks-unit mm/h \
     --depth-cm 150 \
     --output work/params.json
   ```

4. Treat these parameters as initial estimates. Calibration in stage 7 can replace them when observed discharge is available.

## Verification

The converter prints each estimated parameter with its configured bound from `PARAM_BOUNDS` in `tools/convert_soil_to_kineros2.py`. Check that `work/params.json` contains all eight keys:

```bash
python -m json.tool work/params.json >/dev/null
```

Boundary warnings in the converter log are not fatal, but they mean calibration is especially important.

## Traps

- `dt_kineros2_004`: `Ks` supplied in `mm/h` instead of `mm/d` makes infiltration capacity about 24x too low.
- `dt_kineros2_005`: `psi_f` supplied in centimeters instead of millimeters underestimates wetting-front suction by 10x.
- `dt_kineros2_007`: `Smax` in meters rather than millimeters breaks soil storage.
- `dt_kineros2_010`: Texture strings must match the converter's USDA texture names in `RAWLS_TABLE`.
- `dt_kineros2_014`: Mixing `Ks` from one texture with `psi_f` from another can create abrupt Green-Ampt transitions.
- `dt_kineros2_016`: `fc` outside the `[0.2, 0.8]` range gives unrealistic soil moisture behavior.

## Example

For the Huai/Bengbu run described in `SKILL.md`, create an initial silt-loam parameter set:

```bash
python tools/convert_soil_to_kineros2.py \
  --texture "silt loam" \
  --depth-cm 150 \
  --output work/params_silt_loam.json
```
