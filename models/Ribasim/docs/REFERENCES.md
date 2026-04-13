# Ribasim References

## Official Resources

- **Documentation**: https://deltares.github.io/Ribasim/
- **Source Code**: https://github.com/Deltares/Ribasim
- **Python API (PyPI)**: https://pypi.org/project/ribasim/
- **Releases**: https://github.com/Deltares/Ribasim/releases
- **Issue Tracker**: https://github.com/Deltares/Ribasim/issues

## Developer

- **Organization**: Deltares (Netherlands)
- **License**: MIT

## Key Documentation Pages

- **User Guide**: https://deltares.github.io/Ribasim/guide/
- **Python API Reference**: https://deltares.github.io/Ribasim/python/reference/
- **Node Types**: https://deltares.github.io/Ribasim/reference/node/
- **Solver Configuration**: https://deltares.github.io/Ribasim/reference/usage/
- **Allocation**: https://deltares.github.io/Ribasim/concept/allocation/

## Context

Ribasim is the successor to the regional surface water modules Mozart and SIMRES
within the Netherlands Hydrological Instrument (NHI). It models water distribution
networks as directed graphs where nodes represent water system components (basins,
pumps, weirs, demands) and edges represent flow connections. The computational core
is written in Julia using the SciML ODE solver ecosystem; the Python API provides
model construction and I/O.

## Related Models

- **Mozart/SIMRES**: Predecessor Dutch regional water models (replaced by Ribasim)
- **NHI**: Netherlands Hydrological Instrument (Ribasim is a component)
- **DELWAQ**: Deltares water quality model (couples with Ribasim)
- **D-HYDRO / SOBEK**: Deltares 1D/2D hydrodynamic models (complementary)
