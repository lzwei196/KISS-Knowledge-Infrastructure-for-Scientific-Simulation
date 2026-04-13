# HydroCNHS References

## Source Code & Documentation
- **GitHub Repository**: https://github.com/philip928lin/HydroCNHS
- **PyPI Package**: https://pypi.org/project/hydrocnhs/
- **Documentation**: https://hydrocnhs.readthedocs.io/

## Key Publications
- Lin, C.-Y., Yang, Y.-C. E., & Wi, S. (2022). HydroCNHS: A Python Package for Coupled Natural-Human Systems Modeling. *Journal of Water Resources Planning and Management*, 148(3). https://doi.org/10.1061/(ASCE)WR.1943-5452.0001520
- Lin, C.-Y., & Yang, Y.-C. E. (2022). The effects of model complexity on model output uncertainty in co-evolved coupled natural-human systems. *Earth's Future*, 10(5), e2021EF002403. https://doi.org/10.1029/2021EF002403

## Model Components
- **GWLF (Generalized Watershed Loading Functions)**: Haith, D. A., & Shoemaker, L. L. (1987). *Journal of the American Water Resources Association*, 23(3), 471-478.
- **ABCD Model**: Thomas, H. A. (1981). *Improved Methods for National Water Assessment*. US Water Resources Council, Report WR15249270.
- **Lohmann Routing**: Lohmann, D., et al. (1996). A large-scale horizontal routing model to be coupled to land surface parameterization schemes. *Tellus A*, 48(5), 708-721.
- **DEAP (GA calibration)**: Fortin, F.-A., et al. (2012). DEAP: Evolutionary Algorithms Made Easy. *Journal of Machine Learning Research*, 13, 2171-2175.

## Validation Basin
- **Tualatin River Basin, Oregon**: USGS streamflow data for Tualatin River at West Linn (WSLO). https://waterdata.usgs.gov/nwis
- **Wangjiaba, Huai River**: Cross-validation on Huai River upstream of Bengbu (station 51030)

## Dependencies
- NumPy, SciPy, pandas, scikit-learn, matplotlib, DEAP, joblib, ruamel.yaml, tqdm
