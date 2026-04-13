# Stage 5: Model Configuration

## Purpose

Assemble the master configuration file (MDU for D-Flow FM, MDF for Delft3D-FLOW)
and the DIMR orchestration file. This stage integrates all upstream outputs
(grid, bathymetry, forcing, boundaries) into a complete simulation setup.

## Inputs

| Input | From Stage | Description |
|-------|-----------|-------------|
| Grid file | s1 | _net.nc (unstructured) or .grd (structured) |
| Bathymetry | s2 | Depths embedded in grid or separate .dep |
| Forcing files | s3 | .wnd, .amp, .amt, .amr, .amc |
| Boundary files | s4 | .ext, .bc, .pli (D-Flow FM) or .bnd, .bch (FLOW) |
| Observation points | User | .xyn or .obs |
| Cross-sections | User | .pli or .crs |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| MDU file | .mdu | D-Flow FM master configuration |
| MDF file | .mdf | Delft3D-FLOW master configuration |
| DIMR config | .xml | Component orchestration |
| Output directory | directory | Must be created before run |

## Procedure

### D-Flow FM (MDU File)

1. **Create MDU** from template or scratch
2. **Set [geometry]**: grid file, bathymetry, structures, dry points, latitude
3. **Set [physics]**: friction (Chezy/Manning), viscosity, salinity, temperature
4. **Set [time]**: reference date, start/stop, timestep, Tunit
5. **Set [numerics]**: CFL limit, solver type, time integration
6. **Set [external forcing]**: link to .ext file
7. **Set [output]**: output directory, file names, intervals, variables
8. **Set [wind]**: wind drag model if using wind forcing

### Key Parameters to Verify

```ini
# CRITICAL: these must be consistent
[time]
RefDate    = 20200101       # Must match forcing/boundary reference
Tunit      = S              # S=seconds, M=minutes, H=hours
TStart     = 0              # In Tunit since RefDate
TStop      = 2592000        # 30 days in seconds
DtMax      = 30             # Max timestep [seconds, always in seconds]

[physics]
UnifFrictType = 0           # 0=Chezy, 1=Manning — KNOW WHICH ONE
UnifFrictCoef = 65          # Chezy: 40-70; Manning: 0.015-0.05

[numerics]
CFLMax     = 0.7            # Keep < 1.0 for stability

[output]
OutputDir  = output         # THIS DIRECTORY MUST EXIST
MapInterval = 3600          # Map output every hour [seconds]
HisInterval = 600           # History every 10 min [seconds]
```

### DIMR Configuration

```xml
<?xml version="1.0" encoding="utf-8"?>
<dimrConfig>
  <documentation>
    <fileVersion>1.3</fileVersion>
  </documentation>
  <control>
    <start name="DFlowFM"/>
  </control>
  <component name="DFlowFM">
    <library>dflowfm</library>
    <workingDir>dflowfm</workingDir>
    <inputFile>model.mdu</inputFile>
  </component>
</dimrConfig>
```

### Coupled Simulation (Flow + Waves)

```xml
<control>
  <parallel>
    <startGroup>
      <time>0 3600 999999</time>   <!-- coupling interval: 1 hour -->
      <start name="DFlowFM"/>
      <coupler name="flow_to_wave"/>
      <start name="DWaves"/>
      <coupler name="wave_to_flow"/>
    </startGroup>
  </parallel>
</control>
```

## Verification

1. **All referenced files exist**: check every file path in MDU/MDF
2. **Time consistency**: RefDate, TStart, TStop, boundary times, forcing times
   must all be in the same reference frame
3. **Unit consistency**: Tunit, friction type, coordinate system
4. **Output directory exists**: create it if not
5. **CFL check**: DtMax × sqrt(g × h_max) / dx_min < CFLMax

```bash
# Preflight check
python ki/tools/run_delft3d.py \
  --dimr_config dimr_config.xml \
  --binary_dir /path/to/bin \
  --skip_preflight  # remove to enable checks
```

## Traps

1. **Chezy vs Manning confusion (dt_007)**: if UnifFrictType=0 (Chezy) but
   you set UnifFrictCoef=0.025 (a Manning value), the friction is enormous.
   Chezy=0.025 means nearly infinite roughness. The flow will be near-zero.
   **Always check that friction TYPE matches friction VALUE.**

2. **Tunit mismatch (dt_008)**: all time parameters are in Tunit units.
   If Tunit=M and you set DtUser=300, that's 300 minutes = 5 hours, not
   300 seconds = 5 minutes. Only DtMax is always in seconds.

3. **Output directory missing**: D-Flow FM does NOT create OutputDir automatically.
   ```bash
   mkdir -p dflowfm/output  # Create before running
   ```

4. **3D vs 2D confusion**: Kmx=0 means 2D mode. Kmx=10 means 10 vertical sigma
   layers. 3D mode is ~10x slower and requires additional settings (vertical
   viscosity, turbulence model). Don't enable 3D unless you need it.

5. **Observation point coordinate mismatch**: .xyn coordinates must be in the
   same CRS as the grid. If grid is in UTM but .xyn has lat/lon, all
   observation points will be outside the domain → empty _his.nc.

## Example

```python
# Generate a minimal MDU file programmatically
mdu_content = """[General]
Program    = D-Flow FM
Version    = 1.2.115.xxxxx
AutoStart  = 1

[geometry]
NetFile    = domain_net.nc
AngLat     = 52.0
Kmx        = 0

[numerics]
CFLMax     = 0.7
Icgsolver  = 4

[physics]
UnifFrictCoef = 65
UnifFrictType = 0
Vicouv     = 1

[time]
RefDate    = 20200101
Tunit      = S
DtUser     = 300
DtMax      = 30
TStart     = 0
TStop      = 86400

[external forcing]
ExtForceFileNew = boundary.ext

[output]
OutputDir  = output
HisFile    = model_his.nc
HisInterval = 600
MapFile    = model_map.nc
MapInterval = 3600
"""

with open("dflowfm/model.mdu", "w") as f:
    f.write(mdu_content)
```
