# PFLOTRAN References

## Official Resources

- **Source Code Repository**: https://bitbucket.org/pflotran/pflotran
- **Documentation**: https://documentation.pflotran.org/
- **User Guide**: https://documentation.pflotran.org/user_guide/
- **Example Problems**: https://bitbucket.org/pflotran/pflotran/src/master/regression_tests/
- **Docker Image**: `pflotran/pflotran:latest` on Docker Hub

## Development

- **Primary Developers**: Los Alamos National Laboratory (LANL), Sandia National Laboratories (SNL), Oak Ridge National Laboratory (ORNL)
- **Language**: Fortran 90/95
- **Key Dependency**: PETSc (Portable, Extensible Toolkit for Scientific Computation) — https://petsc.org/

## Key Publications

- Lichtner, P.C., Hammond, G.E., Lu, C., Karra, S., Bisht, G., Andre, B., Mills, R.T., Kumar, J., Frederick, J.M. (2020). "PFLOTRAN Web Page." https://www.pflotran.org
- Hammond, G.E., Lichtner, P.C., Mills, R.T. (2014). "Evaluating the performance of parallel subsurface simulators: An illustrative example with PFLOTRAN." *Water Resources Research*, 50(1), 208-228. DOI: 10.1002/2012WR013483
- Lichtner, P.C., Hammond, G.E., Lu, C., Karra, S., Bisht, G., Andre, B., Mills, R.T., Kumar, J. (2015). "PFLOTRAN User Manual: A Massively Parallel Reactive Flow and Transport Model for Describing Surface and Subsurface Processes." Los Alamos National Laboratory Report LA-UR-15-20403.

## Related Datasets

- **HWSD**: Harmonized World Soil Database — soil texture for material properties
- **GLHYMPS**: Global Hydrogeology Maps — permeability and porosity
- **CMFD / ERA5 / MSWX**: Meteorological forcing for recharge estimation
- **GRACE TWS**: Gravity Recovery and Climate Experiment — total water storage for validation
- **Fan et al. WTD**: Global water table depth dataset for initial conditions

## Governing Equations

- **Richards Equation**: Variably saturated flow in porous media
- **van Genuchten Model**: Soil water retention and relative permeability (Carsel & Parrish, 1988)
- **Mualem Model**: Relative permeability function paired with van Genuchten
