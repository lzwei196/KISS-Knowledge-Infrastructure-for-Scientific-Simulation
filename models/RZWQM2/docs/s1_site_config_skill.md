# Skill Document: Site/Grid Configuration (S1)

**Stage:** s1_site_config
**Pipeline Order:** 1
**Depends On:** None
**Tool:** `write_site_properties`

---

## Purpose

Configure the geographic and site-specific properties for an RZWQM2 simulation grid. These properties define the physical location and characteristics of the field being modeled, and are written to the `grid_general_property` section of `RZWQM.dat`. The model uses these values to compute solar radiation geometry, potential evapotranspiration, atmospheric pressure corrections, and rainfall distribution. Incorrect site configuration -- particularly latitude and longitude -- will produce silently wrong PET estimates and radiation calculations, making this a critical first step.

---

## Prerequisites

1. A scenario directory exists containing a template `RZWQM.dat` file.
2. The geographic coordinates (latitude, longitude) of the study site are known.
3. Site elevation (meters above sea level) is known.
4. An estimate of average field slope is available.
5. Python environment with access to `rzwqm_file.py` (specifically the `RZWQM` class and `grid_general_property` class).

---

## Inputs

| Parameter | Type | Unit | Description | Example |
|-----------|------|------|-------------|---------|
| `project_path` | string (directory) | -- | Root directory of the RZWQM2 project | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | -- | Scenario/station identifier (used as subdirectory name) | `534` |
| `lat` | float | **radians** | Latitude of the site center. MUST be in radians. | `0.8727` (for 50 degrees N) |
| `lon` | float | **radians** | Longitude of the site center. MUST be in radians. | `-1.7104` (for -98 degrees W) |
| `elevation` | float | meters | Elevation above sea level | `300.0` |
| `slope` | float | fraction | Average field slope (0.0 = flat, 1.0 = 45 degrees) | `0.02` |
| `area` | float | m^2 | Area of the simulation grid cell | `10000.0` |
| `aspect` | float | degrees | Aspect measured clockwise from north | `0.0` |
| `ambient_co2` | float | ppm | Ambient CO2 concentration | `400.0` |
| `rainfall_zone` | int | -- | Rainfall zone identifier (typically 1) | `1` |

---

## Procedure

### Step 1: Convert Latitude and Longitude from Degrees to Radians

RZWQM2 internally expects latitude and longitude in **radians**, not degrees. If your coordinates are in degrees (as is typical from GPS, weather stations, or geographic databases), convert them:

```
lat_radians = lat_degrees * (pi / 180)
lon_radians = lon_degrees * (pi / 180)
```

**Example:** For a site at 50.0 degrees N, -98.0 degrees W:
```python
import math
lat_rad = 50.0 * math.pi / 180.0   # = 0.8727
lon_rad = -98.0 * math.pi / 180.0  # = -1.7104
```

### Step 2: Construct the Grid General Property Object

Create a `grid_general_property` instance with all 8 parameters:

```python
from rzwqm_file import grid_general_property

site_props = grid_general_property(
    area=10000.0,
    elevation=300.0,
    aspect_measured_clockwise=0.0,
    center_lat=0.8727,       # radians
    center_lon=-1.7104,      # radians
    slope=0.02,
    rainfall_zone=1,
    ambient_co2=400.0
)
```

### Step 3: Write to RZWQM.dat

Use the `RZWQM` class to locate the `grid_general_property` section in `RZWQM.dat` and overwrite it:

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)
rz.write_soil_general_properties_to_dat(site_props)
```

The write function locates the section using the identifier `'=     8      ambient co2 [ppm]'` as the head marker and `'==         SOIL PROPERTIES AND PARAMETERS                             =='` as the end marker. It writes a single data line with 8 space-separated values in this order:

```
area  elevation  aspect  lat  slope  lon  rainfall_zone  ambient_co2
```

Note the non-intuitive ordering: latitude is position 4 (not 3), and longitude is position 6 (not 4). The `grid_general_property` class and `write_soil_general_properties_to_dat` method handle this ordering automatically.

### Step 4: Verify the Written Values

Re-read the RZWQM.dat file and confirm the grid general property line contains the expected values:

```python
rz2 = RZWQM(project_path, station_id)
props = rz2.return_soil_general_properties()
assert float(props.center_lat) != 0.0, "Latitude was not written"
assert float(props.center_lon) != 0.0, "Longitude was not written"
```

---

## Expected Outputs

- **Modified file:** `{project_path}/{station_id}/RZWQM.dat`
- **Changed section:** The single data line in the `grid_general_property` section (between the head/end identifiers) contains the 8 updated values.
- **No other sections of RZWQM.dat are modified.**

---

## Validation Checks

1. **Latitude range:** For locations in the Northern Hemisphere, `lat` should be between 0 and pi/2 (0 to 1.5708 radians). Southern Hemisphere: 0 to -pi/2.
2. **Longitude range:** For locations in the Western Hemisphere, `lon` should be negative (0 to -pi radians). Eastern Hemisphere: 0 to pi.
3. **Non-zero check:** Both `lat` and `lon` must be non-zero. A value of 0.0 for both indicates the site is at the intersection of the prime meridian and equator (Gulf of Guinea), which is almost certainly an error.
4. **Elevation reasonableness:** Should be between -500 and 9000 meters.
5. **Slope range:** Must be between 0.0 and 1.0 (fraction). Values greater than 0.5 are unusual for agricultural fields.
6. **Ambient CO2:** Typical present-day value is 400-425 ppm. Values below 200 or above 1000 are likely errors unless modeling specific scenarios.
7. **File integrity:** After writing, confirm the RZWQM.dat file still has the correct number of lines (writing should not add or remove lines, only modify one line in place).

---

## Common Pitfalls

### PITFALL 1: Latitude and Longitude in Degrees Instead of Radians (SILENT ERROR)
**Severity:** Silent -- the model will run without crashing but produce incorrect results.
**Symptom:** PET calculations are wrong, leading to incorrect water balance. Snow and radiation calculations are also affected.
**Cause:** Passing latitude as 50.0 (degrees) instead of 0.8727 (radians).
**Detection:** If `abs(lat) > pi/2` (1.5708), the value is almost certainly in degrees.
**Fix:** Always multiply degrees by `pi / 180` before passing to the tool:
```python
lat_rad = lat_deg * 3.14159265 / 180.0
```

### PITFALL 2: Confusing the Column Order
**Severity:** Silent error.
**Cause:** The grid general property line has a non-intuitive column order: `area elevation aspect lat slope lon rainfall_zone ambient_co2`. Latitude is column 4 and longitude is column 6, with slope between them at column 5.
**Fix:** Always use the `grid_general_property` class and `write_soil_general_properties_to_dat` method, which handle the column ordering internally.

### PITFALL 3: Not Verifying After Write
**Severity:** Operational risk.
**Cause:** The file write may silently fail if the RZWQM.dat section identifiers have changed or if the file is read-only.
**Fix:** Always re-read the file after writing and verify the values match expectations.
