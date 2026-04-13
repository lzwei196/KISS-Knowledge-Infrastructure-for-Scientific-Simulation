# GEOtop References

## Source Code
- **Repository**: https://github.com/geotopmodel/geotop
- **Version**: 3.0 (C++11 rewrite)
- **License**: GPLv3
- **Build**: CMake 3.0+, no external dependencies required

## Key Publications

1. Endrizzi, S., Gruber, S., Dall'Amico, M., and Rigon, R. (2014).
   GEOtop 2.0: simulating the combined energy and water balance at and below the land surface
   accounting for soil freezing, snow cover and terrain effects.
   *Geoscientific Model Development*, 7, 2831–2857.
   https://doi.org/10.5194/gmd-7-2831-2014

2. Rigon, R., Bertoldi, G., and Over, T.M. (2006).
   GEOtop: A distributed hydrological model with coupled water and energy budgets.
   *Journal of Hydrometeorology*, 7(3), 371–388.
   https://doi.org/10.1175/JHM497.1

3. Dall'Amico, M., Endrizzi, S., Gruber, S., and Rigon, R. (2011).
   A robust and energy-conserving model of freezing variably-saturated soil.
   *The Cryosphere*, 5, 469–484.
   https://doi.org/10.5194/tc-5-469-2011

4. Bertoldi, G., Notarnicola, C., Leitinger, G., Endrizzi, S., Zebisch, M.,
   Della Chiesa, S., and Tappeiner, U. (2010).
   Topographical and ecohydrological controls on land surface temperature in an alpine catchment.
   *Ecohydrology*, 3(2), 189–204.
   https://doi.org/10.1002/eco.129

## Documentation
- **User manual**: Bundled with source at `doc/` in repository
- **Keywords reference**: `src/geotop/keywords.h` (455+ configuration keywords)
- **Test cases**: `tests/` directory in repository (Matsch B2 reference test)

## Related Projects
- **MeteoIO**: Meteorological data interpolation library (optional dependency)
  https://gitlabext.wsl.ch/snow-models/meteoio
- **SNOWPACK**: Detailed snow model that can couple with GEOtop
  https://gitlabext.wsl.ch/snow-models/snowpack

## Data Sources Used in KI Tools
| Source | Variables | Tool |
|--------|-----------|------|
| CMFD/MSWX/ERA5 | AirT, Precip, Wind, RH, SW, LW | `convert_forcing.py` |
| HWSD/SoilGrids | Sand, Silt, Clay, Ksat, BD, OC | `convert_soil.py` |
| SRTM/MERIT | DEM elevation grid | External GIS |
| MODIS/AVHRR | Land cover, LSAI | External classification |
