# S2 Dam Geometry

## Purpose

Create DLBreach embankment geometry cards for crest-to-base height, crest width, upstream and downstream slopes, and embankment length. These cards become part of the single `casename.txt` input assembled in S5.

## Inputs

- `--height_m`: embankment height in meters, measured from base to crest.
- `--crest_width_m`: crest width in meters.
- `--upstream_slope_vh` and `--downstream_slope_vh`: vertical-over-horizontal ratios.
- `--length_m`: maximum breach bottom width used by DLBreach, not simply a display crest length.

## Outputs

- JSON from `tools/s2_dam_properties/create_dam_geometry.py`.
- `geometry_cards` containing `Embankment_Height`, `Embankment_Crest_Width`, `Embankment_Upstream_Slope`, `Embankment_Downstream_Slope`, and `Embankment_Length`.
- Derived properties including `base_width_m` and warning messages.

## Procedure

Generate the geometry JSON:

```bash
python3 tools/s2_dam_properties/create_dam_geometry.py \
  --height_m 93 \
  --crest_width_m 10 \
  --upstream_slope_vh 0.4 \
  --downstream_slope_vh 0.4 \
  --length_m 200 \
  --output outputs/demo/geometry.json
```

Use `docs/format_spec.yaml` for units and variable meanings, and keep the resulting JSON for S5 `assemble_input_file.py`.

## Verification

- The command exits 0 and prints `status: success`.
- `validation_errors` is empty.
- Review `validation_warnings`, especially the computed `base_width_m` and any warning about `Embankment_Length`.
- Confirm the five `Embankment_*` cards appear in `geometry_cards`.

## Traps

- `dt_011`: slopes are V/H. For a 1V:3H earthfill face, use about `0.333`, not `3`.
- `dt_024`: `Embankment_Length` caps breach bottom width. If it is too small, final breach width can stop artificially early.

## Example

```bash
cd KISSPATH_KI_ROOT/DLBreach/knowledge_infrastructure
python3 tools/s2_dam_properties/create_dam_geometry.py \
  --height_m 30 \
  --crest_width_m 8 \
  --upstream_slope_vh 0.333 \
  --downstream_slope_vh 0.4 \
  --length_m 150 \
  --output outputs/example_case/geometry.json
```

