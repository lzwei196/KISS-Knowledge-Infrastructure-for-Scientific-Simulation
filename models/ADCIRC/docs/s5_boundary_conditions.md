# S5: Boundary Conditions (fort.19/20)

## Purpose

Define tidal harmonic forcing and time-varying boundary conditions at the open ocean boundaries of the ADCIRC mesh. Boundary conditions drive the circulation from the open-ocean edges and must be accurately specified to reproduce tidal signals and storm surge propagation.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Tidal constituents | TPXO9, FES2014, OTPS | netCDF/binary | Global tidal solutions (amplitude, phase) |
| River discharge | USGS, CaMa-Flood | CSV/time series | Flow rates at river boundaries |
| Remote surge | Regional model | Time series | Surge signal from parent model |
| Open boundary nodes | fort.14 | ADCIRC mesh | Node list for each open boundary segment |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| fort.15 tidal section | embedded | ASCII | Harmonic constituents in control file |
| Elevation BC | `fort.19` | ASCII | Time-varying elevation at open boundary (optional) |
| Flux BC | `fort.20` | ASCII | Time-varying normal flux at boundaries (optional) |
| SAL tide | `fort.24` | ASCII | Self-attraction / earth-load tide (optional) |

## Procedure

### 1. Harmonic Tidal Forcing (in fort.15)

Standard approach: specify tidal constituents directly in fort.15.

```
NBFR = 8                           ! Number of forcing frequencies
M2                                  ! Constituent name
28.9841042   1.0000   0.0000       ! Period (hours→converted), nodal factor, eq. argument
...
```

**Major tidal constituents** (in order of importance):

| Name | Period (hours) | Amplitude | Description |
|------|---------------|-----------|-------------|
| M2 | 12.4206 | 0.2-2.0 m | Principal lunar semidiurnal |
| S2 | 12.0000 | 0.1-0.6 m | Principal solar semidiurnal |
| N2 | 12.6583 | 0.05-0.4 m | Larger lunar elliptic |
| K1 | 23.9345 | 0.1-0.5 m | Lunar diurnal |
| O1 | 25.8193 | 0.1-0.4 m | Lunar diurnal |
| K2 | 11.9672 | 0.02-0.1 m | Lunisolar semidiurnal |
| P1 | 24.0659 | 0.03-0.2 m | Solar diurnal |
| Q1 | 26.8684 | 0.02-0.1 m | Larger lunar elliptic |

**CRITICAL**: Tidal periods in fort.15 are specified in **seconds**, not hours (dt_012). The constituent data block uses `period_in_seconds = period_hours × 3600`.

For each open boundary node, specify amplitude (meters) and phase (degrees, Greenwich epoch):
```
M2                                  ! Constituent name for boundary forcing
0.3456  127.89                      ! Amplitude (m), Phase (deg) for boundary node 1
0.3489  128.12                      ! Node 2
...
```

### 2. Tidal Potential Forcing (NTIP)

```
NTIP = 1    ! 1 = tidal potential
NTIP = 2    ! 2 = tidal potential + SAL (Self-Attraction & Loading)
```

When NTIP=2, provide fort.24 with SAL amplitudes and phases at each node.

### 3. Time-Varying Elevation BC (fort.19)

For non-harmonic signals (storm surge from parent model):

```
NSTEPS                              ! Number of timesteps
TIME1  ELEV_NODE1  ELEV_NODE2 ...   ! Time (s), elevation (m) at each boundary node
TIME2  ELEV_NODE1  ELEV_NODE2 ...
...
```

### 4. Time-Varying Flux BC (fort.20)

For river discharge or prescribed flow:
```
NSTEPS
TIME1  FLUX_NODE1  FLUX_NODE2 ...   ! Time (s), normal flux (m²/s) at each boundary node
```

### 5. Extracting Tidal Constants from TPXO

```python
# Using pytmd or similar library
import pytmd
model = pytmd.io.load_model('/path/to/TPXO9')

# Extract at boundary node locations
for node_lon, node_lat in boundary_nodes:
    amp, phase = pytmd.predict.extract_constants(
        node_lon, node_lat, model, constituent='M2'
    )
    # amp in meters, phase in degrees
```

## Verification

```bash
# Check that boundary node count matches fort.14
python3 -c "
with open('fort.14') as f:
    for line in f:
        pass  # Read to end to find boundary section
# Compare NOPE count with number of amplitude/phase pairs per constituent
"

# Verify tidal amplitude range
python3 -c "
# M2 amplitude should typically be 0.01-5.0 m
# If > 10 m, units may be wrong
print('Check that tidal amplitudes are in meters')
print('M2 typical: 0.2-2.0 m in Gulf of Mexico')
print('M2 typical: 0.5-4.0 m in Bay of Fundy')
"
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Period in hours not seconds | dt_012 | Tidal frequency wrong, no meaningful tidal signal |
| Phase in radians not degrees | — | Wrong tidal timing (phase shifted) |
| Amplitude too large | — | Unrealistic tidal range, possible instability |
| Node order mismatch | — | Forcing applied to wrong boundary nodes |
| Missing constituent data | — | Incomplete tidal signal |

## Example

```
! Excerpt from fort.15 tidal section
8                                    ! NBFR
M2                                   ! Constituent 1
 44714.16440  1.00000  0.00000       ! Period(s), nodal factor, eq arg
S2
 43200.00000  1.00000  0.00000
N2
 45570.05400  1.00000  0.00000
K1
 86164.09180  1.00000  0.00000
O1
 92949.63000  1.00000  0.00000
K2
 43082.05220  1.00000  0.00000
P1
 86637.20340  1.00000  0.00000
Q1
 96726.08160  1.00000  0.00000
! Then for each constituent, amplitude/phase at each open boundary node:
M2
 0.1543  178.23                      ! Node 1
 0.1556  178.45                      ! Node 2
...
```
