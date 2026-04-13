# Stage 1: River Network Topology Construction

## Purpose
Build the river network topology NetCDF that defines every reach and its contributing catchment (HRU). This is the core spatial input for mizuRoute.

If skipped: mizuRoute has no river network to route through.

## Prerequisites
- [ ] Basin shapefile exists
- [ ] DEM available (China 90m or Copernicus GLO-30)
- [ ] WhiteboxTools installed (in HydroCraft python_env)

## Procedure

1. **Run build_network_topology.py**:
   ```bash
   python tools/s1_network/build_network_topology.py \
     --basin_shp <shapefile> --dem <dem_path> \
     --output network_topology.nc \
     --stream_threshold 500 --min_slope 0.0001
   ```

2. **Stream threshold selection guide**:
   | Basin area | Recommended threshold | Approx. reaches |
   |-----------|----------------------|-----------------|
   | < 1,000 km2 | 100-300 | 20-100 |
   | 1,000-10,000 km2 | 300-1000 | 50-500 |
   | 10,000-100,000 km2 | 1000-5000 | 200-2000 |
   | > 100,000 km2 | 5000-20000 | 1000-10000 |

   Higher threshold = fewer, longer reaches = faster routing.

3. **Validate topology**:
   - Exactly one outlet (tosegment=0)
   - All tosegment references exist in seg_id
   - All seg_slope > min_slope
   - All seg_length > 0

## Common Pitfalls
- **Multiple outlets (dt_m015)**: DEM extraction near basin boundary creates extra outlets. Fix by connecting secondary outlets to main outlet.
- **Zero slope (dt_m007)**: Flat terrain gives slope=0. Apply minimum 0.0001 m/m.
- **Wrong width estimation (dt_m018)**: Default Leopold coefficients are for temperate. Adjust for climate zone.
- **Too many reaches**: Very low threshold creates thousands of reaches, slowing routing. Start with threshold=500 and adjust.
