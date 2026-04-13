# S3 — Forcing Preparation

## Purpose

Prepare the external forcing data (precipitation, sea-level, tectonics, waves) in the
formats and units required by pyBadlands. This is the stage with the highest density
of unit conversion traps — most silent failures originate here.

## Inputs

| Input | Format | Source Units | Model Units | Conversion |
|-------|--------|-------------|-------------|------------|
| Precipitation | raster or scalar | mm/day, mm/month | **m/year** | × 365.25/1000 |
| Sea-level curve | 2-col CSV | ka or Ma, m | **years, m** | time × 1000 or × 1e6 |
| Tectonic uplift | raster map | m/year (rate) | **m (total)** | × duration_years |
| Horiz. displacement | raster map | m/year (rate) | **m (total)** | × duration_years |
| Wave climate | parameters | m, s, degrees | **m, s, degrees** | (usually correct) |
| Orographic params | scalar | m/year, m | **m/year, m** | (verify) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Rainfall config | XML `<precipitation>` | Uniform rval or spatial map path |
| Sea-level file | 2-col text | time (yr), elevation (m) |
| Displacement maps | raster/CSV | Total displacement (m) per event |
| Wave events | XML `<waveglobal>` | Wave height, period, direction |

## Procedure

### Rainfall

1. **Uniform rainfall** — Set `<rval>` directly in m/year:
   ```xml
   <rain>
       <rstart>0</rstart>
       <rend>5000000</rend>
       <rval>1.0</rval>  <!-- 1.0 m/year = ~1000 mm/year -->
   </rain>
   ```

2. **Spatially variable** — Create a map file with columns `x y rainfall_m_per_year`.
   Reference it via `<map>`:
   ```xml
   <rain>
       <rstart>0</rstart>
       <rend>5000000</rend>
       <map>rain_map.csv</map>
   </rain>
   ```

3. **Orographic rainfall** — If precipitation depends on topography, set the orographic
   parameters:
   ```xml
   <rain>
       <rstart>0</rstart>
       <rend>5000000</rend>
       <ortime>10000</ortime>     <!-- Recalculate every 10 kyr -->
       <rbgd>0.5</rbgd>           <!-- Background rain: 0.5 m/year -->
       <rmin>0</rmin>              <!-- Min elevation for rain -->
       <rmax>3000</rmax>           <!-- Max elevation for rain -->
       <windx>1.0</windx>
       <windy>0.0</windy>
   </rain>
   ```

### Sea Level

1. **Fixed sea level** — Set `<position>` in metres:
   ```xml
   <sea>
       <position>0.0</position>
   </sea>
   ```

2. **Time-varying** — Create a 2-column file: `time_years sealevel_m`
   ```xml
   <sea>
       <curve>sealevel_curve.csv</curve>
   </sea>
   ```
   **CRITICAL**: Time must be in years, not ka or Ma (dt_004).

### Tectonic Displacement

1. Create displacement event(s) in XML:
   ```xml
   <tectonic>
       <events>1</events>
       <disp>
           <dstart>0</dstart>
           <dend>5000000</dend>
           <ufile>uplift_map.csv</ufile>  <!-- Vertical, metres TOTAL -->
       </disp>
   </tectonic>
   ```

2. **CRITICAL**: The `ufile` map contains **total displacement** in metres over the
   event duration `dend - dstart`, NOT a rate (dt_005).
   - If your data is a rate (m/year): multiply by `(dend - dstart)`
   - Example: 0.001 m/year uplift over 5 Myr → ufile values = 5000 m

### River Sources

1. For point-source rivers:
   ```xml
   <rivers>
       <riverNb>1</riverNb>
       <river>
           <rstart>0</rstart>
           <rend>5000000</rend>
           <rposX>100000</rposX>      <!-- X position, metres -->
           <rposY>200000</rposY>      <!-- Y position, metres -->
           <rQw>500.0</rQw>           <!-- Discharge, m³/s -->
           <rQs>0.5</rQs>             <!-- Sediment load, Mt/year -->
       </river>
   </rivers>
   ```
   **CRITICAL**: `rQs` is in **megatonnes/year**. The code converts internally:
   `qs_m3 = rQs × 1e9 / rhoS` (dt_002).

## Verification

- [ ] Rainfall values are in m/year (0.1–5.0 for most climates) (dt_001)
- [ ] Sea-level time is in years, not ka (dt_004)
- [ ] Displacement maps are total (m), not rate (m/year) (dt_005)
- [ ] River Qs is in Mt/year, not kg/year (dt_002)
- [ ] All referenced file paths exist relative to XML location
- [ ] Forcing time ranges cover the full simulation period

## Traps

| ID | Trap | Consequence | Detection |
|----|------|-------------|-----------|
| dt_001 | Rain in mm/day not m/year | 1000× erosion | Max rval > 50 |
| dt_002 | Qs in kg/year not Mt/year | 10⁹× sediment | Qs > 1000 |
| dt_004 | Sea-level time in ka | Changes 1000× too fast | Time range mismatch |
| dt_005 | Displacement rate not total | Under-displacement | Max disp too small |
| dt_011 | Discharge in L/s not m³/s | 1000× too small | Very low discharge |
| dt_017 | No precipitation defined | Zero runoff, no erosion | Check XML has rain |

## Example

Using the `convert_forcing_to_badlands.py` tool:

```bash
# Convert ERA5 precipitation (mm/day) to badlands format
python ki/tools/s3_forcing/convert_forcing_to_badlands.py \
    --type rainfall \
    --input era5_precip.csv \
    --output rain_map.csv \
    --input-units mm/day

# Convert sea-level curve from ka to years
python ki/tools/s3_forcing/convert_forcing_to_badlands.py \
    --type sealevel \
    --input sl_curve_ka.csv \
    --output sl_curve_years.csv \
    --time-units ka

# Convert uplift rate to total displacement
python ki/tools/s3_forcing/convert_forcing_to_badlands.py \
    --type tectonic \
    --input uplift_rate.csv \
    --output uplift_total.csv \
    --duration 5000000
```
