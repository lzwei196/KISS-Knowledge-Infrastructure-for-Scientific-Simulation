# Noah-MP References

## Source Code Repository

- **Noah-MP v5.x**: https://github.com/NCAR/noahmp
- **HRLDAS driver**: https://github.com/NCAR/hrldas (or bundled in noahmp/drivers/hrldas/)
- **WRF-Hydro/NWM** (uses Noah-MP as LSM): https://github.com/NCAR/wrf_hydro_nwm_public
- **License**: See LICENSE.txt in repository

## Key Publications

1. **Niu, G.-Y., et al. (2011)**. "The community Noah land surface model with multiparameterization options (Noah-MP): 1. Model description and evaluation with local-scale measurements." *Journal of Geophysical Research: Atmospheres*, 116, D12109. doi:10.1029/2010JD015139

2. **Yang, Z.-L., et al. (2011)**. "The community Noah land surface model with multiparameterization options (Noah-MP): 2. Evaluation over global river basins." *Journal of Geophysical Research: Atmospheres*, 116, D12110. doi:10.1029/2010JD015140

3. **He, C., et al. (2023)**. "The Community Noah-MP Land Surface Modeling System Technical Description Version 5.0." *NCAR Technical Note* NCAR/TN-575+STR. doi:10.5065/ew8g-yr95

4. **Chen, F. and Dudhia, J. (2001)**. "Coupling an Advanced Land Surface–Hydrology Model with the Penn State–NCAR MM5 Modeling System. Part I: Model Implementation and Sensitivity." *Monthly Weather Review*, 129, 569-585.

## HRLDAS Documentation

- HRLDAS User Guide: bundled in source repository under `docs/`
- NCAR Research Applications Lab: https://ral.ucar.edu/solutions/products/noah-multiparameterization-land-surface-model-noah-mp

## Noah-MP Physics Documentation

- Vegetation dynamics and phenology: Dickinson et al. (1998), Niu & Yang (2004)
- Snow physics (3-layer): Jordan (1991), Anderson (1976)
- Runoff schemes: TOPMODEL (Niu et al., 2005), VIC (Liang et al., 1994), Xinanjiang (Zhao, 1992)
- Stomatal conductance: Ball-Berry (Ball et al., 1987), Jarvis (Jarvis, 1976)
- Photosynthesis: Farquhar et al. (1980), Collatz et al. (1991, 1992)

## Forcing Data Sources

- **CMFD**: China Meteorological Forcing Dataset — http://data.tpdc.ac.cn (0.1°, 3-hourly, 1979–2018)
- **ERA5**: ECMWF Reanalysis v5 — https://cds.climate.copernicus.eu (0.25°, hourly, 1940–present)
- **MSWX**: Multi-Source Weather — https://www.gloh2o.org/mswx/ (0.1°, 3-hourly, 1979–present)

## Soil Data Sources

- **HWSD**: Harmonized World Soil Database v1.2 — https://www.fao.org/soils-portal/data-hub/
- **SoilGrids**: ISRIC SoilGrids 250m — https://soilgrids.org

## Related HydroCraft Models

- WRF-Hydro: Routing model that uses Noah-MP runoff as input
- CaMa-Flood: Global river routing that accepts Noah-MP SFCRNOFF + UGDRNOFF
