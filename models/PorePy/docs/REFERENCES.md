# PorePy References

## Official Resources

- **Source Code**: https://github.com/pmgbergen/porepy
- **Documentation**: https://porepy.readthedocs.io/
- **PyPI**: https://pypi.org/project/PorePy/
- **License**: GPL v3

## Key Papers

1. **Keilegavlen, E., Berge, R., Fumagalli, A., Starnoni, M., Stefansson, I., Varela, J., & Berre, I. (2021).** PorePy: An open-source software for simulation of multiphysics processes in fractured porous media. *Computational Geosciences*, 25, 243–265. https://doi.org/10.1007/s10596-020-10002-5

2. **Berre, I., Doster, F., & Keilegavlen, E. (2019).** Flow in fractured porous media: A review of conceptual models and discretization approaches. *Transport in Porous Media*, 130(1), 215–236. https://doi.org/10.1007/s11242-018-1171-6

3. **Stefansson, I., Berre, I., & Keilegavlen, E. (2021).** A fully coupled numerical model of thermo-hydro-mechanical processes and fracture contact mechanics in porous media. *Computer Methods in Applied Mechanics and Engineering*, 386, 114122. https://doi.org/10.1016/j.cma.2021.114122

4. **Berge, R. L., Berre, I., Keilegavlen, E., Nordbotten, J. M., & Wohlmuth, B. (2020).** Finite volume discretization for poroelastic media with fractures modeled by contact mechanics. *International Journal for Numerical Methods in Engineering*, 121(4), 644–663. https://doi.org/10.1002/nme.6238

## Developers

- **Porous Media Group (PMG)**, Department of Mathematics, University of Bergen, Norway
- Lead: Eirik Keilegavlen, Ivar Berre

## Dependencies Documentation

- **Gmsh**: https://gmsh.info/doc/texinfo/gmsh.html
- **meshio**: https://github.com/nschloe/meshio
- **NumPy**: https://numpy.org/doc/stable/
- **SciPy**: https://docs.scipy.org/doc/scipy/
- **pypardiso**: https://github.com/haasad/PyPardisoProject

## Related Models (KDT Coupling Points)

- SWAT+ / VIC: Provide recharge boundary conditions
- MODFLOW: Pressure/head field comparison
- FLAC / ABAQUS: Import stress fields
- ERA5 / CMIP6: Transient boundary conditions
