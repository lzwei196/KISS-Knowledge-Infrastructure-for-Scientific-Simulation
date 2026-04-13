# Delft3D — References

## Official Documentation

- **Deltares Delft3D Open Source**: https://oss.deltares.nl/web/delft3d
- **D-Flow FM User Manual** (Deltares): https://content.oss.deltares.nl/delft3d/manuals/D-Flow_FM_User_Manual.pdf
- **Delft3D-FLOW User Manual**: https://content.oss.deltares.nl/delft3d/manuals/Delft3D-FLOW_User_Manual.pdf
- **DIMR Technical Reference**: https://content.oss.deltares.nl/delft3d/manuals/DIMR_Technical_Reference_Manual.pdf
- **D-Water Quality User Manual**: https://content.oss.deltares.nl/delft3d/manuals/D-Water_Quality_User_Manual.pdf

## Source Code

- **GitHub Repository**: https://github.com/Deltares/Delft3D
- **License**: LGPL v3+ (open source since 2014)
- **Build Documentation**: `doc/delft3d.Dockerfile` and `doc/third-party-libs.Dockerfile` in repository

## Python Packages (Pre/Post-Processing)

- **dfm_tools** (Deltares): https://pypi.org/project/dfm-tools/ — D-Flow FM pre/post-processing
- **hydrolib-core** (Deltares): https://pypi.org/project/hydrolib-core/ — Model configuration file I/O
- **meshkernel** (Deltares): https://pypi.org/project/meshkernel/ — Mesh/grid generation

## Key Publications

- Kernkamp, H.W.J., Van Dam, A., Stelling, G.S., de Goede, E.D. (2011). "Efficient scheme for the shallow water equations on unstructured grids with application to the Continental Shelf." *Ocean Dynamics*, 61(8), 1175-1188. doi:10.1007/s10236-011-0423-6
- Deltares (2024). "Delft3D-FLOW: Simulation of multi-dimensional hydrodynamic flows and transport phenomena, including sediments." Deltares Technical Documentation.
- Lesser, G.R., Roelvink, J.A., van Kester, J.A.T.M., Stelling, G.S. (2004). "Development and validation of a three-dimensional morphological model." *Coastal Engineering*, 51(8-9), 883-915. doi:10.1016/j.coastaleng.2004.07.014
- Roelvink, J.A. (2006). "Coastal morphodynamic evolution techniques." *Coastal Engineering*, 53(2-3), 277-287.

## Validation Data Sources Used

- **NOAA Tides & Currents**: https://tidesandcurrents.noaa.gov/ — Hourly water level observations
- **NDBC (National Data Buoy Center)**: https://www.ndbc.noaa.gov/ — Wave and meteorological buoy data
- **GEBCO Bathymetry**: https://www.gebco.net/ — Global gridded bathymetry
- **ERA5 Reanalysis**: https://cds.climate.copernicus.eu/ — Meteorological forcing

## Related KI Models

- **CaMa-Flood**: Provides upstream river discharge as boundary inflow
- **VIC**: Meteorological forcing with unit conversions
- **GLM**: 1D lake model (different spatial paradigm)
- **SWAT**: Lumped basin hydrology (different spatial paradigm)
