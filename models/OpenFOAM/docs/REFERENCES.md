# OpenFOAM References

## Official Resources

- **Source Code**: https://github.com/OpenFOAM/OpenFOAM-dev
- **Website**: https://openfoam.org
- **User Guide**: https://doc.cfd.direct/openfoam/user-guide-dev/
- **C++ API Documentation**: https://cpp.openfoam.org/dev/

## Key Publications

- Weller, H.G., Tabor, G., Jasak, H., Fureby, C. (1998). "A tensorial approach to computational continuum mechanics using object-oriented techniques." *Computers in Physics*, 12(6), 620-631. — Original OpenFOAM architecture paper.

- Jasak, H. (1996). "Error Analysis and Estimation for the Finite Volume Method with Applications to Fluid Flows." PhD Thesis, Imperial College London. — Foundation of OpenFOAM's FVM implementation.

## Validation Benchmarks

- Ghia, U., Ghia, K.N., Shin, C.T. (1982). "High-Re Solutions for Incompressible Flow Using the Navier-Stokes Equations and a Multigrid Method." *Journal of Computational Physics*, 48, 387-411. — Standard lid-driven cavity benchmark used for KDT validation.

## Solver References

- Issa, R.I. (1986). "Solution of the Implicitly Discretised Fluid Flow Equations by Operator-Splitting." *Journal of Computational Physics*, 62, 40-65. — PISO algorithm.

- Patankar, S.V. (1980). *Numerical Heat Transfer and Fluid Flow.* Hemisphere Publishing. — SIMPLE algorithm foundation.

- Hirt, C.W., Nichols, B.D. (1981). "Volume of Fluid (VOF) Method for the Dynamics of Free Boundaries." *Journal of Computational Physics*, 39(1), 201-225. — VoF method used in interFoam/incompressibleVoF.

## Turbulence Model References

- Launder, B.E., Spalding, D.B. (1974). "The Numerical Computation of Turbulent Flows." *Computer Methods in Applied Mechanics and Engineering*, 3(2), 269-289. — k-epsilon model.

- Menter, F.R. (1994). "Two-Equation Eddy-Viscosity Turbulence Models for Engineering Applications." *AIAA Journal*, 32(8), 1598-1605. — k-omega SST model.

## Build and Installation

- **Build system**: wmake (custom Make-based system), Allwmake master script
- **Prerequisites**: GCC >= 7, OpenMPI/MPICH, Scotch/METIS, flex
- **KDT build location**: `KISSPATH_BINARIES/OpenFOAM/source/repo/`
- **Platform**: linux64GccDPInt32Opt (64-bit, GCC, double precision, 32-bit int labels)
