# Stage S1 — Site setup

## Purpose
Build the four ASCII files DayCent needs to describe a location: `<site>.100`
(climate normals + initial SOM pools), `sitepar.in` (site physical parameters),
`soils.in` (soil hydraulic profile), and `outfiles.in` (output toggles).

## Inputs
- Latitude, longitude, elevation
- Monthly climate normals (PRECIP, TMN2M, TMX2M)
- Soil texture profile (sand/clay/bulk density per layer) — usually from HWSD
- Site description: ground cover / starting vegetation, microcosm flag,
  N-input scalar, baseline pH

## Outputs
| File | Contents |
|------|----------|
| `<site>.100` | Climate normals + initial SOM, in Century-100 fixed format |
| `sitepar.in` | DayCent-specific site physics (key/value with `/` separator) |
| `soils.in` | Multi-layer soil hydraulic profile (13 columns, tab-separated; rev 491) |
| `outfiles.in` | 28 output channels with 0/1 toggle |

## Procedure
1. Copy the canonical template `100_Files/site_template_rev491.100` from the
   DayCent distribution into the run directory and rename to `<site>.100`.
2. Edit climate normals to match the location (PRECIP in **cm/month**,
   TMN2M/TMX2M in **°C**).
3. Edit the `*** Site and control parameters` block: `sitlat`, `sitlng`,
   `sand`, `silt`, `clay`, `rock`, `bulkd`, `nlayer`, `drain`, `basef`,
   `stormf`, `swflag`, `ph`.
4. Run `tools/convert_soil_to_daycent.py --lat ... --lon ... --out soils.in`
   to generate the 9-layer soil profile (0-90 cm) from HWSD/ROSETTA. The profile
   stops at 90 cm: HWSD only covers 0-100 cm, and DayCent rejects a layer
   boundary at 100 cm with the standard fix.100 ADEP layering ("Incompatible
   soil structures"). Layers above 30 cm use HWSD topsoil; 30-90 cm use HWSD
   subsoil (S_OC, S_REF_BULK_DENSITY, S_PH_H2O). In `<site>.100`, NLAYER 5
   matches 0-90 cm (NLAYER 8 also ran in a test).
5. Copy the Wooster `sitepar.in` and edit `elevation`, `slope`, `aspect`,
   monthly `sradadj`, and N2O nitrification adjustments.
6. Copy `100_Files/outfiles.in` and toggle the channels you want.

## Verification
- `<site>.100` parses without error: `head -10 site.100` shows 12 PRECIP
  values followed by 12 PRCSTD values.
- `soils.in` has 9 layers (0-90 cm) and `validate_outputs()` in
  `convert_soil_to_daycent.py` passes: 13 columns, no layer below 100 cm,
  root/evap columns equal to the Wooster values (root sum 0.84, must be in
  (0, 1]), FC > WP, sand+clay ≤ 1, bulkd 0.5–2.5, OM ≤ 0.2. The check runs
  before writing; on failure no soils.in is written.
- `sitepar.in` has the `usexdrvrs` flag set correctly for your forcing
  (0 = no extra drivers, 1 = include solar radiation column in `.wth`).
- `outfiles.in` references only files DayCent supports; misspelled channel
  names cause silent failures.

## Traps
- **Site-100 column alignment:** the parameter must end at column 16 and the
  label must start at column 19. Free-format tools that left-justify break
  the parser silently.
- **`sitlat`/`sitlng` sign convention:** decimal degrees, +N / +E. Western
  hemisphere longitudes are negative.
- **`drain` and `basef`:** drainage and baseflow fractions, **not** rates.
  Sum of `drain + basef + stormf` should be ≤ 1.0.
- **HWSD bulk density:** HWSD `T_REF_BULK_DENSITY` / `S_REF_BULK_DENSITY`
  are in kg/dm³ = g/cm³ already; do NOT divide by 1000. The converter writes
  them as is and never converts by the size of the value.
- **Organic carbon vs matter:** HWSD `T_OC` / `S_OC` is % organic carbon;
  soils.in column 10 is organic matter fraction = OC / 100 × 1.724.

## Example
```
python tools/convert_soil_to_daycent.py \
    --lat 40.78 --lon -81.93 \
    --out wooster_run/soils.in
```
