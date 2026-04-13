# ELMFIRE References

## Primary Citation

Lautenberger, C. (2013). Wildland fire modeling with an Eulerian level set method and automated calibration. *Fire Safety Journal*, 62, 289-298. https://doi.org/10.1016/j.firesaf.2013.08.014

## Source Code

- **Repository**: https://github.com/lautenberger/elmfire
- **Language**: Fortran 90/95 with MPI parallelism
- **License**: See repository for current license terms
- **Build**: `build/linux/make_gnu.sh` (requires gfortran >= 9, libopenmpi-dev)

## Key Papers

- Lautenberger, C. (2017). Mapping areas at risk from wildfires using an Eulerian level set model. In *Proceedings of the 12th International Symposium on Fire Safety Science*.
- Rothermel, R.C. (1972). A mathematical model for predicting fire spread in wildland fuels. USDA Forest Service Research Paper INT-115.
- Scott, J.H. & Burgan, R.E. (2005). Standard fire behavior fuel models: a comprehensive set for use with Rothermel's surface fire spread model. USDA Forest Service General Technical Report RMRS-GTR-153.
- Van Wagner, C.E. (1977). Conditions for the start and spread of crown fire. *Canadian Journal of Forest Research*, 7(1), 23-34.
- Cruz, M.G. & Alexander, M.E. (2013). Uncertainty associated with model predictions of surface and crown fire rates of spread. *Environmental Modelling & Software*, 47, 16-28.

## Fuel Model Reference

- Anderson, H.E. (1982). Aids to determining fuel models for estimating fire behavior. USDA Forest Service General Technical Report INT-122.
- Scott, J.H. & Burgan, R.E. (2005). FBFM40 fuel model set. RMRS-GTR-153.

## Data Sources

- **LANDFIRE**: https://landfire.gov — Fuel, topography, canopy data for CONUS
- **HRRR**: High-Resolution Rapid Refresh weather model — real-time meteorological forcing
- **RAWS**: Remote Automated Weather Stations — point weather observations

## Related Tools

- **CloudFire**: Cloud-based interface for ELMFIRE (developed by Reax Engineering)
- **FARSITE**: Alternative Lagrangian fire spread model (perimeter-tracking approach)
- **FlamMap**: Static fire behavior mapping tool using same Rothermel fuel models
