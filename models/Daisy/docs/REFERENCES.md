# Daisy Model — References

## Source Code

- **GitHub repository**: https://github.com/daisy-model/daisy
- **Build system**: CMake with preset `linux-gcc-portable`
- **Language**: C (174k LOC), with Python tools for pre/post-processing
- **License**: GPL (Per Abrahamsen, Søren Hansen, University of Copenhagen)

## Official Documentation

- **Daisy home page**: https://daisy.ku.dk/
- **User manual**: https://daisy.ku.dk/publications/ (Reference manual and tutorials)
- **Daisy model description**: Included in source repo under `doc/`

## Key Publications

- Abrahamsen, P. and Hansen, S. (2000). Daisy: an open soil-crop-atmosphere system model. *Environmental Modelling & Software*, 15(3), 313-330.
- Hansen, S., Jensen, H.E., Nielsen, N.E. and Svendsen, H. (1991). Simulation of nitrogen dynamics and biomass production in winter wheat using the Danish simulation model DAISY. *Fertilizer Research*, 27, 245-259.
- Hansen, S. (2002). Daisy, a flexible Soil-Plant-Atmosphere system Model. Department of Agricultural Sciences, The Royal Veterinary and Agricultural University, Denmark.

## Technical Details

- **Model type**: 1D mechanistic soil-plant-atmosphere model
- **Version tested**: 7.1.4 (built Mar 25, 2026)
- **Key processes**: Richards equation (water), multi-pool carbon/nitrogen turnover, crop growth (phenology, photosynthesis), macropore flow, pesticide fate
- **Forcing format**: Daisy Weather File (.dwf) — custom text format
- **Output format**: Daisy Log File (.dlf) — tab-separated with metadata header
- **Configuration**: Lisp-like .dai files with library system for crops, soils, management

## Validation Dataset

- **Site**: Taastrup, Denmark (1986-1988) — standard tutorial example
- **Also tested**: RISMA ON2, Ontario, Canada (soil moisture validation, MARGINAL result)

## Dependencies

- **Build**: g++, cmake, libsuitesparse-dev, libboost-filesystem-dev, python3-pybind11
- **Runtime**: libboost_filesystem.so.1.83.0 (or compatible symlink from 1.85)
- **Python tools**: numpy, pandas, matplotlib, pyyaml
