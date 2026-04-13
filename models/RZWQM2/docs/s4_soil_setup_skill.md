# Skill Document: Soil Properties Configuration (S4)

**Stage:** s4_soil_setup
**Pipeline Order:** 4
**Depends On:** s1_site_config
**Tools:** `soil_texture_classification`, `pedotransfer_hydraulic`, `write_soil_properties`

---

## Purpose

Configure the complete soil profile for RZWQM2, including horizon depths, physical properties (texture, bulk density), hydraulic properties (Brooks-Corey parameters), micropore and macropore characteristics, infiltration parameters, and heat model settings. This is the most complex and sensitive configuration step in the entire pipeline. Soil hydraulic properties -- particularly saturated hydraulic conductivity (Ksat), effective porosity, macroporosity, and bubbling pressure -- are the most sensitive parameters in RZWQM2 and should be the primary targets during calibration. All soil properties are written to the `RZWQM.dat` file.

**Calibration priority:** When calibrating RZWQM2 for water balance, adjust soil hydraulic properties first. The order of sensitivity is approximately: Ksat > effective porosity > macroporosity > bubbling pressure > pore size distribution.

---

## Soil Data Source Priority

**Use HWSD global database as primary source** — not VIC soil converter.

| Priority | Source | Tool | When to use |
|----------|--------|------|-------------|
| **1 (primary)** | HWSD raster + MDB | `tools/s0_global_data/hwsd_soil_adapter.py` | Always — gives real sand/silt/clay/bulk density/OC per cell directly from the global HWSD database |
| 2 (fallback) | VIC soil params | `tools/s0_vic_coupling/vic_soil_converter.py` | Only if HWSD raster/MDB unavailable. **WARNING**: VIC soil file column layout varies — column indices in vic_soil_converter.py may not match actual file layout, causing wrong bulk_density/Wcr/Wpwp values and RZWQM2 crash. |
| 3 (API) | SoilGrids REST API | Manual query | For very specific sites with known coordinates |

**HWSD data paths** (shared with HydroCraft VIC):
- Global raster: `/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER/hwsd.bil` (1.8 GB, 30 arc-sec)
- MDB database: `/mnt/disk1/Hydrocraft_server/data/forcing/huaihe_raw/soil/HWSD.mdb` (32 MB, 16,108 mapping units)

```bash
# Get soil for a grid cell (returns topsoil + subsoil → 6 RZWQM2 horizons)
python knowledge_infrastructure/tools/s0_global_data/hwsd_soil_adapter.py \
  <lat> <lon> \
  /mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER/hwsd.bil \
  /mnt/disk1/Hydrocraft_server/data/forcing/huaihe_raw/soil/HWSD.mdb
```

## Prerequisites

1. A scenario directory exists with a template `RZWQM.dat` file (site configuration S1 completed).
2. Soil profile data is available from HWSD adapter (primary) or VIC converter (fallback): horizon depths (cm), texture (sand/silt/clay percentages), bulk density (g/cm^3).
3. Optionally: measured hydraulic properties (field capacity at 33 kPa, wilting point at 1500 kPa, Ksat).
4. Python environment with access to `rzwqm_file.py` (the `RZWQM` class and soil-related classes and functions).

---

## Inputs

### A. Horizon Depths

| Parameter | Type | Unit | Description | Constraints |
|-----------|------|------|-------------|-------------|
| `horizon_depths` | list of floats | cm | Depth to bottom of each horizon | Ascending order, max 20 horizons (MAXHOR), max depth 3000 cm |

Example: `[15.0, 30.0, 60.0, 100.0, 200.0]` for a 5-horizon profile.

### B. Physical Properties (per horizon)

| Parameter | Type | Unit | Description | Default |
|-----------|------|------|-------------|---------|
| `soil_name` | string | -- | Descriptive name for the horizon | `"Soil Horizon"` |
| `particle_density` | float | g/cm^3 | Mineral particle density | 2.65 (standard for most mineral soils) |
| `bulk_density` | float | g/cm^3 | Dry bulk density | Measured or estimated |
| `porosity` | float | fraction | Total porosity = 1 - (bulk_density / particle_density) | Calculated |
| `sand` | float | % | Sand fraction (0.05-2.0 mm) | Measured |
| `silt` | float | % | Silt fraction (0.002-0.05 mm) | silt = 100 - sand - clay |
| `clay` | float | % | Clay fraction (< 0.002 mm) | Measured |

### C. Hydraulic Properties - Brooks-Corey Parameters (per horizon)

These are written in the `SOIL HORIZON HYDRAULIC PROPERTIES` section. Each horizon requires 3 lines:

**Line 1 (7 values):**

| Parameter | Position | Unit | Description |
|-----------|----------|------|-------------|
| `horizon_num` | 1 | -- | Horizon number (1-based) |
| `bubbling_pressure` | 2 | cm H2O | Air-entry pressure (Brooks-Corey parameter) |
| `pore_size_dist` | 3 | -- | Pore size distribution index (lambda) |
| `eps` (N2) | 4 | -- | Exponent for unsaturated conductivity, typically = 2 + 3*lambda |
| `ksat` | 5 | cm/hr | Saturated hydraulic conductivity |
| `residual_wc` (wr) | 6 | fraction | Residual water content |
| `saturated_wc` (ws) | 7 | fraction | Saturated water content (approximately = porosity) |

**Line 2 (7 values):**

| Parameter | Position | Unit | Description |
|-----------|----------|------|-------------|
| `fc33` | 1 | fraction | Field capacity at 33 kPa (1/3 bar) |
| `fc10` | 2 | fraction | Water content at 10 kPa (1/10 bar) |
| `fc15` | 3 | fraction | Wilting point at 1500 kPa (15 bar) |
| `bubbling_pressure` | 4 | cm H2O | Repeated from line 1 |
| `C2` | 5 | -- | Second intercept for conductivity function |
| `0` | 6 | -- | Reserved (always 0) |
| `0` | 7 | -- | Reserved (always 0) |

**Line 3 (1 value):**

| Parameter | Position | Unit | Description |
|-----------|----------|------|-------------|
| `lateral_ksat` | 1 | cm/hr | Lateral saturated hydraulic conductivity |

### D. Micropore Properties (per horizon)

The micropore section contains a general header line followed by one line per horizon:

**Header line:**
```
0  1.0  4.4
```
Format: `flag  parameter1  parameter2` (typically fixed values).

**Per-horizon line (1 value):**

| Parameter | Unit | Description | Source |
|-----------|------|-------------|--------|
| `microporosity` | fraction | Volume fraction of micropores | Use `default_microporosity_for_each_soil_type(texture_class)` |

Default microporosity values by texture class:
| Texture | Default Microporosity |
|---------|----------------------|
| sand | 0.057 |
| loamy sand | 0.108 |
| sandy loam | 0.19 |
| loam | 0.254 |
| silt loam | 0.274 |
| silt | 0.274 |
| sandy clay loam | 0.347 |
| clay loam | 0.41 |
| silty clay loam | 0.452 |
| sandy clay | 0.52 |
| silty clay | 0.53 |
| clay | 0.564 |

### E. Macropore Properties

The macropore section has a general header (2 lines) followed by one line per horizon:

**General header:**
```
{macropores_present}  {sorptivity_factor}  {tile_drain_express}
{radial_holes}  {cracks_columns}
```

**Per-horizon line (6 values):**

| Parameter | Unit | Description | Typical Range |
|-----------|------|-------------|---------------|
| `total_macroporosity` | fraction | Total macropore volume fraction | 0.001-0.05 |
| `average_radius` | cm | Average macropore radius | 0.05-0.5 |
| `width` | cm | Width of macropore cracks | 0.01-0.1 |
| `crack_length` | cm | Length of cracks | 1-30 |
| `aggregate_length` | cm | Length of soil aggregates | 1-10 |
| `dead_end_fraction` | fraction | Fraction of dead-end pores | 0.0-1.0 |

### F. Infiltration Parameters (19 values on a single line)

| # | Parameter | Unit | Description | Default |
|---|-----------|------|-------------|---------|
| 1 | surface_crust_present | flag | 0=no crust, 1=crust present | 0 |
| 2 | crust_hydraulic_conductivity | cm/hr | Ksat of crust layer | 0.0 |
| 3 | bottom_boundary_condition | flag | 1=free drain, 2=water table, 3=lysimeter | 1 |
| 4 | field_saturation_fraction | fraction | Fraction of porosity filled at field sat | 0.95 |
| 5 | convergence_criteria | -- | Numerical convergence criterion | 0.001 |
| 6 | max_iterations | int | Maximum iterations per time step | 20 |
| 7 | max_cycles | int | Maximum cycles | 5 |
| 8 | management_cutoff_moisture | fraction | Cutoff moisture for management | 0.01 |
| 9 | perched_water_table | flag | 0=no, 1=yes | 0 |
| 10 | water_table_leakage_rate | cm/hr | Leakage rate if perched table | 0.0 |
| 11 | drains_present | flag | 0=no drains, 1=tile drains present | 0 or 1 |
| 12 | depth_to_drains | cm | Depth from surface to drain center | 100-200 |
| 13 | drain_spacing | cm | Horizontal spacing between drains | 500-3000 |
| 14 | drain_radius | cm | Radius of drain pipe | 5-15 |
| 15 | init_gradient_flow | flag | Initial gradient for flow calculation | 0 |
| 16 | lateral_hydraulic_gradient | fraction | Lateral gradient for subsurface flow | 0.0 |
| 17 | min_water_suction_head | cm | Minimum suction head | -10 |
| 18 | fc_suction_head | cm | Field capacity suction head | -333 |
| 19 | wp_suction_head | cm | Wilting point suction head | -15000 |

### G. Heat Model Parameters (per horizon)

| Parameter | Unit | Description | Default |
|-----------|------|-------------|---------|
| method_flag | int | Heat model method (2 = de Vries, recommended) | 2 |
| thermal_conductivity | W/m/K | Thermal conductivity (used if method != 2) | 1.0 |

---

## Procedure

### Step 1: Classify Soil Texture

For each horizon, determine the USDA texture class from sand and clay percentages:

```python
from rzwqm_file import soil_texture_setter

texture = soil_texture_setter(sand=45.0, clay=20.0)
# Returns: 'loam'
```

The function implements the full USDA soil texture triangle. It computes `silt = 100 - sand - clay` internally.

**Validation:** The function raises an exception if `sand + clay > 100` or if either value is negative.

### Step 2: Estimate Hydraulic Properties

If measured hydraulic properties are not available, use the default lookup table:

```python
from rzwqm_file import soil_default_setter

defaults = soil_default_setter('loam')
# Returns: {
#   "ws": 0.463,
#   "wr": 0.027,
#   "bubbling_pressure": 11.15,
#   "pore_size_dist": 0.22,
#   "fc33": 0.2334,
#   "fc15": 0.1163,
#   "ksat": 1.32
# }
```

If measured field capacity (fc33) and wilting point (fc15) are available, estimate pore size distribution and bubbling pressure:

```python
from rzwqm_file import pore_size_distribution_estimate, B_estimate, bubbling_pressure_estimate, N2_estimate, fc10_estimate

# Step 2a: Estimate pore size distribution
psd = pore_size_distribution_estimate(fc33=0.25, fc15=0.12, wr=0.03)

# Step 2b: Estimate N2 (eps)
n2 = N2_estimate(psd)  # = 2 + 3 * psd

# Step 2c: Estimate B coefficient
B = B_estimate(fc33=0.25, wr=0.03, pore_size_dist=psd)

# Step 2d: Estimate bubbling pressure
bp = bubbling_pressure_estimate(ws=0.45, pore_size_dist=psd, wr=0.03, B=B)

# Step 2e: Estimate fc10
fc10 = fc10_estimate(ws=0.45, wr=0.03, bubbling_pressure=bp, pore_size_dist=psd)
```

### Step 3: Create Soil Property Objects

For each horizon, create the appropriate class instances:

```python
from rzwqm_file import (
    soil_hydraulic_properties_each_horizon,
    soil_physical_properties_each_horizon,
    soil_macropore_properties_each_horizon,
    soil_macropore_general_properties,
    soil_infiltration_properties
)

# Physical properties
phys = soil_physical_properties_each_horizon(
    bulk_density=1.35,
    particle_density=2.65,
    sand=45.0,
    silt=35.0,
    clay=20.0
)
# phys.porosity is automatically calculated as 1 - (1.35/2.65) = 0.49

# Hydraulic properties
hydro = soil_hydraulic_properties_each_horizon(
    pore_size_dist=0.22,
    saturated_water_content=0.463,
    residual_water_content=0.027,
    bubbling_pressure=11.15,
    constant_for_oh=0,          # typically 0
    lateral_ksat=1.32,          # often same as ksat
    ksat=1.32,
    eps=2.66,                   # = 2 + 3 * 0.22
    second_intercept_c2=0.0,
    horizon_num=1,
    fc33=0.2334,
    fc10=0.30,
    fc15=0.1163
)

# Macropore properties per horizon
macro = soil_macropore_properties_each_horizon(
    total_macroporosity=0.01,
    average_radius=0.1,
    width=0.05,
    crack_length=10.0,
    length_of_aggregate=5.0,
    fraction_of_dead_end=0.5
)

# General macropore properties
macro_gen = soil_macropore_general_properties(
    macropores_present=1,       # 1 = yes
    sorptivity_factor=1.0,
    tile_drain_express=0,
    radial_holes=0,
    cracks_columns=1
)

# Infiltration properties
infilt = soil_infiltration_properties(
    surface_crust_present=0,
    crust_hydraulic_conductivity=0.0,
    bottom_boundry_condition=1,      # 1 = free drainage
    Field_saturation_fraction=0.95,
    Convergence_Criteria=0.001,
    Maximum_number_of_iterations=20,
    Maximum_number_of_cycles=5,
    Management_cutoff_threshold_for_soil_moisture_content=0.01,
    Perched_water_table=0,
    water_table_leakage_rate=0.0,
    Drains_are_present=1,            # 1 = tile drains
    depth_from_surface_to_drains=120.0,
    drain_spacing=1500.0,
    radius_of_drain=10.0,
    Init_gradient_flow=0,
    Lateral_hydraulic_gradient=0.0,
    Minimum_water_suction_head=-10.0,
    Field_Capacity_water_suction_head=-333.0,
    Wilting_Point_water_suction_head=-15000.0
)
```

### Step 4: Write Horizon Depths to RZWQM.dat

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)

# Write horizon depths
horizon_list = [15.0, 30.0, 60.0, 100.0, 200.0]
rz.write_soil_horizon_depth_to_dat(horizon_list)
```

This writes to the `SOIL PROPERTIES AND PARAMETERS` section. The first line contains `{num_horizons}  {max_depth}` and subsequent lines list individual horizon depths.

### Step 5: Write Physical Properties

```python
physical_dict = {
    1: phys_horizon_1,
    2: phys_horizon_2,
    # ... one entry per horizon
}
rz.write_new_soil_physical_properties_to_dat(physical_dict)
```

Each horizon generates 2 lines:
```
Soil Name
0  {particle_density}  {bulk_density}  {porosity} {sand}  {silt}  {clay}
```

### Step 6: Write Hydraulic Properties

```python
hydraulic_dict = {
    1: hydro_horizon_1,
    2: hydro_horizon_2,
    # ... one entry per horizon
}
rz.write_new_hydraulic_properties_to_dat(hydraulic_dict)
```

### Step 7: Write Micropore Properties

```python
from rzwqm_file import default_microporosity_for_each_soil_type

micropore_dict = {}
for i, texture in enumerate(texture_classes, 1):
    micropore_dict[i] = default_microporosity_for_each_soil_type(texture)

rz.write_new_soil_micropore_properties_to_dat(micropore_dict)
```

### Step 8: Write Macropore Properties

```python
macropore_dict = {
    1: macro_horizon_1,
    2: macro_horizon_2,
    # ...
}
rz.write_new_soil_macropore_properties_to_dat(macropore_dict, macro_gen)
```

### Step 9: Write Infiltration Properties

```python
rz.write_new_soil_infiltration_to_dat(infilt)
```

### Step 10: Write Heat Model Properties

```python
heat_dict = {}
for i in range(1, num_horizons + 1):
    heat_dict[i] = '2  1.0'  # method=2 (de Vries), thermal_conductivity=1.0
rz.write_new_soil_heat_properties_to_dat(heat_dict)
```

---

## Expected Outputs

- **Modified file:** `{project_path}/{station_id}/RZWQM.dat`
- **Sections modified:**
  - Soil horizon depths (count + individual depths)
  - Soil physical properties (2 lines per horizon: name + properties)
  - Soil hydraulic properties (3 lines per horizon)
  - Soil heat model parameters (1 line per horizon)
  - Micropore properties (header line + 1 line per horizon)
  - Macropore properties (2 header lines + 1 line per horizon)
  - Infiltration parameters (1 line with 19 values)

---

## Validation Checks

### Texture Validation
1. `sand + silt + clay = 100` (within rounding tolerance of +/- 1%).
2. `sand >= 0`, `silt >= 0`, `clay >= 0`.
3. `sand + clay <= 100` (the function checks this and raises an exception).

### Hydraulic Property Physical Consistency
1. `0 < wr < fc15 < fc33 < fc10 < ws < 1` -- water content values must be in ascending order.
2. `ws` should be approximately equal to porosity (`1 - bulk_density/particle_density`).
3. `ksat > 0` -- saturated hydraulic conductivity must be positive.
4. `bubbling_pressure > 0` -- air-entry pressure must be positive.
5. `pore_size_dist > 0` -- pore size distribution index must be positive.
6. `eps` (N2) should approximately equal `2 + 3 * pore_size_dist`.

### Horizon Depth Consistency
1. Horizon depths must be in **strictly ascending order**.
2. All depths must be positive.
3. Maximum depth must not exceed 3000 cm.
4. Number of horizons must not exceed 20 (MAXHOR).
5. **Critical:** Horizon depths in RZWQM.dat must match the number of horizons used in RZINIT.dat (see S6).

### Infiltration Parameter Validation
1. `drain_spacing > 0` if drains are present.
2. `drain_radius > 0` if drains are present.
3. `depth_to_drains > 0` and less than total profile depth if drains are present.
4. `wp_suction_head < fc_suction_head < min_water_suction_head < 0` (all negative, decreasing magnitude).

---

## Common Pitfalls

### PITFALL 1: Sand + Clay > 100 or Negative Values (FATAL CRASH)
**Severity:** Fatal -- the model will crash or the texture classification function will raise an exception.
**Symptom:** Python exception `'Inputs adds over 100% or are negative'` during texture classification.
**Cause:** Data entry error, unit confusion (fractions vs percentages), or source database providing sand and clay that sum to more than 100.
**Fix:** Always verify `sand + clay <= 100` and both are >= 0. Compute silt as `100 - sand - clay`. If sand + clay slightly exceeds 100 due to rounding, normalize: `sand = sand / (sand + clay) * 100` (assuming silt is negligible).

### PITFALL 2: Horizon Depths Mismatch Between RZWQM.dat and RZINIT.dat (FATAL)
**Severity:** Fatal -- the model will crash with an array bounds error.
**Symptom:** Fortran runtime error or segmentation fault.
**Cause:** RZWQM.dat declares N horizons but RZINIT.dat has data for a different number of horizons.
**Fix:** After modifying horizon depths in RZWQM.dat (S4), always update RZINIT.dat (S6) to match. Both files must specify exactly the same number of horizons.

### PITFALL 3: Using Default Hydraulic Properties Without Validation
**Severity:** Moderate -- water balance will be approximate.
**Cause:** The `soil_default_setter` lookup table provides textbook averages that may not represent site-specific conditions. For example, the default Ksat for "clay" is 0.06 cm/hr, but actual clay soils can range from 0.001 to 0.5 cm/hr depending on structure and macropores.
**Fix:** Use measured Ksat, field capacity, and wilting point whenever available. If using defaults, plan to calibrate Ksat and effective porosity first against observed water balance data (tile drainage, soil moisture, or water table depth).

### PITFALL 4: Silty Clay Loam Spelling Inconsistency
**Severity:** Operational bug.
**Cause:** In the source code `soil_default_setter`, the key for silty clay loam is `"silty clay loam "` (with a trailing space). Similarly, `default_microporosity_for_each_soil_type` uses `"silty clay loam "` with trailing space but `silt loam` is stored as `"silty loam"` and `"silt loam"` is stored as `"siltyloam"`.
**Fix:** When calling these functions, be aware of the exact string keys used:
- Use `"silty clay loam "` (trailing space) for silty clay loam hydraulic defaults
- Use `"siltyloam"` (no space) for silt loam hydraulic defaults
- For microporosity: `"silty clay loam "` (trailing space) and `"silty loam"` (with space)

### PITFALL 5: Not Calibrating in the Right Order
**Severity:** Wasted effort.
**Cause:** Attempting to calibrate crop parameters or nutrient parameters before the water balance is correct.
**Fix:** Always calibrate water balance first by adjusting soil hydraulic properties. The sensitivity order is: Ksat > effective porosity (ws - wr) > macroporosity > bubbling pressure > pore size distribution. Only after the water balance is satisfactory should you move to calibrating crop and nutrient parameters.

### PITFALL 6: Forgetting Lateral Ksat
**Severity:** Minor to moderate depending on drainage study.
**Cause:** Setting `lateral_ksat = 0` instead of a reasonable value. For tile-drained fields, lateral Ksat controls flow to drains.
**Fix:** Set lateral Ksat equal to or somewhat less than vertical Ksat as a starting point. Calibrate against observed tile drainage data.
