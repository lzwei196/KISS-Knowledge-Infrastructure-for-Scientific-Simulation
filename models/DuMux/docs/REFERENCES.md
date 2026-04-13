# DuMux — References

## Official Resources

- **DuMux Homepage**: https://dumux.org/
- **Source Code (GitLab)**: https://git.iws.uni-stuttgart.de/dumux-repositories/dumux
- **Documentation**: https://dumux.org/docs/doxygen/master/
- **Installation Guide**: https://dumux.org/docs/doxygen/master/installation.html
- **DUNE Framework**: https://www.dune-project.org/

## Key Publications

- Koch, T., Gläser, D., Weishaupt, K., Ackermann, S., Beck, M., Becker, B., ... & Flemisch, B. (2021).
  **DuMux 3 – an open-source simulator for solving flow and transport problems in porous media with a focus on model coupling.**
  *Computers & Mathematics with Applications*, 81, 423–443.
  DOI: 10.1016/j.camwa.2020.02.012

- Flemisch, B., Darcis, M., Erbertseder, K., Faigle, B., Lauser, A., Mosthaf, K., ... & Helmig, R. (2011).
  **DuMux: DUNE for Multi-{Phase, Component, Scale, Physics, ...} Flow and Transport in Porous Media.**
  *Advances in Water Resources*, 34(9), 1102–1112.
  DOI: 10.1016/j.advwatres.2011.03.007

## Theoretical Background

- Helmig, R. (1997).
  **Multiphase Flow and Transport Processes in the Subsurface: A Contribution to the Modeling of Hydrosystems.**
  Springer. ISBN: 978-3-642-60763-9

- Bear, J. (1972).
  **Dynamics of Fluids in Porous Media.**
  Dover Publications. ISBN: 978-0-486-65675-5

## Example: 1p Tracer Transport

The validated example (`example_1ptracer`) solves single-phase Darcy flow coupled with tracer transport on a 2D structured grid with an embedded low-permeability lens. This is the canonical DuMux test case for advection-diffusion in heterogeneous porous media.

- Source: `dumux/examples/1ptracer/`
- DuMux course materials: https://dumux.org/docs/doxygen/master/example_1ptracer.html

## Related DUNE Modules

| Module | Purpose |
|--------|---------|
| dune-common | Core infrastructure |
| dune-geometry | Reference elements, mappings |
| dune-grid | Grid interfaces and implementations |
| dune-istl | Iterative solver template library |
| dune-localfunctions | Local basis functions |
| dune-alugrid | Adaptive unstructured grids |
| dune-foamgrid | 1D/2D network grids (fractures) |
