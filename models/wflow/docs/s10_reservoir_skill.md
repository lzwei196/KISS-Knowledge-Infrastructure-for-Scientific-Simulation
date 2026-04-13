# s10 -- Reservoir and Lake Module Skill Document

## Purpose

Enable reservoir routing in wflow_sbm simulations using GRanD (Global Reservoir and Dam) data. Reservoirs intercept river flow, apply operating rules, and release water downstream -- significantly altering flow timing, magnitude, and seasonal distribution.

## Prerequisites

- Working wflow_sbm setup (stages s0-s4 complete)
- staticmaps.nc with river network (wflow_river, wflow_ldd)
- GRanD Data KI installed at `data_ki/GRanD/`
- Optional: HydroLAKES Data KI for natural lakes

## When to Use Reservoirs

Enable reservoirs when:
- The basin contains large dams (check GRanD with `lookup_dams.py`)
- Flow regulation affects downstream hydrology significantly
- You are modeling flood control, water supply, or irrigation
- Observed discharge shows unnatural patterns (flat hydrographs, sudden releases)

Do NOT enable reservoirs when:
- No dams exist in the basin (wastes computation)
- You are modeling a pristine/natural watershed
- Dam capacity is negligible relative to annual flow volume

## Wflow.jl Reservoir Implementation

Wflow.jl supports four reservoir outflow types (from `src/routing/reservoir.jl`):

| Type | outflowfunc | Description | Required Data |
|------|-------------|-------------|---------------|
| Rating curve (H-Q) | 1 | Interpolation from H-Q table | `reservoir_hq_N.csv` files |
| Free weir | 2 | Q = b * (H - H0)^e | threshold, b, e |
| Modified Puls | 3 | Q = b * (H - H0)^2 | threshold, b, e, S-H curve |
| **Simple** | **4** | **Target-based release** | **maxstorage, demand, maxrelease, targetfull, targetmin** |

**Recommended approach**: Use **Simple (outflowfunc=4)** for GRanD-derived reservoirs because all parameters can be estimated from GRanD capacity and area data. The other types require rating curves or weir coefficients that are rarely available globally.

### Simple Reservoir Logic (outflowfunc=4)

The simple reservoir uses target-based operating rules:

1. **Environmental flow**: A sigmoid-scaled fraction of `demand` is released when storage is above `targetminfrac` of `maxstorage`
2. **Excess release**: Water above `targetfullfrac * maxstorage` is released up to `maxrelease`
3. **Overflow**: If storage exceeds `maxstorage`, excess is added to release
4. **Evaporation**: Subtracted from storage based on reservoir area and PET

### Storage function types

| Type | storfunc | Description |
|------|----------|-------------|
| Linear | 1 | S = A * H (constant area assumed) |
| Interpolation | 2 | S = f(H) from `reservoir_sh_N.csv` file |

Use **linear (storfunc=1)** when only surface area is known (GRanD default). Use interpolation (storfunc=2) when a measured S-H curve is available.

## Required TOML Configuration

### [model] section
```toml
reservoir__flag = true
```

### [input] section
```toml
reservoir_area__count = "wflow_reservoirareas"
reservoir_location__count = "wflow_reservoirlocs"
```

### [input.static] section (CSDMS standard names)
```toml
reservoir_surface__area = "reservoir_area"
reservoir_water_demand__required_downstream_volume_flow_rate = "ResDemand"
reservoir_water_release_below_spillway__max_volume_flow_rate = "ResMaxRelease"
reservoir_water__max_volume = "ResMaxVolume"
reservoir_water__target_full_volume_fraction = "ResTargetFullFrac"
reservoir_water__target_min_volume_fraction = "ResTargetMinFrac"
reservoir_water_surface__initial_elevation = "waterlevel_reservoir"
reservoir_water__rating_curve_type_count = "outflowfunc"
reservoir_water__storage_curve_type_count = "storfunc"
```

### [state.variables] section
```toml
reservoir_water_surface__elevation = "waterlevel_reservoir"
```

### [output] section
```toml
[output.netcdf_grid.variables]
reservoir_water__volume = "storage_reservoir"

[[output.csv.column]]
header = "reservoir_storage"
index = 1
parameter = "reservoir_water__volume"
```

## Required staticmaps.nc Variables

| Variable Name | Type | Unit | Description |
|--------------|------|------|-------------|
| wflow_reservoirlocs | int | - | Unique integer ID per reservoir (0 = no reservoir) |
| wflow_reservoirareas | int | - | Area mask matching reservoir IDs |
| reservoir_area | float | m^2 | Reservoir surface area |
| ResMaxVolume | float | m^3 | Maximum storage capacity |
| ResDemand | float | m^3/s | Required downstream environmental flow |
| ResMaxRelease | float | m^3/s | Maximum controllable release |
| ResTargetFullFrac | float | - | Target storage fraction (0-1) |
| ResTargetMinFrac | float | - | Minimum storage fraction (0-1) |
| waterlevel_reservoir | float | m | Initial water level |
| outflowfunc | int | - | 1=HQ, 2=weir, 3=Puls, 4=simple |
| storfunc | int | - | 1=linear, 2=interpolation |

**CRITICAL**: All spatial variables must have the same dimensions as the DEM (y, x). Reservoir parameters are only read at cells where `wflow_reservoirlocs > 0`.

## Pipeline

### Step 1: Find dams in basin
```bash
python tools/s10_reservoir/lookup_dams.py \
    --lat 32.95 --lon 117.38 --radius_km 200 \
    --min_capacity_mcm 100 \
    --json --output reservoir_params.json
```

### Step 2: Configure wflow for reservoirs
```bash
python tools/s10_reservoir/configure_reservoirs.py \
    --reservoir_json reservoir_params.json \
    --toml wflow_project/wflow_sbm.toml \
    --staticmaps wflow_project/staticmaps.nc
```

### Step 3: Run wflow with reservoirs
```bash
python tools/s4_execution/run_wflow.py \
    --toml wflow_project/wflow_sbm.toml
```

### Step 4: Analyze reservoir effects
Compare discharge with and without reservoirs. Expect:
- Reduced flood peaks
- Increased dry season baseflow
- Phase shift in peak timing

## Unit Conversion Reference (GRanD to wflow)

| GRanD field | GRanD unit | wflow parameter | wflow unit | Factor |
|------------|-----------|-----------------|-----------|--------|
| CAP_MCM | MCM (10^6 m^3) | maxstorage | m^3 | * 1e6 |
| area_ori | km^2 | area | m^2 | * 1e6 |
| DAM_HGT_M | m | (used for waterlevel init) | m | 1 |

**TRAP (dt_w031)**: GRanD capacity is in MCM (million cubic meters), NOT m^3. If you pass MCM values directly as m^3, storage will be 1e6 too small and the reservoir will overflow immediately.

## Parameter Estimation from GRanD

When GRanD provides only capacity (CAP_MCM) and area (area_ori):

| Parameter | Estimation Method | Typical Range |
|-----------|------------------|---------------|
| demand | 5% of capacity / year, as m^3/s | 0.01 - 100 m^3/s |
| maxrelease | From weir equation Q=1.7*L*H^1.5 or capacity/30days | 1 - 10000 m^3/s |
| targetfullfrac | Default 0.8 | 0.6 - 0.9 |
| targetminfrac | Default 0.2 | 0.1 - 0.3 |
| waterlevel_init | dam_height * targetfullfrac | 5 - 200 m |
| storfunc | 1 (linear) | 1 |
| outflowfunc | 4 (simple) | 4 |

**NOTE**: `demand` and `maxrelease` are rough estimates. Calibrate against observed outflow if available.

## Common Pitfalls

### dt_w031: MCM vs m^3 confusion
GRanD CAP_MCM is in million cubic meters. Passing MCM directly as m^3 makes storage 1e6 too small. The reservoir appears to overflow constantly, releasing all inflow. **Solution**: Always use `lookup_dams.py` which converts automatically.

### dt_w032: Reservoir not on river cell
If reservoir location falls on a non-river cell, wflow ignores it silently. The reservoir has no effect on discharge. **Solution**: `configure_reservoirs.py` snaps to nearest river cell, but verify placement.

### dt_w033: Reservoir area larger than grid cell
For coarse grids (0.25 deg), a single cell is ~625 km^2. Large reservoirs (>1000 km^2) may span multiple cells but are modeled as a point. This is physically reasonable for routing but underestimates evaporation from the reservoir surface. **Solution**: For very large reservoirs, consider finer resolution.

### Reservoir vs Lake
- **Reservoir**: Has operating rules (controlled outflow). Use `reservoir__flag`.
- **Lake**: Natural outflow based on rating curve. Use `lake__flag` (separate module, not covered here).
- In HydroLAKES, `Lake_type=2` means reservoir, `Lake_type=1` means natural lake.
- In HydroLAKES, `Grand_id > 0` means the lake is also in GRanD (it is a dam).

## Data KI Dependencies

| Data KI | What it provides | Used by |
|---------|-----------------|---------|
| GRanD | Dam locations, capacity, height, area | lookup_dams.py |
| HydroLAKES | Lake/reservoir morphometry, volume, depth | (future: natural lakes) |
| CMFD/MSWX | PET for reservoir evaporation | wflow forcing (existing) |
