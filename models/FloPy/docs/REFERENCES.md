# FloPy — References

## Official Documentation

- **FloPy Documentation**: https://flopy.readthedocs.io/
- **FloPy GitHub Repository**: https://github.com/modflowpy/flopy
- **FloPy PyPI**: https://pypi.org/project/flopy/

## MODFLOW (USGS)

- **MODFLOW 6 Documentation**: https://www.usgs.gov/software/modflow-6-usgs-modular-hydrologic-model
- **MODFLOW 6 GitHub**: https://github.com/MODFLOW-USGS/modflow6
- **MODFLOW-2005**: https://www.usgs.gov/software/modflow-2005-usgs-three-dimensional-finite-difference-ground-water-model
- **MODFLOW-NWT**: https://www.usgs.gov/software/modflow-nwt-newton-formulation-modflow-2005
- **MODPATH 7**: https://www.usgs.gov/software/modpath-particle-tracking-model-modflow

## Key Papers

- Bakker, M., Post, V., Langevin, C.D., Hughes, J.D., White, J.T., Starn, J.J., and Fienen, M.N., 2016, Scripting MODFLOW model development using Python and FloPy: Groundwater, v. 54, p. 733–739, doi:10.1111/gwat.12413.
- Langevin, C.D., Hughes, J.D., Banta, E.R., Niswonger, R.G., Panday, S., and Provost, A.M., 2017, Documentation for the MODFLOW 6 Groundwater Flow Model: U.S. Geological Survey Techniques and Methods, book 6, chap. A55, 197 p., doi:10.3133/tm6A55.
- Harbaugh, A.W., 2005, MODFLOW-2005, The U.S. Geological Survey Modular Ground-Water Model: U.S. Geological Survey Techniques and Methods 6-A16.

## Related Tools

- **PEST/PEST++**: Parameter estimation and uncertainty analysis for MODFLOW — https://github.com/usgs/pestpp
- **MT3DMS**: Solute transport model — https://hydro.geo.ua.edu/mt3d/
- **SEAWAT**: Variable-density flow and transport — https://www.usgs.gov/software/seawat-a-computer-program-simulation-three-dimensional-variable-density-ground-water-flow

## Binary Installation

- **get-modflow utility** (included with FloPy): Downloads pre-compiled MODFLOW executables
  ```bash
  get-modflow :              # Install all to default location
  get-modflow /path/to/bin   # Install to specific directory
  ```
- **Executables source**: https://github.com/MODFLOW-USGS/executables
