# dfnWorks References

## Official Resources

- **Project website**: https://dfnworks.lanl.gov
- **Source code**: https://github.com/lanl/dfnWorks (LANL GitHub)
- **Documentation**: https://dfnworks.readthedocs.io
- **Contact**: dfnworks@lanl.gov
- **License**: LGPL-3.0 / GPL-2.0 (LANL LA-CC-17-027)

## Key Publications

1. Hyman, J.D., Karra, S., Makedonska, N., Gable, C.W., Painter, S.L., & Viswanathan, H.S. (2015). dfnWorks: A discrete fracture network framework for modeling subsurface flow and transport. *Computers & Geosciences*, 84, 10-19.

2. Hyman, J.D., Hagberg, A., Srinivasan, G., Mohd-Yusof, J., & Viswanathan, H. (2017). Predictions of first passage times in sparse discrete fracture networks using graph-based reductions. *Physical Review E*, 96(1), 013304.

3. Hyman, J.D., Dentz, M., Hagberg, A., & Kang, P.K. (2019). Linking structural and transport properties in three-dimensional fracture networks. *Journal of Geophysical Research: Solid Earth*, 124(2), 1185-1204.

4. Hyman, J.D., Jimenez-Martinez, J., Viswanathan, H.S., Carey, J.W., Porter, M.L., Rishi, E., Kang, P.K., Frash, L., Chen, L., Lei, Z., O'Malley, D., & Makedonska, N. (2016). Understanding hydraulic fracturing: a multi-scale problem. *Phil. Trans. R. Soc. A*, 374, 20150426.

## External Dependencies

- **LaGriT**: https://lagrit.lanl.gov — Los Alamos Grid Toolbox for meshing
- **PFLOTRAN**: https://www.pflotran.org — Parallel subsurface flow and reactive transport
- **FEHM**: https://fehm.lanl.gov — Finite Element Heat and Mass Transfer
- **PETSc**: https://petsc.org — Portable, Extensible Toolkit for Scientific Computation

## Version History

- **v2.10.0** (Feb 2026): Current version installed in HydroCraft KI
- Includes DFNGen v2.3, DFNTrans, pydfnworks Python wrapper
- Graph-based flow and transport (no external solver dependencies)
