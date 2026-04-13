# Stage 3: Parameter Configuration

## Purpose

Create and configure the HAIL-CAESAR parameter file (.params) that controls all aspects of the model simulation: file paths, numerical settings, hydrology, erosion, and output.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| DEM properties | From Stage 1 | Resolution, extent, outlet slope |
| Rainfall properties | From Stage 2 | Timestep, spatial variability |
| Catchment knowledge | Literature/field | Manning's n, TOPMODEL m, soil properties |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parameter file | `.params` (plain text) | Key-value pairs with model configuration |

## Procedure

### Step 1: Copy template parameter file

Start from the Boscastle example or create a new file. The format is:
```
parameter_name:    value    # optional comment
```

### Step 2: Set file paths

```
read_fname:             my_catchment      # DEM name WITHOUT extension
dem_read_extension:     asc               # Only asc supported for input
dem_write_extension:    asc               # Output format: asc, flt, or bil
read_path:              ./input_data/     # Path to input files
write_path:             ./results/        # Path for output files
write_fname:            output.dat        # Timeseries output filename
timeseries_save_interval: 5              # Save interval in model minutes
```

### Step 3: Set numerical parameters

```
min_time_step:          0                 # Seconds (0 = auto)
max_time_step:          300               # Seconds (300 for 50m, lower for finer)
run_time_start:         0                 # Always 0 unless restart
max_run_duration:       71                # Hours (set to desired - 1!)
memory_limit:           1                 # Always 1
```

**Critical trap**: `max_run_duration` must be set to **T-1** hours. For a 72-hour simulation, set to 71. This is a known model quirk.

### Step 4: Configure hydrology

```
hydro_model_only:       yes               # yes = no erosion, no = full model
topmodel_m_value:       0.005             # 0.005 = flashy, 0.02 = slow
mannings_n:             0.04              # Roughness (0.03-0.06 channels)
courant_number:         0.3               # 0.3-0.7 (lower for finer DEMs)
froude_num_limit:       0.8               # Usually 0.8
hflow_threshold:        0.00001           # Min gradient for flow (metres)
slope_on_edge_cell:     0.005             # Approx channel slope at outlet
min_q_for_depth_calc:   0.03              # ~10% of cellsize for 50m DEM
max_q_for_depth_calc:   1000.0            # Upper threshold
water_depth_erosion_threshold: 0.01       # Metres
evaporation_rate:       0.0               # Not implemented
```

**Key relationships**:
- `courant_number`: 0.7 for 20-50m DEMs, 0.3 for <2m DEMs
- `min_q_for_depth_calc`: ~10% of cell size (0.5 for 50m, 0.01 for 5m)
- `topmodel_m_value`: Controls hydrograph shape (lower = flashier)

### Step 5: Configure precipitation

```
rainfall_data_on:       yes
rainfall_data_file:     rainfall.txt
rain_data_time_step:    60                # Minutes, MUST match file
spatial_var_rain:       no
num_unique_rain_cells:  1
```

### Step 6: Configure erosion (if not hydro-only)

```
hydro_model_only:       no                # Enable erosion
transport_law:          wilcock           # or einstein
max_tau_velocity:       5                 # m/s
active_layer_thickness: 0.1              # Metres (>= 4x erode_limit)
erode_limit:            0.02             # Max erosion per cell per step
chann_lateral_erosion:  20               # Prevents overdeepening
suspended_sediment_on:  yes
read_in_graindata_from_file: no
bedrock_layer_on:       no
```

### Step 7: Configure outputs

```
raster_output_interval: 120              # Minutes between raster saves
write_waterdepth_file:  yes
waterdepth_outfile_name: WaterDepths
write_elev_file:        yes
write_elevation_file:   Elevations
write_grainsize_file:   no
write_elevdiff_file:    no
```

### Step 8: Set hillslope parameters

```
creep_rate:             0.0025            # m/yr
slope_failure_thresh:   45                # degrees
vegetation_on:          no
```

## Verification

1. Cross-check all file paths exist
2. Verify `max_run_duration` is T-1 (not T)
3. Verify `rain_data_time_step` matches rainfall file timestep
4. Check `active_layer_thickness >= 4 * erode_limit`
5. Check `courant_number` is appropriate for DEM resolution
6. Ensure `write_path` directory exists (create if needed)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `max_run_duration` = T not T-1 | Simulation runs 1 hour short | Set to desired_hours - 1 |
| `read_fname` includes extension | "No DEM found" error | Remove `.asc` from name |
| `rain_data_time_step` mismatch | Rain applied at wrong rate | Must match actual file timestep exactly |
| `active_layer < 4 * erode_limit` | Numerical instability | Increase active_layer or decrease erode_limit |
| `courant_number` too high for fine DEM | Checkerboarding, instability | Use 0.3 for <2m DEMs |
| Missing `write_path` directory | No output files created | Create directory before running |
| Spaces in file paths | Parameter parsing fails | Use paths without spaces |

## Example

Minimal parameter file for Boscastle 50m hydro-only simulation:

```
read_fname:             boscastle_square_50m
dem_read_extension:     asc
dem_write_extension:    asc
read_path:              ./input_data/
write_path:             ./results/
write_fname:            output.dat
timeseries_save_interval: 5
rainfall_data_file:     boscastle_72hr_rain_u.txt
min_time_step:          0
max_time_step:          300
max_run_duration:       71
hydro_model_only:       yes
topmodel_m_value:       0.002
mannings_n:             0.04
courant_number:         0.3
froude_num_limit:       0.8
hflow_threshold:        0.00001
slope_on_edge_cell:     0.005
rainfall_data_on:       yes
rain_data_time_step:    5
spatial_var_rain:       no
num_unique_rain_cells:  1
raster_output_interval: 120
write_waterdepth_file:  yes
waterdepth_outfile_name: WaterDepths
write_elev_file:        yes
write_elevation_file:   Elevations
```
