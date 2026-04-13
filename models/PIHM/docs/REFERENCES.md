# MM-PIHM References

## Source Code Repository
- **GitHub**: https://github.com/PSUmodeling/MM-PIHM
- **License**: MIT
- **Language**: C (with SUNDIALS CVODE v7.3.0 solver)

## Key Publications

### Core PIHM Model
- Qu, Y., & Duffy, C.J. (2007). A semidiscrete finite volume formulation for multiprocess watershed simulation. *Water Resources Research*, 43(8), W08419. https://doi.org/10.1029/2006WR005752

### MM-PIHM Framework
- Shi, Y., Davis, K.J., Duffy, C.J., & Yu, X. (2013). Development of a coupled land surface hydrologic model and evaluation at a critical zone observatory. *Journal of Hydrometeorology*, 14(5), 1401-1420. https://doi.org/10.1175/JHM-D-12-0145.1

### Flux-PIHM (Noah LSM coupling)
- Shi, Y., Davis, K.J., Zhang, F., Duffy, C.J., & Yu, X. (2014). Parameter estimation of a physically based land surface hydrologic model using the ensemble Kalman filter: A multivariate real-data experiment. *Advances in Water Resources*, 72, 119-130.

### PIHMgis (Preprocessing)
- Bhatt, G., Kumar, M., & Duffy, C.J. (2014). A tightly coupled GIS and distributed hydrologic modeling framework. *Environmental Modelling & Software*, 62, 70-84. https://doi.org/10.1016/j.envsoft.2014.08.023

## Solver Documentation
- **SUNDIALS CVODE**: https://computing.llnl.gov/projects/sundials/cvode
- Hindmarsh, A.C., et al. (2005). SUNDIALS: Suite of nonlinear and differential/algebraic equation solvers. *ACM Transactions on Mathematical Software*, 31(3), 363-396.

## Data Sources (Common Inputs)
- **ERA5 Reanalysis**: https://cds.climate.copernicus.eu/
- **NLDAS-2 Forcing**: https://ldas.gsfc.nasa.gov/nldas/v2/forcing
- **HWSD Soils**: https://www.fao.org/soils-portal/data-hub/soil-maps-and-databases/harmonized-world-soil-database-v12/
- **SSURGO Soils**: https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo

## Test Basins
- **Shale Hills** (bundled example): 40.66°N, 77.91°W, ~8 ha, State College, PA, USA
- **Bengbu** (KDT test): Huai River basin, China
- **Wangjiaba** (KDT test): Huai River basin, China
