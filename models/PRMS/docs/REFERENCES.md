# PRMS v5.1.0 — References

## Official Documentation

- **PRMS-IV User Manual**: Markstrom, S.L., Regan, R.S., Hay, L.E., Viger, R.J., Webb, R.M.T., Payn, R.A., and LaFontaine, J.H., 2015, PRMS-IV, the Precipitation-Runoff Modeling System, Version 4: U.S. Geological Survey Techniques and Methods, book 6, chap. B7, 158 p. https://doi.org/10.3133/tm6B7
- **PRMS v5 Release Notes**: Regan, R.S., Markstrom, S.L., Hay, L.E., Viger, R.J., Norton, P.A., Driscoll, J.M., and LaFontaine, J.H., 2018, Description of the National Hydrologic Model Infrastructure (NHM) including updates to PRMS-IV: U.S. Geological Survey Techniques and Methods, book 6, chap. B9, 38 p. https://doi.org/10.3133/tm6B9

## Source Code

- **GitHub Repository**: https://github.com/nhm-usgs/prms
- **Version used**: 5.1.0 (05/01/2020)
- **Build**: Linux x86-64, gfortran + gcc

## Key Papers

- Leavesley, G.H., Lichty, R.W., Troutman, B.M., and Saindon, L.G., 1983, Precipitation-Runoff Modeling System: User's Manual: U.S. Geological Survey Water-Resources Investigations Report 83-4238, 207 p.
- Markstrom, S.L., Niswonger, R.G., Regan, R.S., Prudic, D.E., and Barlow, P.M., 2008, GSFLOW—Coupled Ground-Water and Surface-Water Flow Model Based on the Integration of PRMS and MODFLOW-2005: U.S. Geological Survey Techniques and Methods 6-D1.
- Hay, L.E., Leavesley, G.H., Clark, M.P., Markstrom, S.L., Viger, R.J., and Umemoto, M., 2006, Step-wise, multiple-objective calibration of a hydrologic model for a snowmelt-dominated basin: Journal of the American Water Resources Association, v. 42, no. 4, p. 877-890.

## Related Software

- **NHM (National Hydrologic Model)**: Framework that uses PRMS as the core rainfall-runoff model for CONUS. https://www.usgs.gov/mission-areas/water-resources/science/national-hydrologic-model-infrastructure
- **GSFLOW**: Coupled PRMS + MODFLOW for integrated surface/groundwater modeling.
- **pyPRMS**: Python tools for PRMS parameter manipulation. https://github.com/nhm-usgs/pyPRMS

## Data Sources Used in KI Tools

- **CMFD**: China Meteorological Forcing Dataset (temperature, precipitation)
- **ERA5**: ECMWF Reanalysis v5 (global climate reanalysis)
- **HWSD/SOILGRIDS**: Soil property databases for parameter estimation
- **SRTM/MERIT DEM**: Digital elevation models for HRU delineation
