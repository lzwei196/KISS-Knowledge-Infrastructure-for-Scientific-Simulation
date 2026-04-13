# Stage 4: Boundary Conditions

## Purpose

Define the open boundary conditions that drive the simulation. Open boundaries
are where the model domain connects to the outside world — typically the open
ocean, upstream rivers, or adjacent coastal domains. Correct boundary conditions
are critical: errors here propagate throughout the entire domain.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Tidal constituents | Database | FES2014 / TPXO9 | Harmonic amplitudes + phases |
| Tide gauge data | CSV | CMEMS / IOC | Observed water levels |
| River discharge | CSV | Gauges / CaMa-Flood | Q (m³/s) time series |
| Nesting model | NetCDF | Regional model output | Full state at boundary |
| Boundary locations | .pli | From grid (Stage 1) | Polyline along open edge |

## Outputs

### D-Flow FM Format

| Output | Format | Description |
|--------|--------|-------------|
| Forcing spec | .ext | Links quantities to locations and data files |
| Boundary locations | .pli | Polyline with labeled points along boundary |
| Boundary data | .bc | Time series or harmonic components |

### Delft3D-FLOW Format

| Output | Format | Description |
|--------|--------|-------------|
| Boundary definition | .bnd | Boundary names, types, grid locations |
| Boundary data | .bch / .bca | Time series / harmonic components |
| Discharge data | .dis | Source/sink flow rates |
| Discharge locations | .src | Grid cell indices for sources |

## Procedure

### Tidal Boundaries (Harmonic)

1. **Define boundary polyline** (.pli) along the open edge of the domain
2. **Extract tidal constituents** at each boundary point from FES2014/TPXO
3. **Write harmonic .bc file**:
   ```ini
   [Forcing]
   Name = boundary_0001
   Function = harmonic
   Quantity = harmonic component
   Unit = minutes
   Quantity = waterlevelbnd amplitude
   Unit = m
   Quantity = waterlevelbnd phase
   Unit = deg
   0.0  0.0  0.0          # A0 (mean level)
   745.2  1.5  30.0        # M2: period 745 min, amp 1.5 m, phase 30°
   720.0  0.5  60.0        # S2: period 720 min, amp 0.5 m, phase 60°
   ```

### Time Series Boundaries

1. **Prepare water level / velocity time series** from gauge or model
2. **Ensure correct datum** (MSL, chart datum, etc.)
3. **Write time series .bc file**:
   ```ini
   [Forcing]
   Name = boundary_0001
   Function = timeseries
   Quantity = time
   Unit = seconds since reference
   Quantity = waterlevelbnd
   Unit = m
   0.0  1.23
   3600.0  1.45
   ```

### River Discharge Boundaries

1. **Identify inflow locations** on the grid
2. **Prepare discharge time series** (m³/s)
3. **Write .bc file** with quantity = dischargebnd
4. **Optionally add** temperature and salinity for the inflow

```bash
python ki/tools/convert_boundary_conditions.py \
  --tide_constituents "M2:1.5:30,S2:0.5:60,K1:0.3:120,O1:0.2:90" \
  --boundary_pli boundary.pli \
  --start_date 2020-01-01 --end_date 2020-02-01 \
  --output_dir boundaries/
```

## Verification

- **Tidal range**: compare boundary tidal range with known values (e.g., co-tidal charts)
- **Phase**: M2 phase should match co-tidal charts for the region
- **Discharge**: river flow should match gauge data; no negative values
- **Spin-up**: first 1-2 tidal cycles may show transient effects — check that
  the boundary signal stabilizes
- **Consistency**: water level at boundary should match between Delft3D and observations

```python
# Quick tidal analysis of boundary
import numpy as np
time_hr = np.linspace(0, 48, 1000)  # 2 days
# M2 tide with 1.5 m amplitude, 12.42 hr period
wl = 1.5 * np.cos(2 * np.pi * time_hr / 12.42)
print(f"Tidal range: {wl.max() - wl.min():.2f} m")
```

## Traps

1. **Datum mismatch (dt_005)**: tidal boundary in MSL, but grid bathymetry
   referenced to chart datum (or vice versa). A constant offset of 0.5-2.0 m
   can flood or dry entire intertidal zones. Always verify the datum reference.

2. **Phase reference time**: harmonic phases are relative to a reference time.
   FES2014 uses a specific epoch; Delft3D uses the simulation RefDate. If the
   phase reference doesn't match, all tidal phases are shifted → wrong timing
   of high/low tide.

3. **Constituent period in wrong units**: Delft3D .bc files expect period in
   MINUTES for harmonic boundaries. Using hours or seconds gives wrong
   frequencies → the tide oscillates 60× too fast or 60× too slow.

4. **Missing mean level (A0)**: the first harmonic entry (period=0) is the
   mean water level. Omitting it defaults to 0 m, which may not match your datum.

5. **River salinity**: freshwater rivers should have S=0 PSU. If you don't specify
   salinity for discharge boundaries, the default may be ocean salinity (~35 PSU),
   which creates an artificially dense inflow.

## Example

```python
# Create boundary PLI file for a simple straight boundary
with open("sea_boundary.pli", "w") as f:
    f.write("SeaBoundary\n")
    f.write("    5    2\n")  # 5 points, 2 columns
    f.write("5.000000E+05  5.700000E+06 SB_0001\n")
    f.write("5.100000E+05  5.700000E+06 SB_0002\n")
    f.write("5.200000E+05  5.700000E+06 SB_0003\n")
    f.write("5.300000E+05  5.700000E+06 SB_0004\n")
    f.write("5.400000E+05  5.700000E+06 SB_0005\n")
```
