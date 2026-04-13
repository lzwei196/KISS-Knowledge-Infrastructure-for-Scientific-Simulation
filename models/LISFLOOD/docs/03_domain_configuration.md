# Stage 3: Domain and Channel Network Configuration

## Purpose

Set up the LISFLOOD spatial domain, drainage network, channel geometry, and the settings XML that ties everything together. This stage connects the static maps, forcing data, and model parameters into a runnable configuration.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| DEM | SRTM, MERIT | GeoTIFF → NetCDF/PCRaster | For deriving slopes, LDD |
| LDD | Derived from DEM | PCRaster (values 1-9) | Local Drainage Direction |
| Channel network | Derived from LDD | PCRaster (boolean) | 1 = channel pixel |
| Gauge locations | User-defined | Coordinates or map | Discharge reporting points |
| Elevation | From DEM | NetCDF/PCRaster | Used for snow model |
| Land use fractions | CLC, GlobCover | NetCDF/PCRaster | OtherFraction, ForestFraction, etc. |

## Outputs

| Output | Description |
|--------|-------------|
| `settings.xml` | Complete LISFLOOD configuration file |
| `MaskMap` | Binary domain mask |
| `Ldd` | Local Drainage Direction (PCRaster format) |
| `Channels` | Channel network mask |
| `ChanBottomWidth`, `ChanGrad`, `ChanLength`, `ChanManMaps` | Channel geometry |
| `Outlets`, `Gauges` | Gauge point maps |

## Procedure

1. **Create MaskMap**: Binary map defining the simulation domain (1=active, 0=outside)
2. **Generate LDD** from DEM using PCRaster `lddcreate`:
   - LDD uses PCRaster encoding: 1-9 where 5=pit/outlet
   - **NOT** ArcGIS D8 encoding (1,2,4,8,16,32,64,128)
3. **Derive channel network**: Apply upstream area threshold
4. **Set channel geometry**:
   - `ChanBottomWidth` [m]: derived from upstream area or geomorphic relations
   - `ChanGrad` [m/m]: channel slope from DEM (NOT in percent)
   - `ChanLength` [m]: pixel-to-pixel distance along channel (NOT in km)
   - `ChanManMaps` [s/m^(1/3)]: Manning's roughness coefficient
5. **Configure settings XML**:
   - Set `PathRoot`, `PathOut`, `PathMeteo`, `PathMaps`, `PathInit`
   - Set time period: `CalendarDayStart`, `StepStart`, `StepEnd`, `DtSec`
   - Enable/disable modules: `simulateLakes`, `simulateReservoirs`, etc.
   - Set calibration parameters as `<textvar>` elements
   - Map variable names to file paths in `<lfbinding>`

## Verification

- [ ] LDD uses PCRaster encoding (values 1-9 only, 5=pit)
- [ ] LDD has exactly one pit at the basin outlet
- [ ] All channel pixels have LDD pointing downstream
- [ ] MaskMap covers entire study area
- [ ] Channel gradient values are positive and < 1
- [ ] ChanLength values are in meters (100-10000 m typical)
- [ ] Settings XML is valid and all paths resolve correctly

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| dt_006 | fatal | LDD uses ArcGIS D8 encoding instead of PCRaster — water routes incorrectly |
| dt_009 | **silent** | CalChanMan set to Manning's n (0.03-0.05) instead of multiplier (~1.0) — routing speed wrong |
| dt_010 | fatal | StepStart/StepEnd format doesn't match CalendarDayStart — wrong period or crash |
| dt_011 | fatal | MaskMap path not found — LISFLOOD crashes immediately |

## Example

### Settings XML key sections:

```xml
<!-- Time configuration -->
<textvar name="CalendarDayStart" value="02/01/1990 06:00"/>
<textvar name="StepStart" value="02/01/1990 06:00"/>
<textvar name="StepEnd"   value="02/01/2010 06:00"/>
<textvar name="DtSec"     value="86400"/>  <!-- Daily timestep -->
<textvar name="DtSecChannel" value="3600"/>  <!-- 1-hour routing sub-step -->

<!-- Paths -->
<textvar name="PathRoot"  value="/data/lisflood/"/>
<textvar name="PathOut"   value="$(PathRoot)/out"/>
<textvar name="PathMeteo" value="$(PathRoot)/forcings"/>
<textvar name="PathMaps"  value="$(PathRoot)/maps"/>
<textvar name="PathInit"  value="$(PathRoot)/init"/>

<!-- Domain -->
<textvar name="MaskMap" value="$(PathMaps)/mask"/>
<textvar name="Gauges" value="$(PathMaps)/gauges"/>

<!-- Calibration (these are MULTIPLIERS, not raw values) -->
<textvar name="CalChanMan" value="1.0"/>  <!-- multiplier on Manning's n -->
<textvar name="UpperZoneTimeConstant" value="10"/>  <!-- days -->
<textvar name="LowerZoneTimeConstant" value="200"/>  <!-- days -->
```

### LDD creation with PCRaster:

```python
from pcraster import *
setclone("dem.map")
dem = readmap("dem.map")
ldd = lddcreate(dem, 1e31, 1e31, 1e31, 1e31)
report(ldd, "ldd.map")
```
