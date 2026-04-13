# TRIGRS v2.1 — References

## Official Documentation

- **USGS Open-File Report 2008-1159**: Baum, R.L., Savage, W.Z., and Godt, J.W., 2008, TRIGRS—A Fortran Program for Transient Rainfall Infiltration and Grid-Based Regional Slope-Stability Analysis, Version 2.0: U.S. Geological Survey Open-File Report 2008-1159.
- **Original TRIGRS Report (2002)**: Baum, R.L., Savage, W.Z., and Godt, J.W., 2002, TRIGRS—A Fortran program for transient rainfall infiltration and grid-based regional slope-stability analysis: U.S. Geological Survey Open-File Report 02-424.

## Source Code

- **USGS distribution**: https://code.usgs.gov/ghsc/lhp/trigrs
- **Compiled from**: `trigrs_full/src/TRIGRS/` (serial: `make trg`; parallel MPI: `make prg`)
- **Companion utilities**: TopoIndex (`src/TopoIndex/make tpx`), GridMatch, UnitConvert

## Key Papers

1. **Iverson, R.M.**, 2000, Landslide triggering by rain infiltration: Water Resources Research, v. 36, no. 7, p. 1897–1910. *(Saturated infiltration analytical solution)*
2. **Savage, W.Z., Godt, J.W., and Baum, R.L.**, 2003, A model for spatially and temporally distributed shallow landslide initiation by rainfall infiltration: in Rickenmann, D., and Chen, C., eds., Debris-Flow Hazards Mitigation — Mechanics, Prediction, and Assessment, Millpress, Rotterdam, p. 179–187. *(Extension to finite-depth)*
3. **Savage, W.Z., Godt, J.W., and Baum, R.L.**, 2004, Modeling time-dependent areal slope stability: in Lacerda, W.A., and others, eds., Landslides — Evaluation and Stabilization, Taylor and Francis, London, p. 23–36. *(Unsaturated zone model)*
4. **Srivastava, R., and Yeh, T.-C.J.**, 1991, Analytical solutions for one-dimensional, transient infiltration toward the water table in homogeneous and layered soils: Water Resources Research, v. 27, no. 5, p. 753–762. *(Unsaturated infiltration theory used by TRIGRS)*
5. **Alvioli, M., and Baum, R.L.**, 2016, Parallelization of the TRIGRS model for rainfall-induced landslides using the message passing interface: Environmental Modelling & Software, v. 81, p. 122–135. *(MPI parallel version)*

## Tutorial & Validation Data

- `data/tutorial/` — 10×10 grid, 2 zones, 2 rainfall periods (USGS reference case)
- `data/sy91/` — Srivastava & Yeh (1991) 1D column analytical test
- `data/flume/` — USGS debris-flow flume experiment
- `data/MinorCreek/` — Minor Creek, CA field study
