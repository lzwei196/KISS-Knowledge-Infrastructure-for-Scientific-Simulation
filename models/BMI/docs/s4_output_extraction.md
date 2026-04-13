# S4: Output Extraction

## Purpose

Extract model state variables from a running BMI model instance using getter functions and write results to CSV or NetCDF format. This stage handles the data conversion from BMI's flattened 1D arrays to structured output files.

## Inputs

| Input            | Type     | Description                                     |
|------------------|----------|-------------------------------------------------|
| BMI instance     | object   | Initialized BMI model (after `initialize()`)    |
| Variable names   | [string] | Names to extract (default: all output vars)     |
| Output format    | string   | `csv` or `netcdf`                                |
| Output path      | string   | File path for output                             |

## Outputs

| Output        | Format      | Description                                  |
|---------------|-------------|----------------------------------------------|
| Data file     | CSV/NetCDF  | Extracted variable values with metadata      |

## Procedure

1. **Discover variables**: If no names specified, query `get_output_var_names()`
2. **Collect metadata**: For each variable, query:
   - `get_var_units()` → unit string
   - `get_var_type()` → data type
   - `get_var_nbytes()` / `get_var_itemsize()` → array size
   - `get_var_grid()` → grid identifier
   - `get_grid_type()` → grid type
   - `get_grid_size()` → total nodes
   - `get_grid_rank()` → dimensions
3. **Extract values**: Call `get_value(name, dest)` with correctly sized dest array
4. **Reshape if possible**: Use `get_grid_shape()` to recover 2D/3D structure
5. **Write output**: CSV (with summary stats) or NetCDF (with dimensions)
6. **Validate**: Check output file exists and is non-empty

```bash
# Example: extract temperature after 100 steps
python output_extractor.py heat BmiHeat heat.yaml --vars plate_surface__temperature --steps 100 -o temp.csv
```

## Verification

- [ ] All requested variables extracted successfully
- [ ] Array sizes match `get_var_nbytes() / get_var_itemsize()`
- [ ] Values are within physically reasonable ranges
- [ ] Units labels are correct (UDUNITS convention)
- [ ] CSV/NetCDF file is valid and non-empty

## Array Convention

BMI always returns **flattened 1D arrays**, regardless of the model's internal grid dimensionality. The developer must reshape based on grid info:

```python
# Extract flat array
grid_id = bmi.get_var_grid("temperature")
grid_size = bmi.get_grid_size(grid_id)
flat = np.empty(grid_size, dtype=float)
bmi.get_value("temperature", flat)

# Reshape using grid shape (ij-order)
rank = bmi.get_grid_rank(grid_id)
shape = np.empty(rank, dtype=int)
bmi.get_grid_shape(grid_id, shape)
grid_2d = flat.reshape(shape)  # shape = [ny, nx]
```

## UDUNITS Convention

BMI uses UDUNITS for variable units. Key rules:
- Compound units: separated by spaces, e.g., `"m s-1"` (velocity)
- Exponents: immediately after unit, e.g., `"km2"` (area), `"W m-2"` (flux)
- Dimensionless: `""` or `"1"` (NOT `"none"`)
- No units concept: `"none"` (e.g., model that doesn't track time)

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| **Wrong dest size** | `np.empty(wrong_size)` passed to `get_value` | Buffer error or silent corruption | Use `nbytes // itemsize` |
| **Wrong dtype** | Using `float32` when model stores `float64` | Precision loss or type error | Check `get_var_type()` first |
| **Scalar on grid** | Extracting a scalar (grid_size=1) as array | Works but wasteful | Check `get_grid_type()` == "scalar" |
| **ij reshape** | Reshaping as [nx, ny] instead of [ny, nx] | Transposed grid | BMI shape is always [ny, nx] |
| **get_value_ptr mutation** | Modifying array from `get_value_ptr` | Changes model state silently | Use `get_value` (copy) for safe reads |

## Example

```python
# CSV output structure for a 10x20 temperature grid
# BMI Output Extraction at t=25.0 s
#
# Variable: plate_surface__temperature [K]
# statistic,value
# variable,plate_surface__temperature
# units,K
# count,200
# mean,1.234
# std,0.567
# min,0.0
# max,5.678
# shape,(10, 20)
# Full data (200 values, flattened):
# index,plate_surface__temperature
# 0,0.0
# 1,0.0123
# ...
```
