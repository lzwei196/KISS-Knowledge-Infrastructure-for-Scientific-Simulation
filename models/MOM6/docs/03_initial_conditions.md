# Stage 3: Initial and Boundary Conditions

## Purpose

Prepare the initial ocean state (temperature, salinity, layer thickness, velocity)
and optional open boundary conditions for regional simulations. Correct initialization
prevents model spin-up artifacts and ensures physical consistency.

## Inputs

| Source        | Variables        | Format        | Typical Resolution |
|---------------|------------------|---------------|--------------------|
| WOA18 (World Ocean Atlas) | temperature, salinity | NetCDF | 0.25° monthly |
| PHC3 (Polar Hydrographic Climatology) | t_an, s_an | NetCDF | 1° annual |
| HYCOM/GLORYS reanalysis | temp, salt, u, v, ssh | NetCDF | 1/12° daily |
| Parent model restart | MOM.res.nc | NetCDF | Model grid |

### Variable Units in Source Data

| Variable    | WOA18 Unit     | MOM6 Expected     | Conversion                |
|-------------|----------------|--------------------|-----------------------------|
| Temperature | degC (in-situ) | degC (potential)   | Use pressure-correction     |
| Salinity    | PSU (practical)| PSU or g/kg        | Depends on EOS choice       |
| Depth       | m (positive down) | m (positive down) | No conversion needed      |

## Outputs

| File              | Variables           | Units        | Description             |
|-------------------|---------------------|--------------|-------------------------|
| `INPUT/MOM_IC.nc` | temp, salt, h, u, v | degC, PSU, m, m/s | Initial state      |
| `INPUT/OBC_*.nc`  | temp, salt, u, v, ssh | degC, PSU, m, m/s | Boundary segments |

## Procedure

### Initial Conditions

1. **Obtain climatology** (WOA18 recommended for ocean-only runs):
   ```bash
   # Download WOA18 temperature and salinity on standard depth levels
   wget https://www.ncei.noaa.gov/data/oceans/woa/WOA18/DATA/temperature/netcdf/decav81B0/1.00/woa18_decav81B0_t00_01.nc
   ```

2. **Interpolate to model grid**:
   - Horizontal: bilinear or conservative remapping
   - Vertical: linear interpolation from z-levels to model layers
   - Land fill: extrapolate ocean values into topographic gaps

3. **Set MOM_input parameters**:
   ```fortran
   TS_CONFIG = "file"
   TEMP_FILE = "MOM_IC.nc"
   SALT_FILE = "MOM_IC.nc"
   TEMP_VAR = "temp"
   SALT_VAR = "salt"
   T_REF = 10.0       ! Reference temperature [degC]
   S_REF = 35.0       ! Reference salinity [PSU]
   VELOCITY_CONFIG = "zero"  ! Start from rest (typical)
   ```

4. **EOS consistency check**:
   - If `EQUATION_OF_STATE = "TEOS10"`: T must be conservative temperature, S must be absolute salinity
   - If `EQUATION_OF_STATE = "WRIGHT"` or `"UNESCO"`: T is potential temperature, S is practical salinity

### Open Boundary Conditions (Regional)

1. **Define boundary segments** in MOM_input:
   ```fortran
   OBC_NUMBER_OF_SEGMENTS = 4
   OBC_SEGMENT_001 = "I=0,J=0:N,FLATHER,ORLANSKI"
   OBC_SEGMENT_002 = "I=N,J=0:N,FLATHER,ORLANSKI"
   ! ...
   ```

2. **Extract boundary data** from parent model on each segment

3. **Ensure temporal resolution** is sufficient (daily or 5-day recommended)

## Verification

- [ ] Temperature in range [-2, 35] degC for global; no fill values in ocean
- [ ] Salinity in range [0, 42] PSU; typically 33-37 for open ocean
- [ ] No NaN/fill values within the ocean mask
- [ ] T/S type matches chosen equation of state
- [ ] Layer thicknesses are non-negative and sum to total depth
- [ ] OBC segments cover the full boundary extent

## Traps

| Trap ID | Symptom                        | Cause                              | Fix                        |
|---------|--------------------------------|------------------------------------|----------------------------|
| dt_002  | Density drift over decades     | Potential temp used with TEOS10    | Convert to conservative T  |
| dt_003  | Subtle salinity bias           | Absolute salinity used with Wright | Convert to practical S     |
| dt_006  | Crash: negative thickness      | Non-Boussinesq h in kg/m² with Boussinesq model | Divide by rho_0 |
| -       | Noisy initial currents         | Unbalanced T/S initialization      | Start from rest, allow geostrophic adjustment |
| -       | Persistent model drift         | Climatological IC too far from forcing period | Use reanalysis IC for the start year |

## Example

```python
import netCDF4
import numpy as np

# Verify IC file
ds = netCDF4.Dataset("INPUT/MOM_IC.nc", "r")
temp = ds.variables["temp"][:]
salt = ds.variables["salt"][:]
print(f"Temperature: {np.nanmin(temp):.2f} to {np.nanmax(temp):.2f} degC")
print(f"Salinity:    {np.nanmin(salt):.2f} to {np.nanmax(salt):.2f} PSU")

# Check for EOS consistency
eos = "WRIGHT"  # from MOM_input
if eos == "TEOS10":
    assert np.nanmax(temp) < 35, "Conservative temp should be < 35 degC"
ds.close()
```
