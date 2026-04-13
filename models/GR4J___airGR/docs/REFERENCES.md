# GR4J (airGR) — References

## Primary Publication

- Perrin, C., Michel, C. and Andreassian, V. (2003). Improvement of a parsimonious model for streamflow simulation. *Journal of Hydrology*, 279(1-4), 275-289. doi:10.1016/S0022-1694(03)00225-7

## airGR R Package

- **CRAN**: https://cran.r-project.org/package=airGR
- **GitHub mirror**: https://github.com/cran/airGR
- **Version used**: v1.7.8
- **Vignette**: https://cran.r-project.org/web/packages/airGR/vignettes/V01_get_started.html

## airGR Package Reference Papers

- Coron, L., Thirel, G., Delaigue, O., Perrin, C. and Andreassian, V. (2017). The suite of lumped GR hydrological models in an R package. *Environmental Modelling & Software*, 94, 166-171. doi:10.1016/j.envsoft.2017.05.002

- Delaigue, O., Thirel, G., Coron, L. and Perrin, C. (2018). airGR and airGRteaching: two open-source tools for modelling and teaching hydrology. *EGU General Assembly 2018*.

## PE Oudin Formula

- Oudin, L., Hervieu, F., Michel, C., Perrin, C., Andreassian, V., Anctil, F. and Loumagne, C. (2005). Which potential evapotranspiration input for a lumped rainfall-runoff model? Part 2 - Towards a simple and efficient potential evapotranspiration model for rainfall-runoff modelling. *Journal of Hydrology*, 303(1-4), 290-306.

## CemaNeige Snow Module (optional coupling)

- Valery, A., Andreassian, V. and Perrin, C. (2014). 'As simple as possible but not simpler': What is useful in a temperature-based snow-accounting routine? Part 2 - Sensitivity analysis of the CemaNeige snow accounting routine on 380 catchments. *Journal of Hydrology*, 517, 1176-1187.

## Calibration Method

- Michel, C. (1991). Hydrologie appliquee aux petits bassins ruraux. *Cemagref*, Antony, France.

## Fortran Source

- Core subroutine: `frun_GR4J.f90` in airGR package `src/` directory
- Compiled as shared object: `airGR.so` via `R CMD INSTALL`

## HydroCraft Integration

- Knowledge infrastructure created for HydroCraft server by Jianyun Zhang Research Group, Hohai University
- 4 Python tools wrapping R/Fortran core via rpy2
