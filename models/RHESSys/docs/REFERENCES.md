# RHESSys References

## Source Code

- **GitHub Repository**: https://github.com/RHESSys/RHESSys
- **Language**: C (501 source files)
- **Build**: GNU Make
- **Binary**: `rhessys7.4`

## Key Publications

- Tague, C.L. and Band, L.E. (2004). "RHESSys: Regional Hydro-Ecologic Simulation System — An object-oriented approach to spatially distributed modeling of carbon, water, and nutrient cycling." *Earth Interactions*, 8(19), 1-42.

- Band, L.E., Tague, C.L., Groffman, P., and Belt, K. (2001). "Forest ecosystem processes at the watershed scale: hydrological and ecological controls of nitrogen export." *Hydrological Processes*, 15(10), 2013-2028.

- Tague, C.L. and Band, L.E. (2001). "Simulating the impact of road construction and forest harvesting on hydrologic response." *Earth Surface Processes and Landforms*, 26(2), 135-151.

- Garcia, E.S. and Tague, C.L. (2015). "Subsurface storage capacity influences climate-evapotranspiration interactions in three western United States catchments." *Hydrology and Earth System Sciences*, 19(12), 4845-4858.

## Documentation

- **RHESSys Wiki**: https://github.com/RHESSys/RHESSys/wiki
- **RHESSys Preprocessing (RHESSysPreprocessing)**: https://github.com/RHESSys/RHESSysPreprocessing

## Scientific Context

RHESSys couples a quasi-distributed hydrological model (based on TOPMODEL concepts) with biogeochemical cycling routines derived from Biome-BGC. It simulates coupled water, carbon, and nitrogen cycling at the watershed scale.

### Core Components
- **Hydrology**: TOPMODEL-based lateral water redistribution, vertical drainage, snowpack energy balance
- **Biogeochemistry**: Biome-BGC derived carbon and nitrogen cycling
- **Vegetation**: Explicit growth, allocation, mortality, phenology dynamics
- **Fire**: Optional WMFire coupling for fire spread modeling

## Validation Sites

- HJ Andrews Watershed 8 (Oregon, USA) — primary test case included in repository
- Santa Ynez Mountains (California)
- Baltimore LTER urban watersheds

## Related Software

- **GRASS GIS**: Used for spatial preprocessing and terrain analysis
- **RHESSysPreprocessing R package**: Domain setup and worldfile creation
- **Biome-BGC**: Source of biogeochemical routines
- **TOPMODEL**: Conceptual basis for lateral flow redistribution
