# Stage 2: Spatial Remapping (VIC Grid -> mizuRoute HRUs)

## Purpose
Create area-weighted spatial mapping from VIC regular grid cells to mizuRoute HRU catchments. Each VIC cell's runoff is distributed proportionally to the HRUs it overlaps.

If skipped: mizuRoute cannot distribute gridded runoff to its river network.

## Prerequisites
- [ ] VIC grid definition (basin_grid.nc)
- [ ] Network topology NetCDF with HRU definitions

## Procedure
```bash
python tools/s2_remap/create_remap_weights.py \
  --grid_nc <grid_nc> --network_nc <network_nc> \
  --output remap_weights.nc
```

## Key Validation
- Weight sum per HRU should be approximately 1.0 (all runoff accounted for)
- Every HRU should have at least one weight > 0
- No HRU should have weight sum > 1.1 (overlap miscalculation)

## Common Pitfalls
- **CRS mismatch (dt_m005)**: VIC grid (WGS84) vs HRU polygons (UTM). Both must be EPSG:4326.
- **Edge HRUs without coverage (dt_m010)**: At coarse VIC resolution, small edge HRUs may fall between grid cells. Use finer VIC resolution (0.1 deg) or nearest-neighbor assignment.
