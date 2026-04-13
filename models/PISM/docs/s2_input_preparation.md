# S2: Input Preparation — Bootstrap File Creation

## Purpose

Prepare a NetCDF bootstrap file containing ice sheet geometry, bedrock topography,
climate forcing, and geothermal heat flux for PISM initialization. This is the most
error-prone stage — unit conversion mistakes here propagate silently through the
entire simulation.

## Inputs

| Source Dataset | Variables | Common Format |
|---------------|-----------|---------------|
| SeaRISE Greenland | topg, thk, precip, temp | NetCDF, 5 km |
| BedMachine v5 | bed, thickness, surface | NetCDF, 150 m |
| ALBMAP Antarctica | topg, thk, bheatflx | NetCDF, 5 km |
| Shapiro & Ritzwoller (2004) | ghf | NetCDF, various |
| ERA5 / RACMO | temperature, precipitation | NetCDF, various |

## Outputs

| Output | Format | Variables |
|--------|--------|-----------|
| Bootstrap file | NetCDF4 | `topg`, `thk`, `ice_surface_temp`, `precipitation`, `climatic_mass_balance`, `bheatflx` |
| Paleo-temperature file | NetCDF4 | `delta_T` (time series) |
| Paleo-sea-level file | NetCDF4 | `delta_SL` (time series) |

## Procedure

### Step 1: Download Source Data

```bash
# SeaRISE Greenland
wget https://zenodo.org/records/10179093/files/Greenland_5km_v1.1.nc

# Or use PISM's preprocess script
cd examples/std-greenland
./preprocess.sh
```

### Step 2: Extract and Rename Variables

Use NCO tools to prepare the bootstrap file:

```bash
DATANAME=Greenland_5km_v1.1.nc
PISMNAME=pism_Greenland_5km_v1.1.nc

# Extract needed variables
ncks -O -v mapping,lat,lon,bheatflx,topg,thk,presprcp,smb,airtemp2m \
  $DATANAME $PISMNAME
```

### Step 3: Unit Conversions (CRITICAL)

**Precipitation: m w.e./year → kg m^-2 year^-1**
```bash
# Multiply by water density (1000 kg/m³)
ncap2 -O -s "precipitation=presprcp*1000.0" $PISMNAME $PISMNAME
ncatted -O -a units,precipitation,m,c,"kg m^-2 year^-1" $PISMNAME
```

**Surface Mass Balance: m w.e./year → kg m^-2 year^-1**
```bash
ncap2 -O -s "climatic_mass_balance=1000.0*smb" $PISMNAME $PISMNAME
ncatted -O -a units,climatic_mass_balance,m,c,"kg m^-2 year^-1" $PISMNAME
```

**Temperature: must be in kelvin or degree_Celsius**
```bash
ncrename -O -v airtemp2m,ice_surface_temp $PISMNAME
ncatted -O -a units,ice_surface_temp,c,c,"degree_Celsius" $PISMNAME
```

**Geothermal Heat Flux: verify units are W/m²**
```bash
# If source is in mW/m², convert:
ncap2 -O -s "bheatflx=bheatflx*0.001" $PISMNAME $PISMNAME  # mW → W
ncatted -O -a units,bheatflx,m,c,"W m-2" $PISMNAME
```

### Step 4: Handle Ice-Free Regions

Where ice thickness is zero, surface mass balance may be missing or zero. Set a
reasonable default:

```bash
# Set -1000 kg/m²/year (= -1 m/year ablation) where no ice
ncap2 -O -s "where(thk <= 0.0){climatic_mass_balance=-1000.0;}" \
  $PISMNAME $PISMNAME
```

### Step 5: Add Projection Metadata

```bash
ncatted -O -a proj,global,c,c,"+proj=stere +lat_0=90 +lat_ts=71 +lon_0=-39 ..." \
  $PISMNAME
```

### Step 6: Add Retreat Mask (Optional)

```bash
ncap2 -A \
  -s 'land_ice_area_fraction_retreat=0*thk' \
  -s 'where(thk > 0 || topg > 0) land_ice_area_fraction_retreat=1' \
  -s 'land_ice_area_fraction_retreat@units="1"' \
  $PISMNAME $PISMNAME
```

## Verification

```bash
# Check variable names and units
ncdump -h $PISMNAME | grep -E "(thk|topg|precipitation|ice_surface_temp|bheatflx|climatic)"

# Verify value ranges
python3 -c "
from netCDF4 import Dataset
ds = Dataset('$PISMNAME')
for v in ['topg','thk','precipitation','ice_surface_temp','bheatflx','climatic_mass_balance']:
    if v in ds.variables:
        d = ds.variables[v][:]
        print(f'{v}: min={d.min():.2f}, max={d.max():.2f}, units={ds.variables[v].units}')
ds.close()
"
```

**Expected ranges:**

| Variable | Min | Max | Units |
|----------|-----|-----|-------|
| `topg` | -5500 | 3700 | m |
| `thk` | 0 | 3400 | m |
| `precipitation` | 0 | 5000 | kg m^-2 year^-1 |
| `ice_surface_temp` | -50 | 20 | °C (or 223–293 K) |
| `bheatflx` | 0.02 | 0.15 | W m^-2 |
| `climatic_mass_balance` | -5000 | 3000 | kg m^-2 year^-1 |

## Traps

| Trap | Severity | Diagnostic |
|------|----------|-----------|
| Precip in m w.e. not kg m^-2 | FATAL | 1000× too little precipitation → no ice |
| SMB in m w.e. not kg m^-2 | FATAL | Mass balance completely wrong |
| Temperature in °C when K expected | FATAL | Negative kelvin → crash or no ice |
| Heat flux in mW not W | SILENT | Basal temps 1000× too high |
| Missing ice-free SMB | SILENT | Zero SMB in ice-free areas → spurious ice growth |
| Wrong variable names | FATAL | PISM can't find required fields |

## Example

```bash
# Using the KI tool:
python ki/tools/convert_geometry.py \
  --input Greenland_5km_v1.1.nc \
  --output pism_Greenland.nc \
  --topg-var topg --thk-var thk \
  --bheatflx-var bheatflx --bheatflx-units "mW/m2" \
  --projection "+proj=stere +lat_0=90 +lat_ts=71 +lon_0=-39 +k=1 +x_0=0 +y_0=0 +ellps=WGS84"
```
