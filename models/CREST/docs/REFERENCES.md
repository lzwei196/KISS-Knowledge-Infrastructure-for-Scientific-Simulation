# CREST / EF5 References

## Source Code

- **EF5 GitHub Repository**: https://github.com/HyDROSLab/EF5
  - Contains CREST, SAC-SMA, HyMOD, and HP models in a unified C++ framework
  - License: GPL v3

## Key Papers

- **CREST Model**:
  - Wang, J., Hong, Y., Li, L., Gourley, J.J., Khan, S.I., Yilmaz, K.K., Adler, R.F., Policelli, F.S., Habib, S., Irwn, D., Limaye, A.S., Korme, T., Okello, L. (2011). The Coupled Routing and Excess STorage (CREST) distributed hydrological model. *Hydrological Sciences Journal*, 56(1), 84-98.
  - Khan, S.I., Hong, Y., Wang, J., Yilmaz, K.K., Gourley, J.J., Adler, R.F., Brakenridge, G.R., Policelli, F., Habib, S., Irwin, D. (2011). Satellite remote sensing and hydrologic modeling for flood inundation mapping in Lake Victoria basin: Implications for hydrologic prediction in ungauged basins. *IEEE Transactions on Geoscience and Remote Sensing*, 49(1), 85-95.

- **EF5 Framework**:
  - Clark, R.A., Flamig, Z.L., Vergara, H., Hong, Y., Gourley, J.J., Mandl, D.J., Frye, S., Handy, M., Patterson, M. (2017). Hydrological modeling and capacity building in the Republic of Namibia. *Bulletin of the American Meteorological Society*, 98(8), 1697-1715.
  - Flamig, Z.L., Vergara, H., Gourley, J.J. (2020). The Ensemble Framework For Flash Flood Forecasting (EF5) v1.2: Description and case studies. *Geoscientific Model Development*, 13, 4943-4958.

- **Variable Infiltration Curve (Xinanjiang)**:
  - Zhao, R.J. (1992). The Xinanjiang model applied in China. *Journal of Hydrology*, 135(1-4), 371-381.

## Documentation

- EF5 User Guide (in source repo): `docs/` directory
- EF5 configuration reference: control file format documented in SKILL.md

## Related Datasets

- **CMFD**: China Meteorological Forcing Dataset (precipitation, temperature, radiation)
- **HWSD**: Harmonized World Soil Database (soil properties for parameter estimation)
- **MSWX**: Multi-Source Weighted-Ensemble Precipitation (global forcing alternative)

## HydroCraft Integration

- KI tools in `tools/` directory provide automated pipeline for:
  - DEM/DDM/FAM preparation
  - Forcing conversion (CMFD/MSWX to EF5 format)
  - Soil parameter grid generation (HWSD to CREST parameters)
  - Output parsing and metric computation (NSE, KGE, PBIAS)
