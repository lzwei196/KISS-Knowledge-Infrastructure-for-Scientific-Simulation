# RAPID References

## Source Code

- **GitHub Repository**: https://github.com/c-h-david/rapid
- **Author**: Cedric H. David (NASA JPL / University of Wisconsin)
- **License**: BSD 3-Clause

## Key Publications

1. **David, C.H., Maidment, D.R., Niu, G.-Y., Yang, Z.-L., Habets, F., and Eijkhout, V.** (2011).
   River network routing on the NHDPlus dataset.
   *Journal of Hydrometeorology*, 12(5), 913–934.
   DOI: 10.1175/2011JHM1345.1

2. **David, C.H., Famiglietti, J.S., Yang, Z.-L., Habets, F., and Maidment, D.R.** (2011).
   A decade of RAPID — Reflections on the development of an open source geoscience code.
   *Earth and Space Science*, 3, 226–244.

3. **David, C.H., Famiglietti, J.S., Yang, Z.-L., and Eijkhout, V.** (2015).
   Enhanced fixed-size parallel speedup with the Muskingum method using a trans-boundary approach and a large-scale river network.
   *Water Resources Research*, 51(3), 1–25.
   DOI: 10.1002/2014WR016650

4. **David, C.H., Hobbs, J., Novak, M.J., et al.** (2019).
   An analytical model for the estimation of water budget components including cloud storage.
   *Geophysical Research Letters*, 46.

5. **Emery, C.M., David, C.H., et al.** (2020).
   Temporal variability of the assimilation impact.
   *Journal of Hydrometeorology*, 21(2).

## Test Cases (included in repo)

| Test Case | Publication | Basin | Reaches |
|-----------|-------------|-------|---------|
| San_Guad_JHM | David et al. 2011 JHM | San Antonio–Guadalupe, TX | 5,175 |
| France_HP | David et al. 2011 HP | France national | ~90,000 |
| HSmsp_WRR | David et al. 2015 WRR | US (HydroSHEDS) | ~400,000 |
| WSWM_GRL | David et al. 2019 GRL | Western/Southern US | ~700,000 |
| MGBM_FRN | Sikder et al. | Mekong / Ganges-Brahmaputra-Meghna | varies |
| Reg07_JHM | David et al. 2011 JHM | Region 07 (Upper Mississippi) | varies |

## Dependencies

- **PETSc** (v3.13.6): https://petsc.org — Parallel linear algebra
- **MPICH**: https://www.mpich.org — MPI implementation (bundled with PETSc build)
- **NetCDF-Fortran**: https://www.unidata.ucar.edu/software/netcdf/ — I/O library
- **NHDPlus**: https://www.epa.gov/waterdata/nhdplus-national-hydrography-dataset-plus — US river network
- **MERIT-Hydro**: http://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/ — Global river network

## Related Models (coupling partners)

- **VIC** (Variable Infiltration Capacity) — provides lateral inflow
- **Noah/Noah-MP** (NCAR LSM) — provides lateral inflow
- **GLDAS** (Global Land Data Assimilation System) — provides forcing
- **CaMa-Flood** — downstream floodplain model
