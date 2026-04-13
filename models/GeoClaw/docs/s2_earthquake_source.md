# Stage 2: Earthquake Source / Dynamic Topography

## Purpose

Define the tsunami generation mechanism by specifying earthquake fault
parameters and computing the resulting seafloor deformation.  GeoClaw uses
the Okada (1985) analytical model to translate fault geometry and slip into
vertical and horizontal displacement of the ocean floor.  The displacement
is written as a dynamic topography (dtopo) file that drives the simulation.

## Prerequisites

- Stage 1 (bathymetry) completed
- Earthquake source parameters from:
  - USGS Centroid Moment Tensor (CMT) catalog
  - NOAA NCEI historical earthquake database
  - Published finite fault models
  - Custom fault specification
- GeoClaw Python tools installed (`from geoclaw import dtopotools`)

## Inputs

| Input | Format | Units | Notes |
|-------|--------|-------|-------|
| Fault longitude | float | degrees | Epicenter or subfault center |
| Fault latitude | float | degrees | Epicenter or subfault center |
| Fault depth | float | **km** | Depth to top of fault plane |
| Fault strike | float | degrees (0–360) | Clockwise from north |
| Fault dip | float | degrees (0–90) | Angle from horizontal |
| Fault rake | float | degrees (−180–180) | Slip direction |
| Fault slip | float | **meters** | CRITICAL: must be in meters, not cm |
| Fault length | float | **km** | Along-strike dimension |
| Fault width | float | **km** | Down-dip dimension |
| Rigidity | float | Pa | Shear modulus (default: 4×10¹⁰ Pa) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `*.tt3` or `*.dtopo` | dtopo Type 3 | Time-dependent seafloor deformation |
| `*.tt1` | dtopo Type 1 | (t, x, y, dz) columns |
| Deformation plot | PNG | Visual verification of uplift/subsidence |

## Procedure

1. **Gather fault parameters.**  Use published finite fault models or
   define a simple rectangular fault.

2. **Create the deformation file using dtopotools:**
   ```python
   from geoclaw import dtopotools

   fault = dtopotools.SubFault()
   fault.strike = 16.0         # degrees
   fault.length = 450e3        # meters (450 km → input to Okada)
   fault.width = 100e3         # meters (100 km)
   fault.depth = 35e3          # meters (35 km — note: dtopotools uses meters)
   fault.slip = 15.0           # meters — CRITICAL: not centimeters
   fault.dip = 14.0            # degrees
   fault.rake = 104.0          # degrees
   fault.latitude = -35.826    # degrees
   fault.longitude = -72.668   # degrees
   fault.coordinate_specification = 'top center'

   # Create dtopo
   subfault_model = dtopotools.SubFault()
   # ... or use Fault class for multi-segment
   fault_model = dtopotools.Fault()
   fault_model.subfaults = [fault]
   fault_model.rupture_type = 'static'  # or 'kinematic'

   # Compute deformation on a grid
   x = numpy.linspace(-77, -67, 100)
   y = numpy.linspace(-40, -30, 100)
   dtopo = fault_model.create_dtopography(x, y, times=[0, 1])
   dtopo.write('chile_dtopo.tt3', dtopo_type=3)
   ```

3. **Verify the deformation.**  Plot the uplift/subsidence pattern:
   ```python
   dtopo.plot_dZ_colors(t=1)
   ```
   - Check that maximum uplift/subsidence is physically reasonable
     (typically < 20 m for major earthquakes)
   - Verify the spatial pattern matches published models

4. **Register in setrun.py:**
   ```python
   dtopo_data.dtopofiles.append([3, 'chile_dtopo.tt3'])
   ```

## Verification

- [ ] Maximum deformation is physically plausible (< 20 m for most earthquakes)
- [ ] Uplift/subsidence pattern matches published finite fault model
- [ ] Seismic moment (M₀ = μ × L × W × slip) matches expected magnitude
- [ ] Fault slip is in METERS (not cm — see dt_010)
- [ ] dtopo file time range matches simulation time
- [ ] dtopo spatial extent covers the fault region adequately

## Traps

| Trap | Triplet | Impact |
|------|---------|--------|
| Slip in cm instead of meters | dt_010 | Tsunami amplitude 100× too small |
| Depth in meters instead of km | dt_010 | Fault too shallow → wrong pattern |
| Missing coordinate_specification | — | Fault offset from intended location |
| dtopo doesn't cover rupture area | — | Incomplete deformation |

## Example

Chile 2010 earthquake (Mw 8.8):

```python
from geoclaw import dtopotools
import numpy

# Simple single-fault approximation
fault = dtopotools.SubFault()
fault.strike = 16.0
fault.length = 450e3    # 450 km in meters
fault.width = 100e3     # 100 km in meters
fault.depth = 35e3      # 35 km in meters
fault.slip = 15.0       # 15 meters
fault.dip = 14.0
fault.rake = 104.0
fault.latitude = -35.826
fault.longitude = -72.668
fault.coordinate_specification = 'top center'

model = dtopotools.Fault()
model.subfaults = [fault]
model.rupture_type = 'static'

x = numpy.linspace(-77, -67, 200)
y = numpy.linspace(-40, -30, 200)
dtopo = model.create_dtopography(x, y, times=[0, 1])
dtopo.write('chile2010.tt3', dtopo_type=3)

print(f"Max uplift:     {dtopo.dZ.max():.2f} m")
print(f"Max subsidence: {dtopo.dZ.min():.2f} m")
print(f"Moment magnitude: {model.Mw():.1f}")
```
