# Lake and Reservoir Routing

## Purpose
Configure mizuRoute to route flow through lakes and reservoirs using one of three available schemes. Required for basins with significant storage (reservoirs, natural lakes).

## Lake Routing Methods

| Method | ID | Description | Data needed |
|--------|---|-------------|-------------|
| Level-pool | 1 | Simple storage-discharge (H-A-V curves) | lake_area, lake_max_storage, H-A relationship |
| Hanasaki | 2 | Global reservoir scheme with demand-based release | lake capacity, mean annual inflow, demand |
| HYPE | 3 | Bucket-model lake routing | lake area, depth, rating curve parameters |

## Required Network Attributes for Lake Routing

Add these variables to the network topology NetCDF:

| Variable | Type | Units | Description |
|----------|------|-------|-------------|
| `is_lake` | int | 0/1 | Flag: is this reach a lake outlet? |
| `lake_id` | int | - | Unique lake identifier |
| `lake_area` | float | m2 | Lake surface area |
| `lake_max_storage` | float | m3 | Maximum storage volume |
| `lake_min_storage` | float | m3 | Minimum (dead) storage |
| `d_h_d_a` | float | m/m2 | Height-area derivative |

## Control File Settings for Lake Routing
```
<is_lake_sim>       .True.
<lake_model_type>   1        ! 1=level-pool, 2=Hanasaki, 3=HYPE
```

## Data Sources for Lake Parameters

| Database | Coverage | Lakes/Dams | Resolution |
|----------|----------|-----------|-----------|
| HydroLAKES v10 | Global | 1.4 million | Polygon |
| GRanD v1.3 | Global | 7,320 dams | Point + attributes |
| GOOD2 | Global | ~38,000 dams | Point + attributes |

None are pre-installed on HydroCraft server. Download HydroLAKES (~2.5 GB) for broad coverage.

## Common Pitfalls
- **Missing lake flags (dt_m011)**: If is_lake_sim=True but no lake variables in network, lake routing silently fails.
- **Lake at wrong segment**: The lake must be assigned to the correct outlet segment. If on a tributary instead of main stem, flow is disrupted.
