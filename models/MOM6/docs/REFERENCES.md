# MOM6 References

## Source Code
- **GitHub Repository**: https://github.com/NOAA-GFDL/MOM6
- **FMS Framework**: https://github.com/NOAA-GFDL/FMS
- **MOM6-examples**: https://github.com/NOAA-GFDL/MOM6-examples

## Documentation
- **ReadTheDocs**: https://mom6.readthedocs.io
- **MOM6 API Docs**: https://mom6.readthedocs.io/en/main/api/
- **User Guide (GFDL)**: https://www.gfdl.noaa.gov/mom-ocean-model/

## Key Papers

Adcroft, A., et al. (2019). "The GFDL Global Ocean and Sea Ice Model OM4.0: Model
Description and Simulation Characteristics." *Journal of Advances in Modeling Earth
Systems*, 11(10), 3167-3211. doi:10.1029/2019MS001726

Hallberg, R. (2013). "Using a resolution function to regulate parameterizations of
oceanic mesoscale eddy effects." *Ocean Modelling*, 72, 92-103.
doi:10.1016/j.ocemod.2013.08.007

Griffies, S. M., & Hallberg, R. W. (2000). "Biharmonic friction with a
Smagorinsky-like viscosity for use in large-scale eddy-permitting ocean models."
*Monthly Weather Review*, 128(8), 2935-2946.

Large, W. G., McWilliams, J. C., & Doney, S. C. (1994). "Oceanic vertical mixing:
A review and a model with a nonlocal boundary layer parameterization." *Reviews of
Geophysics*, 32(4), 363-403. (KPP mixing scheme)

## Configuration References
- **TEOS-10**: http://www.teos-10.org/ — Thermodynamic Equation of Seawater 2010
- **WOA (World Ocean Atlas)**: https://www.ncei.noaa.gov/products/world-ocean-atlas — Climatology for initial conditions
- **GEBCO**: https://www.gebco.net/ — Global bathymetry dataset
- **ERA5**: https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5 — Atmospheric forcing reanalysis
- **JRA55-do**: https://climate.mri-jma.go.jp/pub/ocean/JRA55-do/ — Ocean forcing dataset

## Build and Infrastructure
- **Autoconf Build Guide**: https://github.com/NOAA-GFDL/MOM6/tree/main/ac
- **GFDL mkmf**: https://github.com/NOAA-GFDL/mkmf — Makefile generator
- **NUOPC/ESMF**: https://earthsystemmodeling.org/ — Coupling framework
