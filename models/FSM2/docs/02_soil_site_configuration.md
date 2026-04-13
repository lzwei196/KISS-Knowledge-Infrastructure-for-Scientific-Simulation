# Stage 2: Soil and Site Configuration

## Purpose

Configure soil properties and site characteristics for FSM2 via the Fortran
namelist file. FSM2 derives soil thermal and hydraulic properties from clay and
sand fractions using pedotransfer functions.

## Inputs

| Parameter | Source | Description |
|-----------|--------|-------------|
| fcly | HWSD, SoilGrids, field data | Soil clay fraction (0-1) |
| fsnd | HWSD, SoilGrids, field data | Soil sand fraction (0-1) |
| lat | Site coordinates | Latitude in degrees (converted internally) |
| zT | Station metadata | Temperature/humidity measurement height (m) |
| zU | Station metadata | Wind speed measurement height (m) |
| alb0 | Literature, MODIS | Snow-free ground albedo (0-1) |
| vegh | Field data, lidar | Canopy height (m), 0 for open site |
| VAI | Field data, MODIS LAI | Vegetation area index (dimensionless) |

## Outputs

- Namelist file (e.g., `nlst_site.txt`) with 6 namelist blocks
- Derived soil properties (computed internally by FSM2):
  - Clapp-Hornberger exponent b
  - Volumetric heat capacity of dry soil (J/K/m³)
  - Saturated soil water pressure (m)
  - Porosity Vsat
  - Critical moisture Vcrit
  - Thermal conductivity (W/m/K)

## Procedure

1. **Obtain soil texture** from HWSD or SoilGrids for the site location.
2. **Compute fcly and fsnd**:
   - fcly = clay_percent / 100
   - fsnd = sand_percent / 100
   - Verify: fcly + fsnd ≤ 1 (remainder is silt)
3. **Set vegetation parameters**:
   - Open site: vegh = 0, VAI = 0
   - Forest: vegh = canopy height (m), VAI = vegetation area index (typically 1-6)
4. **Set measurement heights**:
   - zT, zU = height of AWS instruments above ground
   - For forest sites with above-canopy measurements: zT, zU > vegh
5. **Write namelist** with all 6 blocks in order.

## Verification

- Check fcly + fsnd ≤ 1.0
- Derived b should be in range 2-15
- Derived Vsat should be 0.3-0.6
- If vegh > 0, VAI should also be > 0 (and vice versa)
- zT, zU should be > vegh for above-canopy sites

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| fcly + fsnd > 1 | Unphysical soil properties | Check data source, normalize |
| fcly and fsnd both 0 | Division by zero in hcap_soil | Use default (0.3, 0.6) |
| lat in radians in namelist | Wrong solar position | Enter degrees (FSM2 converts) |
| vegh > 0 but VAI = 0 | Canopy has no radiative effect | Set VAI > 0 for forest |
| zT < vegh | Measurement below canopy top | Use ZOFFST=1 or adjust height |
| Missing &initial block | Namelist read error | Include empty block: `&initial /` |

## Example

```python
from ki.tools.convert_soil_params import convert_soil

params = convert_soil(texture_class="sandy_loam", output_file="params_block.txt")
# Output: fcly=0.10, fsnd=0.65, b=4.47, Vsat=0.41
```

### Example namelist

```fortran
&params
  fcly = 0.10
  fsnd = 0.65
/
&gridpnts
  Npnts = 1
/
&gridlevs
/
&drive
  met_file = 'met_site.txt'
  lat = 47.05
  zT = 2
  zU = 10
/
&veg
  alb0 = 0.2
  vegh = 0
  VAI  = 0
/
&initial
/
&outputs
  runid = 'test_'
/
```
