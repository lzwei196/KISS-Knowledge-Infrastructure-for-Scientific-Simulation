# S2: Initial Profile Setup

## Purpose

Create the `.sno` file that defines the initial state of the snowpack and
underlying soil at simulation start. This includes layer thicknesses,
temperatures, volume fractions, grain microstructure, and soil thermal properties.

## Inputs

| Parameter       | Description                        | Unit     | Typical range     |
|-----------------|------------------------------------|----------|-------------------|
| station_id      | Station identifier                 | string   | —                 |
| latitude        | Station latitude                   | degrees  | -90 to 90         |
| longitude       | Station longitude                  | degrees  | -180 to 180       |
| altitude        | Station elevation                  | m        | 0 to 9000         |
| start_date      | Profile initialization date        | ISO 8601 | —                 |
| SlopeAngle      | Terrain slope                      | degrees  | 0 to 90           |
| SlopeAzi        | Slope azimuth (from N)             | degrees  | 0 to 360          |
| n_soil_layers   | Number of soil layers              | integer  | 0 to 10           |
| soil_depth      | Total soil column depth            | m        | 0 to 5            |
| soil_texture    | USDA texture class                 | enum     | sand to clay      |
| soil_temp       | Initial soil temperature           | °C       | -10 to 30         |
| soil_moisture   | Initial moisture (of pore space)   | fraction | 0 to 1            |

## Outputs

A single `.sno` file in SMET 1.1 format with:
- Header: station metadata, profile date, slope, canopy parameters
- Data: one row per layer (soil layers first, bottom→top; then snow layers)
- 18 fields per layer row

## Procedure

1. **Define site** — Set coordinates, elevation, slope, aspect.
2. **Choose soil setup** — Use HWSD data or manual texture class.
3. **Compute volume fractions** — For each soil layer:
   - `Vol_Frac_S ≈ 0.55` (typical mineral soil solid fraction)
   - `Vol_Frac_W = moisture × (1 - Vol_Frac_S)`
   - `Vol_Frac_V = 1 - Vol_Frac_S - Vol_Frac_W - Vol_Frac_I`
   - **VERIFY: sum = 1.0 exactly**
4. **Set thermal properties** — From texture lookup table.
5. **Write .sno file** — Run `build_sno_profile.py`.
6. **Verify** — Check volume fraction sums, temperature in Kelvin.

## Verification

```bash
# Check volume fraction sums (should all be 1.000000)
awk '/^[0-9]/ {
    sum = $4 + $5 + $6 + $7
    if (sum < 0.999 || sum > 1.001) print "ERROR: sum=" sum " at line " NR
}' input/station.sno

# Check temperatures are in Kelvin (should be 250-310 range)
awk '/^[0-9]/ {if ($3 < 200) print "CELSIUS? line", NR, "T=", $3}' input/station.sno
```

## Traps

### Volume fractions not summing to 1.0 (dt_004) — FATAL
If `θ_i + θ_w + θ_v + θ_s ≠ 1.0`, SNOWPACK may crash with a mass conservation
error or produce layers with impossible properties. The error message may be
cryptic (e.g., "negative porosity").

**Prevention:** `build_sno_profile.py` enforces the sum constraint with an assertion.

### Layer thickness in cm instead of m (dt_015) — SILENT
The `Layer_Thick` field is in meters. If provided in cm (e.g., 50 for a 50 cm
layer), SNOWPACK interprets it as a 50 m thick layer, which will have enormous
thermal mass and effectively decouple the soil from the snowpack.

### Soil/snow layer ordering (dt_018)
Layers must be listed bottom-to-top. Soil layers come first, then snow layers.
Reversing the order doesn't crash but produces a physically meaningless column.

### Grain size in wrong units
Grain size `rg` is in mm (not m or μm). Bond radius `rb` is also in mm.
For soil layers, both are typically 0.0.

## Example

```bash
# Bare ground start (alpine site, no soil)
python tools/build_sno_profile.py \
    --output input/WFJ2.sno \
    --station_id WFJ2 \
    --latitude 46.831 --longitude 9.810 --altitude 2540 \
    --start_date "2020-10-01T00:00"

# With soil (3 layers, 1.5 m deep, sandy loam)
python tools/build_sno_profile.py \
    --output input/WFJ2.sno \
    --station_id WFJ2 \
    --latitude 46.831 --longitude 9.810 --altitude 2540 \
    --start_date "2020-10-01T00:00" \
    --n_soil_layers 3 --soil_depth 1.5 \
    --soil_texture sandy_loam --soil_temp_C 5.0 --soil_moisture 0.3
```
