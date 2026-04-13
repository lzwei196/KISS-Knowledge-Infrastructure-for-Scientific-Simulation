# ELM (E3SM Land Model) — References

## Official Documentation

- **E3SM Project**: https://e3sm.org/
- **ELM Documentation**: https://e3sm.org/model/e3sm-model-description/v3-description/v3-land/
- **E3SM User Guide**: https://docs.e3sm.org/

## Source Code

- **E3SM GitHub Repository**: https://github.com/E3SM-Project/E3SM
- **ELM component**: `components/elm/` within the E3SM repository
- **CIME framework**: `cime/` within the E3SM repository

## Key Publications

- Golaz, J.-C., et al. (2019). The DOE E3SM coupled model version 1: Overview and evaluation at standard resolution. *Journal of Advances in Modeling Earth Systems*, 11, 2089-2129. https://doi.org/10.1029/2018MS001603

- Golaz, J.-C., et al. (2022). The DOE E3SM Model Version 2: Overview of the physical model and initial model evaluation. *Journal of Advances in Modeling Earth Systems*, 14, e2022MS003156. https://doi.org/10.1029/2022MS003156

- Zhu, Q., et al. (2019). Representing nitrogen, phosphorus, and carbon interactions in the E3SM Land Model: Development and global benchmarking. *Journal of Advances in Modeling Earth Systems*, 11, 2238-2258. https://doi.org/10.1029/2018MS001571

- Bisht, G., et al. (2018). Coupling a three-dimensional subsurface flow and transport model with a land surface model to simulate stream-aquifer-land interactions (CP v1.0). *Geoscientific Model Development*, 11, 4337-4369. https://doi.org/10.5194/gmd-11-4337-2018

## Predecessor Model

- **CLM (Community Land Model)**: ELM descends from CLM4.5 with DOE-specific extensions for C/N/P cycling, FATES vegetation dynamics, and E3SM coupling.
- Lawrence, D.M., et al. (2019). The Community Land Model version 5: Description of new features, benchmarking, and impact of forcing uncertainty. *JAMES*, 11, 4245-4287. https://doi.org/10.1029/2018MS001583

## FATES (Vegetation Dynamics)

- Fisher, R.A., et al. (2015). Taking off the training wheels: the properties of a dynamic vegetation model without climate envelopes, CLM4.5(ED). *Geoscientific Model Development*, 8, 3593-3619. https://doi.org/10.5194/gmd-8-3593-2015
- **FATES GitHub**: https://github.com/NGEET/fates

## Forcing Data Sources

- **ERA5**: https://cds.climate.copernicus.eu/
- **GSWP3**: Global Soil Wetness Project Phase 3 forcing
- **CMFD**: China Meteorological Forcing Dataset (used for Huai River basin runs)

## Related KDT Validation

- Wangjiaba basin (station 51030): calibrated distributed ELM, NSE=0.55 (validation)
- Bengbu basin (station 51080): distributed ELM, cross-validated
