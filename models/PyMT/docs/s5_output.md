# Stage 5: Output and Data Export

## Purpose

Write model output variables to persistent storage (NetCDF files, CSV, or
xarray Datasets). PyMT provides built-in NetCDF writers that support
CF-compliant metadata, UGRID format for unstructured grids, and time-series
databases for multi-timestep output.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Running/completed model | object | Yes | Model with data to export |
| Variable names | list of str | Yes | Which variables to write |
| Output path | str | Yes | File path for output |
| Output format | str | No | "netcdf", "csv", or "xarray" |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| NetCDF file | .nc file | CF/UGRID compliant output |
| CSV file | .csv file | Tabular time series |
| xarray Dataset | object | In-memory labeled data |

## Procedure

### Step 1: Direct Array Export to CSV
```python
import csv
import numpy as np

with open("output.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["time", "var_mean", "var_min", "var_max"])

    while model.time < model.end_time:
        model.update()
        val = model.get_value("variable_name")
        writer.writerow([
            model.time,
            float(np.mean(val)),
            float(np.min(val)),
            float(np.max(val)),
        ])
```

### Step 2: NetCDF Output via PortPrinter
```python
from pymt.portprinter.port_printer import NcPortPrinter

# Create printer for a specific variable
printer = NcPortPrinter(model, "sea_surface_water_wave__height")
printer.open()

for step in range(100):
    model.update()
    printer.write()  # writes current timestep to NetCDF

printer.close()
```

### Step 3: UGRID Output for Unstructured Grids
```python
from pymt.framework.bmi_ugrid import dataset_from_bmi_grid

# Get grid as xarray Dataset (UGRID format)
grid_id = model.var_grid("variable_name")
ds = dataset_from_bmi_grid(model.bmi, grid_id)

# Add variable data
val = model.get_value("variable_name")
ds["variable_name"] = (("n_node",), val)

# Save
ds.to_netcdf("output_ugrid.nc")
```

### Step 4: xarray Dataset Export
```python
import xarray as xr
import numpy as np

# Collect time series
times = []
data = []
while model.time < model.end_time:
    model.update()
    times.append(model.time)
    data.append(model.get_value("var_name").copy())

# Create xarray Dataset
ds = xr.Dataset({
    "var_name": (["time", "node"], np.array(data)),
}, coords={"time": times})

ds.to_netcdf("output.nc")
```

### Step 5: Read Back NetCDF Output
```python
import xarray as xr

ds = xr.open_dataset("output.nc")
print(ds)
print(ds["var_name"].values)
```

## Verification

```python
import os
import xarray as xr

assert os.path.exists("output.nc"), "NetCDF file not created"
ds = xr.open_dataset("output.nc")
assert len(ds.data_vars) > 0, "No variables in output"
assert "time" in ds.dims or "time" in ds.coords, "No time dimension"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Flat arrays in NetCDF** | Variables have wrong shape | Reshape using `grid_shape()` before writing |
| Missing time coordinate | NetCDF has no time axis | Add time explicitly when building Dataset |
| UGRID not recognized | NetCDF readers can't parse grid | Use `xarray` or `netCDF4` with UGRID conventions |
| File locked | Cannot overwrite existing output | Close previous dataset/printer first |
| Large files | Disk full or slow I/O | Use chunked writing, compress with `encoding={"var": {"zlib": True}}` |
| Unit metadata missing | Downstream tools misinterpret values | Set `ds["var"].attrs["units"] = model.var_units("var")` |

## Example

```python
from pymt.models import Waves
import numpy as np
import csv

model = Waves()
model.initialize(*model.setup())

# Export to CSV
with open("wave_output.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["time", "wave_height_mean"])

    try:
        for _ in range(50):
            model.update()
            wh = model.get_value("sea_surface_water_wave__height")
            writer.writerow([model.time, float(np.mean(wh))])
    finally:
        model.finalize()

print("Output written to wave_output.csv")
```
