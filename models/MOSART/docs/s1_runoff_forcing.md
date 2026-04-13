# Stage 1: Runoff Forcing Preparation

## Purpose

Convert land surface model runoff output (VIC, CLM, Livneh, etc.) into the NetCDF format expected by mosartwmpy. This is the primary forcing input that drives all river routing.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Surface runoff | NetCDF variable | VIC `RUNOFF`, CLM `QOVER` | varies (mm/s, mm/day, m/s) |
| Subsurface runoff | NetCDF variable | VIC `BASEFLOW`, CLM `QDRAI` | varies |
| Wetland runoff (optional) | NetCDF variable | CLM `QGWL` | varies |
| Grid coordinates | NetCDF dims | lat, lon, time | degrees, datetime |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| `QOVER` | NetCDF variable | mm/s | Surface runoff flux |
| `QDRAI` | NetCDF variable | mm/s | Subsurface drainage flux |
| `QGWL` | NetCDF variable (optional) | mm/s | Wetland/glacier runoff |

## Procedure

1. **Open source dataset** and identify runoff variable names
2. **Determine source units** — common sources:
   - VIC: mm/timestep (often 3-hourly or daily)
   - CLM: mm/s (native)
   - Livneh: mm/day
3. **Apply unit conversion** to mm/s:
   - mm/day → mm/s: divide by 86400
   - mm/hr → mm/s: divide by 3600
   - m/s → mm/s: multiply by 1000
   - kg/m²/s → mm/s: multiply by 1 (water density = 1000 kg/m³)
4. **Replace NaN/missing values** with 0.0
5. **Clip negative values** to 0.0 (physically meaningless)
6. **Rename coordinates** to `time`, `lat`, `lon`
7. **Write output** NetCDF with proper attributes

## Verification

- [ ] Output units are mm/s (max values typically 0.001 to 0.1 mm/s for CONUS)
- [ ] No NaN or infinite values in output
- [ ] No negative values in output
- [ ] Time coordinate covers simulation period
- [ ] Spatial grid matches domain grid (same lat/lon)
- [ ] File opens with `xr.open_dataset()` without errors

## Traps

### TRAP 1: Unit confusion between mm/s and mm/day
**Symptom**: Discharge ~86400x too high or too low.
**Diagnosis**: Source data in mm/day was not divided by 86400, or mm/s was incorrectly divided again.
**Prevention**: Always check source documentation. Livneh data is mm/day. CLM is mm/s.

### TRAP 2: VIC time-integrated vs. instantaneous runoff
**Symptom**: Runoff spikes at each VIC output step, zero between.
**Diagnosis**: VIC outputs accumulated mm per output step, not instantaneous flux.
**Prevention**: Divide by output interval in seconds: `mm_per_step / step_seconds`.

### TRAP 3: Grid mismatch between forcing and domain
**Symptom**: `IndexError` or all-zero runoff after masking.
**Diagnosis**: Forcing lat/lon does not match grid lat/lon (resolution or extent).
**Prevention**: Verify `np.allclose(forcing_lats, grid_lats)` before running.

### TRAP 4: Non-standard calendar (360-day, noleap)
**Symptom**: `TypeError` when selecting time index.
**Diagnosis**: CLM uses cftime calendars that need conversion to DatetimeIndex.
**Prevention**: mosartwmpy handles this in `load_runoff()` by calling `to_datetimeindex()`.

## Example

```python
from ki.tools.convert_runoff_forcing import convert_runoff

# Convert Livneh daily runoff to mosartwmpy format
stats = convert_runoff(
    input_path='./Livneh_daily_1980_1985.nc',
    output_path='./input/runoff/Livneh_NLDAS_1980_1985.nc',
    source_type='generic',
    surface_var='RUNOFF',
    subsurface_var='BASEFLOW',
    source_units='mm/day',
)
print(f"Max surface runoff: {stats['surface_max_mm_s']:.6f} mm/s")
```
