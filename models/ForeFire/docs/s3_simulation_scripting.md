# Stage 3: Simulation Scripting (.ff Files)

## Purpose

Create ForeFire simulation scripts that define the domain, load data, set parameters, ignite fires, apply wind forcing, and run the simulation. The `.ff` script is the primary interface for driving ForeFire simulations.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Landscape data | `data.nc` (NetCDF) | Stage 1 | Elevation, fuel, wind grids |
| Fuel table | `fuels.csv` (CSV) | Stage 2 | Fuel properties |
| Ignition points | Coordinates | User/historical data | Fire origin locations |
| Wind conditions | Speed/direction | Weather data | Wind forcing (time-varying optional) |
| Simulation period | Seconds | User | Duration of simulation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `simulation.ff` | ForeFire script | Complete simulation script |
| Fire output | KML/GeoJSON/NetCDF/FF | Simulation results |

## Procedure

### Step 1: Set Parameters

```
setParameter[fuelsTableFile=fuels.csv]
setParameter[propagationModel=Rothermel]
setParameter[ForeFireDataDirectory=.]
setParameter[spatialIncrement=3]
setParameter[perimeterResolution=10]
setParameter[minSpeed=0.009]
setParameter[dumpMode=geojson]
```

Key parameter choices:
- `propagationModel`: Must match fuels.csv format (Rothermel, Balbi2020, RothermelAndrews2018, Farsite, Iso)
- `spatialIncrement`: Spatial resolution in meters (smaller = more accurate, slower)
- `perimeterResolution`: Node spacing on fire front (meters)
- `propagationSpeedAdjustmentFactor`: Global ROS multiplier (default 1.0, lower = slower fire)
- `windReductionFactor`: Wind reduction for canopy effects (0-1, default 1.0)

### Step 2: Load Data

```
loadData[data.nc;2025-02-10T17:35:54Z]
```

The timestamp must match the one used when creating data.nc. It sets the reference time for the simulation.

### Step 3: Ignite Fire

Two coordinate systems available:

```
# UTM coordinates (meters)
startFire[loc=(35881.873,28699.674,0);t=0]

# Longitude/Latitude (degrees)
startFire[lonlat=(8.70,41.952,0);t=0]
```

Multiple ignition points are supported:
```
startFire[loc=(35881,28699,0);t=0]
startFire[loc=(35581,28699,0);t=0]
startFire[loc=(35181,28699,0);t=300]  # delayed ignition at t=300s
```

### Step 4: Apply Wind

```
# Constant wind
trigger[wind;loc=(0.,0.,0.);vel=(10.0,5.0,0.)]

# Time-varying wind (triggered at specific simulation time)
trigger[wind;loc=(0.,0.,0.);vel=(10.0,0.7,0.)]@t=1200
trigger[wind;loc=(0.,0.,0.);vel=(5.0,8.0,0.)]@t=3600
```

Wind velocity: `vel=(u, v, w)` where u=eastward, v=northward, w=vertical (m/s).

### Step 5: Run Simulation

```
# Run for specific duration (seconds)
step[dt=3600]

# Or advance to absolute time
goTo[t=7200]
```

### Step 6: Save Output

```
# Print fire front to file
print[output.geojson]

# Save full state to NetCDF
save[]

# Print to reload file (for continuing later)
print[to_reload.ff]
```

## Verification

- Script syntax: Each command must be `commandName[args]` on its own line
- Comments: Lines starting with `#` are comments
- Parameter names are case-sensitive
- Time is in seconds from domain creation
- Coordinates must be within the domain bounds (sw to ne)
- Wind components must be in m/s

## Traps

### Trap 1: Ignition outside domain
**Symptom**: No fire appears, or "node outside domain" errors.
**Cause**: `startFire` coordinates are outside the `FireDomain[sw=...;ne=...]` bounds.
**Fix**: Verify ignition point is within the domain. When using loadData, the domain is set from the NetCDF extent.

### Trap 2: Time reference mismatch
**Symptom**: Wind triggers don't fire, or fire at wrong time.
**Cause**: The `@t=` time in trigger commands is absolute time from domain start, not relative.
**Fix**: Ensure trigger times are consistent with `step[dt=]` accumulation.

### Trap 3: Missing include order
**Symptom**: Parameters not applied, missing fuels table.
**Cause**: `include[params.ff]` must come before `loadData` and `startFire`.
**Fix**: Order: parameters → loadData → startFire → trigger → step → print.

### Trap 4: Using lonlat without proper projection setup
**Symptom**: Fire appears at wrong location.
**Cause**: `startFire[lonlat=...]` requires the domain to have UTM projection info.
**Fix**: Ensure data.nc was created with proper UTM coordinates.

## Example

Complete simulation script:
```
# params
setParameter[fuelsTableFile=fuels.csv]
setParameter[propagationModel=Rothermel]
setParameter[spatialIncrement=3]
setParameter[perimeterResolution=10]
setParameter[propagationSpeedAdjustmentFactor=0.6]
setParameter[windReductionFactor=0.4]
setParameter[dumpMode=geojson]
setParameter[ForeFireDataDirectory=.]

# load landscape
loadData[data.nc;2025-02-10T17:35:54Z]

# ignition
startFire[lonlat=(8.70,41.952,0);t=0]

# wind
trigger[wind;loc=(0.,0.,0.);vel=(10,5,0.)]

# run 1 hour
goTo[t=3600]

# save output
print[result.geojson]
save[]
```

Run with:
```bash
forefire -i simulation.ff
```
