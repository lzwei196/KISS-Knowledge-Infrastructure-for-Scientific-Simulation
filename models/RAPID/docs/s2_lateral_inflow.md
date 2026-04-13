# Stage 2: Lateral Inflow (Vlat) Preparation

## Purpose

Convert land surface model (LSM) runoff output into RAPID's lateral inflow
format: a NetCDF file with variable `Vlat` containing accumulated water volume
(m³) per reach per routing period (ZS_TauR).

This is the most error-prone stage due to unit conversions. RAPID divides Vlat
by TauR internally to get flow rate, so Vlat MUST be volume, not rate.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| LSM runoff | NetCDF | kg/m²/s or mm/day | VIC, Noah, GLDAS, ERA5 |
| Catchment areas | CSV | m² | GIS/weight table |
| riv_bas_id.csv | CSV | — | Stage 1 output |
| ZS_TauR | Scalar | seconds | User choice (typically 10800 = 3h) |

## Outputs

| Output | Format | Dimensions | Units | Description |
|--------|--------|------------|-------|-------------|
| Vlat.nc | NetCDF4 | (time, rivid) | m³ | Lateral inflow volume per TauR |

### NetCDF Structure

```
dimensions:
  rivid = <n_reaches>
  time = UNLIMITED

variables:
  int rivid(rivid)        — reach IDs matching riv_bas_id order
  double time(time)       — seconds since reference date
  float Vlat(time, rivid) — lateral inflow volume (m³)
```

## Procedure

1. **Read LSM runoff** from NetCDF grid or point data.

2. **Map grid cells to reaches** using a weight table that distributes each
   grid cell's runoff to overlapping catchments proportionally by area.

3. **Convert units** to m³ per TauR period:

   | Source Units | Conversion Formula |
   |-------------|-------------------|
   | kg/m²/s | `Vlat = runoff × area_m2 × TauR_s / 1000` |
   | mm/s | `Vlat = runoff × area_m2 × TauR_s / 1000` |
   | mm/day | `Vlat = runoff / 86400 × area_m2 × TauR_s / 1000` |
   | mm/3hr | `Vlat = runoff / 10800 × area_m2 × TauR_s / 1000` |
   | m³/s (per reach) | `Vlat = runoff × TauR_s` |

   The `/1000` factor converts mm to m (depth × area = volume).

4. **Temporal aggregation**: If LSM time step ≠ TauR, aggregate by summing
   volumes within each TauR window.

5. **Write Vlat NetCDF** with rivid dimension matching riv_bas_id order.

## Verification

```bash
# Check variable exists and dimensions
ncdump -h Vlat.nc | grep -E "Vlat|rivid|time"

# Check number of time steps matches expected
python3 -c "
import netCDF4 as nc
d = nc.Dataset('Vlat.nc')
print('Time steps:', len(d.dimensions['time']))
print('Reaches:', len(d.dimensions['rivid']))
print('Expected time steps:', int(ZS_TauM / ZS_TauR))
print('Max Vlat:', d['Vlat'][:].max(), 'm³')
print('Min Vlat:', d['Vlat'][:].min(), 'm³')
d.close()
"

# Sanity: peak Vlat / TauR should give reasonable m³/s
python3 -c "
import netCDF4 as nc
d = nc.Dataset('Vlat.nc')
peak = d['Vlat'][:].max()
print(f'Peak equiv. rate: {peak / 10800:.1f} m³/s')
d.close()
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Volume vs rate confusion (dt_001) | SILENT | Passing m³/s as Vlat → discharge ~10800× too small |
| Wrong area units (dt_006) | SILENT | Area in km² instead of m² → Vlat 1e6× too large |
| Temporal mismatch (dt_009) | DEGRADED | Vlat time steps ≠ ZS_TauM/ZS_TauR → RAPID reads wrong data or crashes |
| Reach ordering mismatch (dt_007) | SILENT | rivid in Vlat.nc ≠ riv_bas_id order → wrong inflow assigned to wrong reaches |
| All-zero Vlat (dt_010) | SILENT | Missing spatial mapping → flat zero hydrograph |
| mm/day not divided by 86400 (dt_006) | SILENT | Vlat 86400× too large |

## Example

Converting GLDAS VIC 3-hourly runoff for a 5000-reach basin:

```python
# GLDAS provides Qs_acc + Qsb_acc in kg/m²/s
# TauR = 10800 s (3 hours), area per reach ~100 km² = 1e8 m²
# Vlat = (Qs + Qsb) × area_m2 × TauR / 1000
#      = 1e-5 kg/m²/s × 1e8 m² × 10800 s / 1000
#      = 10,800 m³ per 3-hour period per reach (plausible)

# Equivalent rate: 10800 / 10800 = 1.0 m³/s (reasonable for small reach)
```
