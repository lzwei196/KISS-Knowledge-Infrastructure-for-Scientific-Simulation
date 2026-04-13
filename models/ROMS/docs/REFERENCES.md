# ROMS (Regional Ocean Modeling System) — References

## Official Resources

- **Source repository:** https://github.com/myroms/roms
- **Wiki / documentation:** https://www.myroms.org/wiki
- **User forum:** https://www.myroms.org/forum
- **ROMS homepage:** https://www.myroms.org

## Key Publications

- Shchepetkin, A.F. and McWilliams, J.C. (2005). The Regional Oceanic Modeling System (ROMS): A split-explicit, free-surface, topography-following-coordinate oceanic model. *Ocean Modelling*, 9(4), 347–404. doi:10.1016/j.ocemod.2004.08.002

- Shchepetkin, A.F. and McWilliams, J.C. (2003). A method for computing horizontal pressure-gradient force in an oceanic model with a nonaligned vertical coordinate. *Journal of Geophysical Research*, 108(C3), 3090. doi:10.1029/2001JC001047

- Haidvogel, D.B., Arango, H., Budgell, W.P., Cornuelle, B.D., Curchitser, E., Di Lorenzo, E., Fennel, K., Geyer, W.R., Hermann, A.J., Lanerolle, L., Levin, J., McWilliams, J.C., Miller, A.J., Moore, A.M., Powell, T.M., Shchepetkin, A.F., Sherwood, C.R., Signell, R.P., Warner, J.C., Wilkin, J. (2008). Ocean forecasting in terrain-following coordinates: Formulation and skill assessment of the Regional Ocean Modeling System. *Journal of Computational Physics*, 227(7), 3595–3624. doi:10.1016/j.jcp.2007.06.016

- Warner, J.C., Sherwood, C.R., Arango, H.G., and Signell, R.P. (2005). Performance of four turbulence closure models implemented using a generic length scale method. *Ocean Modelling*, 8(1–2), 81–113. doi:10.1016/j.ocemod.2003.12.003

## Vertical Coordinate and Stretching

- Song, Y. and Haidvogel, D.B. (1994). A semi-implicit ocean circulation model using a generalized topography-following coordinate system. *Journal of Computational Physics*, 115(1), 228–244. doi:10.1006/jcph.1994.1189

- Shchepetkin, A.F. (2015). An adaptive, Courant-number-dependent implicit scheme for vertical advection in oceanic modeling. *Ocean Modelling*, 91, 1–16. doi:10.1016/j.ocemod.2015.03.006

## Data Assimilation (4D-Var)

- Moore, A.M., Arango, H.G., Broquet, G., Powell, B.S., Weaver, A.T., Zavala-Garay, J. (2011). The Regional Ocean Modeling System (ROMS) 4-dimensional variational data assimilation systems. *Progress in Oceanography*, 91(1), 34–49. doi:10.1016/j.pocean.2011.05.004

## Coupled Models (Sediment, Waves, Biology)

- Warner, J.C., Armstrong, B., He, R., and Zambon, J.B. (2010). Development of a Coupled Ocean-Atmosphere-Wave-Sediment Transport (COAWST) Modeling System. *Ocean Modelling*, 35(3), 230–244. doi:10.1016/j.ocemod.2010.07.010

- Fennel, K., Wilkin, J., Levin, J., Moisan, J., O'Reilly, J., Haidvogel, D. (2006). Nitrogen cycling in the Middle Atlantic Bight: Results from a three-dimensional model and implications for the North Atlantic nitrogen budget. *Global Biogeochemical Cycles*, 20, GB3007. doi:10.1029/2005GB002456

## Configuration and Input Data

- **varinfo.yaml:** Variable metadata mapping — ships with ROMS source at `ROMS/External/varinfo.yaml`
- **OTPS:** Oregon State Tidal Prediction Software for tidal forcing extraction
- **GEBCO/ETOPO:** Global bathymetry datasets commonly used for grid generation
- **ERA5/NCEP:** Atmospheric reanalysis products for surface forcing
