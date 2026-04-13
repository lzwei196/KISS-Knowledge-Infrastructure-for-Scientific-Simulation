# COAWST References

## Source Code Repository
- **GitHub**: https://github.com/DOI-USGS/COAWST
- **Authors**: John C. Warner (USGS), Brandy Armstrong, Ruoying He, Jesse Maitland

## Official Documentation
- **COAWST Wiki**: https://github.com/DOI-USGS/COAWST/wiki
- **ROMS Wiki**: https://www.myroms.org/wiki/
- **ROMS Forum**: https://www.myroms.org/forum/
- **SWAN Documentation**: https://swanmodel.sourceforge.io/online_doc/swanuse/swanuse.html
- **WRF User Guide**: https://www2.mmm.ucar.edu/wrf/users/docs/user_guide_v4/

## Key Publications

### Primary COAWST Reference
- Warner, J.C., Armstrong, B., He, R., Zambon, J.B. (2010). Development of a Coupled Ocean-Atmosphere-Wave-Sediment Transport (COAWST) modeling system. *Ocean Modelling*, 35(3), 230–244. doi:10.1016/j.ocemod.2010.07.010

### ROMS
- Shchepetkin, A.F., McWilliams, J.C. (2005). The Regional Oceanic Modeling System (ROMS): a split-explicit, free-surface, topography-following-coordinate oceanic model. *Ocean Modelling*, 9(4), 347–404. doi:10.1016/j.ocemod.2004.08.002

### SWAN
- Booij, N., Ris, R.C., Holthuijsen, L.H. (1999). A third-generation wave model for coastal regions: 1. Model description and validation. *Journal of Geophysical Research*, 104(C4), 7649–7666. doi:10.1029/98JC02622

### WRF
- Skamarock, W.C., et al. (2019). A Description of the Advanced Research WRF Version 4. NCAR Technical Note NCAR/TN-556+STR.

### Coupling Framework (MCT)
- Larson, J., Jacob, R., Ong, E. (2005). The Model Coupling Toolkit: A New Fortran90 Toolkit for Building Multiphysics Parallel Coupled Models. *International Journal of High Performance Computing Applications*, 19(3), 277–292.

### Sediment Transport
- Warner, J.C., Sherwood, C.R., Signell, R.P., Harris, C.K., Arango, H.G. (2008). Development of a three-dimensional, regional, coupled wave, current, and sediment-transport model. *Computers & Geosciences*, 34(10), 1284–1306. doi:10.1016/j.cageo.2008.02.012

## Validation Cases
- **Hurricane Sandy (2012)**: Warner et al. (2017), Coupled storm surge and wave inundation modeling
- **Inlet Test**: Standard COAWST test case for wave-current interaction
- **Delilah morphodynamics**: Beach profile evolution test case

## Data Sources
| Data Type | Source | URL |
|-----------|--------|-----|
| Bathymetry | GEBCO | https://www.gebco.net/ |
| Atmospheric forcing | ERA5 | https://cds.climate.copernicus.eu/ |
| Ocean IC/BC | HYCOM | https://www.hycom.org/ |
| Tidal constituents | TPXO | https://www.tpxo.net/ |
| Observations | NOAA CO-OPS | https://tidesandcurrents.noaa.gov/ |
| Wave observations | NDBC | https://www.ndbc.noaa.gov/ |
