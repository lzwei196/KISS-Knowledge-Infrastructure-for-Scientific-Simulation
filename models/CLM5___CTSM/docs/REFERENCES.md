# CLM5 / CTSM References

## Official Documentation

- **CTSM Technical Note (CLM5.0)**: https://escomp.github.io/ctsm-docs/versions/master/html/tech_note/index.html
- **CTSM User's Guide**: https://escomp.github.io/ctsm-docs/versions/master/html/users_guide/index.html
- **CESM Documentation**: https://www.cesm.ucar.edu/models/cesm2/land/

## Source Code Repository

- **CTSM GitHub**: https://github.com/ESCOMP/CTSM
- **CIME GitHub**: https://github.com/ESMCI/cime
- **CESM GitHub**: https://github.com/ESCOMP/CESM

## Key Publications

1. **Lawrence, D. M., et al. (2019)**. The Community Land Model Version 5: Description of New Features, Benchmarking, and Impact of Forcing Uncertainty. *Journal of Advances in Modeling Earth Systems*, 11, 4245–4287. https://doi.org/10.1029/2018MS001583
   - Primary CLM5 description paper; global GPP ~120 PgC/yr, runoff ~40000 km3/yr

2. **Fisher, R. A., et al. (2019)**. Vegetation demographics in Earth System Models: A review of progress and priorities. *Global Change Biology*, 24, 35–54. https://doi.org/10.1111/gcb.13910
   - FATES vegetation demography model used in CLM5

3. **Wieder, W. R., et al. (2019)**. Beyond static benchmarking: Using experimental manipulations to evaluate land model assumptions. *Global Biogeochemical Cycles*, 33, 1289–1309.
   - CLM5 biogeochemistry validation

4. **Oleson, K. W., et al. (2013)**. Technical Description of version 4.5 of the Community Land Model (CLM). *NCAR Technical Note NCAR/TN-503+STR*.
   - Foundational technical description (CLM4.5, basis for CLM5)

5. **Medlyn, B. E., et al. (2011)**. Reconciling the optimal and empirical approaches to modelling stomatal conductance. *Global Change Biology*, 17, 2134–2144.
   - Medlyn stomatal conductance model used in CLM5 (`medlynslope`, `medlynintercept`)

## Input Data Sources

- **CESM Input Data**: https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata/
- **GSWP3 Forcing**: Global Soil Wetness Project Phase 3 atmospheric forcing
- **CRUJRA Forcing**: CRU-JRA v2.4 reanalysis-based forcing
- **ERA5 Reanalysis**: https://cds.climate.copernicus.eu/
- **HWSD Soil Data**: Harmonized World Soil Database v1.2
- **SoilGrids**: https://soilgrids.org/
- **CMFD Forcing**: China Meteorological Forcing Dataset (used in Wangjiaba validation)

## Related Models

- **MOSART**: Model for Scale Adaptive River Transport (river routing)
- **CISM**: Community Ice Sheet Model
- **CESM**: Community Earth System Model (parent framework)
- **FATES**: Functionally Assembled Terrestrial Ecosystem Simulator

## Community Resources

- **CESM Forums**: https://bb.cgd.ucar.edu/cesm/
- **CTSM Discussion**: https://github.com/ESCOMP/CTSM/discussions
- **CESM Tutorials**: https://www.cesm.ucar.edu/events/tutorials/
