# EPIC0810 Stage 2 — Soil Preparation

## Purpose
Build a 6-layer EPIC `.SOL` file from HWSD + ROSETTA van Genuchten lookups.

## Inputs
- Site coordinates (lat, lon)
- Optional slope percent (default 1.0%)
- Output path

## Outputs
- `.SOL` file with header line + 2 site rows + 19 property rows × 6 layers, all numeric.

## Procedure
```python
from tools.convert_soil_to_sol import convert
result = convert(lat=35.86, lon=-78.78,
                 sol_path="/tmp/epic_run1/site.SOL",
                 soil_name="UMSTEAD")
```

Internally:
1. `ki_tools_common.soil_utils.lookup_hwsd(lat, lon)` — sand/silt/clay/OM/BD/pH/CEC/CaCO3
2. `ki_tools_common.soil_utils.rosetta_vgn(sand, clay)` — alpha, n, theta_r/s, Ksat, FC, WP
3. `build_profile()` assembles 19 properties
4. `write_sol()` writes fixed-width 8.2f columns
5. `validate_sol()` confirms zero alpha tokens

## Verification
```bash
wc -l site.SOL              # expect 22 lines (1 header + 2 site rows + 19 prop rows)
grep -n "[A-Za-z]" site.SOL # expect only line 1
```

Sanity:
- `Layer_depth_m` strictly increasing
- `Bulk_density` 0.9–1.8 g/cm³
- `Field_capacity > Wilting_point`
- `Sand + Silt + Clay ≈ 100`
- `pH` 4.0–8.5

## Traps
- **Alpha codes in SOL** → EPIC0810 crashes with `forrtl: severe (64)`.
  Always run `sanitize_sol()` after writing.
- **Layer depth in cm vs m** → EPIC0810 expects metres in the depth row;
  putting cm there gives bizarre water balance (1000× too deep).
- **Organic matter vs Organic carbon** → divide OM by 1.724 to get OC (Van Bemmelen).
- **Bulk density in kg/m³** → must be g/cm³.
- **Ksat in cm/day vs mm/h** → multiply by 10/24.

## Example
```python
from tools.convert_soil_to_sol import build_profile, write_sol, validate_sol
soil = {"sand": 50, "silt": 30, "clay": 20, "bulk_density": 1.4,
        "organic_matter": 1.2, "ph": 6.0, "cec": 12.0, "caco3": 0.0,
        "hyd_group": 2}
vgn = {"field_capacity": 0.30, "wilting_point": 0.12, "ksat_mmhr": 8.0}
prof = build_profile(soil, vgn)
write_sol(prof, "/tmp/test.SOL", soil_name="DEMO")
assert validate_sol("/tmp/test.SOL") == []
```
