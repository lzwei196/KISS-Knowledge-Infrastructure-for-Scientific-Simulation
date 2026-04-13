# openAMUNDSEN References

## Source Code
- **GitHub**: https://github.com/openamundsen/openamundsen
- **License**: MIT

## Documentation
- **Official docs**: https://openamundsen.readthedocs.io/
- **PyPI**: https://pypi.org/project/openamundsen/
- **conda-forge**: https://anaconda.org/conda-forge/openamundsen

## Key Publications
- Hanzer, F., Carmagnola, C.M., Ebner, P.P., Koch, F., Monti, F., Bavay, M., Bernhardt, M., Bettini, C., François, H., Lehning, M., Morin, S., Schöber, J., Strasser, U., and Terzago, S. (2022). Simulation of snow management and artificial snowmaking in Alpine ski resorts with the physically based snow model AMUNDSEN. *Cold Regions Science and Technology*, 201, 103596.
- Strasser, U. (2008). Modelling of the mountain snow cover in the Berchtesgaden National Park. *Forschungsbericht 55, Nationalparkverwaltung Berchtesgaden*.
- Strasser, U., Warscher, M., and Liston, G.E. (2011). Modeling snow-canopy processes on an idealized mountain. *Journal of Hydrometeorology*, 12(4), 663-677.
- Hanzer, F., Helfricht, K., Marke, T., and Strasser, U. (2016). Multilevel spatiotemporal validation of snow/ice mass balance and runoff modeling in glacierized catchments. *The Cryosphere*, 10(4), 1859-1881.

## Model Description
openAMUNDSEN is a fully distributed, physically based snow and hydroclimatological model for mountain regions. It operates on regular grids at 10-100 m spatial resolution and 1-3 hour temporal resolution. Key processes include:
- Spatial interpolation of meteorological observations
- Solar radiation including terrain effects
- Precipitation phase partitioning and wind correction
- Multi-layer or cryolayer snow energy/mass balance
- Forest canopy interception and sublimation
- Evapotranspiration (FAO Penman-Monteith)
- Soil heat conduction
- Glacier mass balance (experimental)

## Related Models
- **AMUNDSEN** (predecessor): Fortran-based, not open source
- **Alpine3D**: Similar purpose, different numerical approach
- **SNOWPACK**: Detailed 1D snow model (can couple with openAMUNDSEN)
