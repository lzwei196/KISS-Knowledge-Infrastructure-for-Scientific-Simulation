# OpenHydroQual References

## Source Code Repository

- **GitHub**: https://github.com/ArashMassoudieh/OpenHydroQual
- **License**: Open-source
- **Language**: C++14
- **Build system**: CMake / qmake

## Core Engine

- **Aquifolium**: Graph-based environmental simulation engine
  - GitHub: https://github.com/ArashMassoudieh/Aquifolium
  - Provides block-and-link topology, ODE/DAE solver, parameter estimation

## Key Publications

- Massoudieh, A. (2023). OpenHydroQual: An open-source environmental modeling
  platform for water quality simulation in interconnected hydrological systems.
  *Environmental Modelling & Software*.

- Massoudieh, A., Dentz, M., & Alikhani, J. (2017). A spatial Markov model
  for the evolution of the joint distribution of groundwater age, arrival time,
  and velocity in heterogeneous media. *Water Resources Research*, 53(7), 5495-5515.

## Activated Sludge Models

- Henze, M., Gujer, W., Mino, T., & van Loosdrecht, M.C.M. (2000).
  *Activated Sludge Models ASM1, ASM2, ASM2d and ASM3*. IWA Scientific
  and Technical Report No. 9. IWA Publishing.

## Biogeochemical Modeling

- Chapra, S.C. (2008). *Surface Water-Quality Modeling*. Waveland Press.
  (General reference for water quality constituent transport and reaction kinetics)

## Numerical Methods

- The model uses Crank-Nicholson time discretization with Newton-Raphson
  nonlinear iteration and adaptive timestepping.

## Related Software

- **SWMM**: EPA Storm Water Management Model (comparable surface water routing)
- **MODFLOW**: USGS modular groundwater flow model (comparable GW components)
- **WASP**: EPA Water Quality Analysis Simulation Program (comparable WQ reactions)
- **QUAL2K**: River and stream water quality model

## Template Documentation

JSON component templates in `resources/` define available block, link, source,
and reaction types. Key templates:

| Template | Domain |
|----------|--------|
| main_components.json | Core blocks, links, sources |
| river_processes.json | Reactive transport in streams |
| wastewater.json | ASM1 treatment reactors |
| Bioretention.json | Green infrastructure BMPs |
| evapotranspiration_models.json | ET methods (Penman, etc.) |
| groundwater.json | Unconfined aquifer cells |
| pipe_pump_tank.json | Water distribution |
| Sewer_system.json | Municipal wastewater |
