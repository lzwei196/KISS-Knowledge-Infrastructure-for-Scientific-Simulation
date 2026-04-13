# OpenGeoSys 6 — References

## Official Resources

- **Website**: https://www.opengeosys.org/
- **Documentation**: https://www.opengeosys.org/docs/
- **Source Code**: https://gitlab.opengeosys.org/ogs/ogs
- **GitHub Mirror**: https://github.com/ufz/ogs
- **Discourse Forum**: https://discourse.opengeosys.org/
- **Benchmarks/Tests**: https://www.opengeosys.org/docs/benchmarks/

## Key Publications

1. Bilke, L., Flemisch, B., Kalbacher, T., Kolditz, O., Helmig, R., & Nagel, T. (2019).
   Development of open-source porous media simulators: Principles and experiences.
   *Transport in Porous Media*, 130(1), 337–361.
   DOI: 10.1007/s11242-019-01310-1

2. Kolditz, O., Bauer, S., Bilke, L., Böttcher, N., Delfs, J. O., Fischer, T., ... & Zehner, B. (2012).
   OpenGeoSys: an open-source initiative for numerical simulation of thermo-hydro-mechanical/chemical (THM/C) processes in porous media.
   *Environmental Earth Sciences*, 67(2), 589–599.
   DOI: 10.1007/s12665-012-1546-x

3. Naumov, D., Bilke, L., Fischer, T., Huang, Y., Kolditz, O., Lehmann, C., ... & Xu, W. (2022).
   OpenGeoSys: Computational Methods in Environmental and Geotechnical Engineering.
   In *High Performance Computing in Science and Engineering '21* (pp. 271–287). Springer.

4. Kolditz, O., et al. (2015).
   *Thermo-Hydro-Mechanical-Chemical Processes in Fractured Porous Media: Modelling and Benchmarking.*
   Springer. (OGS Benchmark Books series)

## Python Interface

- **ogs6py**: https://github.com/joergbuchwald/ogs6py — Python interface for OGS6 project file manipulation
- **VTUinterface**: https://github.com/joergbuchwald/VTUinterface — Python VTU reading utilities
- **PyPI package**: `pip install ogs`

## Related Tools

- **GMSH**: https://gmsh.info/ — Mesh generation for OGS
- **ParaView**: https://www.paraview.org/ — VTU visualization
- **meshio**: https://github.com/nschloe/meshio — Mesh format conversion (Python)
- **pyvista**: https://docs.pyvista.org/ — VTK-based 3D plotting (Python)

## Unit Conversion References

- Darcy to m²: 1 Darcy = 9.869×10⁻¹³ m²
- Hydraulic conductivity to intrinsic permeability: κ = K × μ / (ρ × g)
- van Genuchten α (1/cm) to OGS: p_b = ρ·g / (α × 100)
