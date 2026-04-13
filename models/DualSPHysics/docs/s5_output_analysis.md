# Stage 5: Output Analysis and Post-Processing

## Purpose

Extract, visualize, and analyze simulation results. DualSPHysics outputs binary bi4 files that must be converted to VTK (for visualization) or CSV (for analysis). This stage also includes force computation, surface extraction, and comparison with experimental/observed data.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| `Part_XXXX.bi4` | Binary | Stage 4 output |
| `PartOut_XXXX.bi4` | Binary | Stage 4 excluded particles |
| `RUN.out` | Text | Stage 4 simulation log |
| Measurement points | TXT | User-defined probe locations |
| Experimental data | CSV/TXT | Literature, lab experiments |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Particle VTK | `.vtk` | Particle data for ParaView |
| Point measurements | `.csv` | Time series at specified points |
| Force data | `.csv` | Forces on structures |
| Surface VTK | `.vtk` | Free-surface isosurface |
| Slice VTK | `.vtk` | Cross-section slices |

## Procedure

### A. Convert to VTK (PartVTK)

```bash
# Fluid particles only
PartVTK -dirdata output/data -savevtk output/PartFluid -onlytype:-all,+fluid

# Boundary particles only
PartVTK -dirdata output/data -savevtk output/PartBound -onlytype:-all,+bound

# Specific MK group
PartVTK -dirdata output/data -savevtk output/PartMk1 -onlymk:1

# With specific variables
PartVTK -dirdata output/data -savevtk output/PartFluid -onlytype:-all,+fluid -vars:+vel,+press,+rhop
```

### B. Point Interpolation (MeasureTool)

Create a points file (space-separated x y z):
```
# Pressure probes
0.5 0.335 0.021
0.5 0.335 0.042
0.5 0.335 0.063
```

Run MeasureTool:
```bash
MeasureTool -dirdata output/data -points probes.txt -onlytype:-all,+fluid \
  -vars:-all,+vel.x,+vel.y,+vel.z,+press,+rhop \
  -kcusedummy:0 -kclimit:0.5 \
  -savecsv output/probes -savevtk output/probes
```

### C. Force Computation (ComputeForces)

```bash
ComputeForces -dirdata output/data -onlymk:20 -viscoart:0.1 \
  -savecsv output/forces
```

### D. Surface Extraction (IsoSurface)

```bash
IsoSurface -dirdata output/data -saveiso output/Surface \
  -vars:-all,vel,rhop \
  -saveslice output/Slices \
  -slicevec:0:0.5:0:0:1:0
```

## Verification

- [ ] VTK files open correctly in ParaView
- [ ] CSV files have expected columns and time steps
- [ ] Pressure values are physically reasonable (0 - few kPa for water)
- [ ] Velocity values are reasonable for the scenario
- [ ] Forces are in expected range
- [ ] No NaN or Inf values in output

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Points outside fluid domain | Zero/NaN interpolation | Move points inside fluid |
| Wrong -onlytype flag | Empty output | Use -onlytype:-all,+fluid |
| MeasureTool timeout | Large datasets | Reduce number of points/timesteps |
| Pressure includes hydrostatic | Offset values | Subtract rhop0*g*z |
| kclimit too strict | Gaps in CSV data | Reduce kclimit or use -kcusedummy:0 |
| Forces on wrong MK | Zero force | Check MK number with -onlymk:N |
| CSV separator | Parsing errors | Check -csvsep:0 (semicolon) or -csvsep:1 (comma) |

## Output Variables

| Variable | PartVTK flag | Units | Description |
|----------|-------------|-------|-------------|
| Position | (always) | m | Particle center |
| Velocity | +vel | m/s | Particle velocity vector |
| Vel magnitude | +vel.m | m/s | Speed |
| Pressure | +press | Pa | Dynamic pressure |
| Density | +rhop | kg/m^3 | Particle density |
| Mass | +mass | kg | Particle mass |
| Type | +type | — | Particle type code |
| MK | +mk | — | Material marker |
| Id | +idp | — | Particle ID |

## Example: Complete Post-Processing Pipeline

```bash
export dirbin=bin/linux
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${dirbin}
export dirdata=output/data

# 1. Particles to VTK
${dirbin}/PartVTK_linux64 -dirdata ${dirdata} \
  -savevtk output/particles/Fluid -onlytype:-all,+fluid

# 2. Pressure at probes
${dirbin}/MeasureTool_linux64 -dirdata ${dirdata} \
  -points PressureProbes.txt -onlytype:-all,+fluid \
  -vars:-all,+press,+kcorr -kcusedummy:0 -kclimit:0.5 \
  -savecsv output/measurements/Pressure

# 3. Velocity at probes
${dirbin}/MeasureTool_linux64 -dirdata ${dirdata} \
  -points VelocityProbes.txt -onlytype:-all,+fluid \
  -vars:-all,+vel.x,+vel.y,+vel.z,+vel.m \
  -savecsv output/measurements/Velocity

# 4. Force on structure (MK=20)
${dirbin}/ComputeForces_linux64 -dirdata ${dirdata} \
  -onlymk:20 -viscoart:0.1 \
  -savecsv output/forces/Structure

# 5. Free surface
${dirbin}/IsoSurface_linux64 -dirdata ${dirdata} \
  -saveiso output/surface/Surface \
  -vars:-all,vel,rhop
```

## Validation Metrics

For comparison with experimental data:

| Metric | Formula | Good | Acceptable |
|--------|---------|------|------------|
| RMSE | sqrt(mean((sim-obs)^2)) | < 5% of range | < 10% |
| R^2 | 1 - SS_res/SS_tot | > 0.95 | > 0.85 |
| Max error | max(abs(sim-obs)) | < 10% | < 20% |
| Phase error | time shift of peaks | < dt_out | < 5*dt_out |
