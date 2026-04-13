# LPJmL — References

## Source Code Repository

- **GitHub**: https://github.com/PIK-LPJmL/LPJmL
- **Version used**: v6.0.0
- **Developer**: PIK (Potsdam Institute for Climate Impact Research), Potsdam, Germany

## Key Publications

### Core Model Description
- Schaphoff, S., von Bloh, W., Rammig, A., Thonicke, K., Biemans, H., Forkel, M., Gerten, D., Heinke, J., Jägermeyr, J., Knauer, J., Langerwisch, F., Lucht, W., Müller, C., Rolinski, S., & Waha, K. (2018). **LPJmL4 – a dynamic global vegetation model with managed land – Part 1: Model description.** *Geoscientific Model Development*, 11, 1343–1375. https://doi.org/10.5194/gmd-11-1343-2018

- Schaphoff, S., Forkel, M., Müller, C., Knauer, J., von Bloh, W., Gerten, D., Jägermeyr, J., Lucht, W., Rammig, A., Thonicke, K., & Waha, K. (2018). **LPJmL4 – a dynamic global vegetation model with managed land – Part 2: Model evaluation.** *Geoscientific Model Development*, 11, 1377–1403. https://doi.org/10.5194/gmd-11-1377-2018

### Crop Modeling
- Bondeau, A., Smith, P.C., Zaehle, S., Schaphoff, S., Lucht, W., Cramer, W., Gerten, D., Lotze-Campen, H., Müller, C., Reichstein, M., & Smith, B. (2007). **Modelling the role of agriculture for the 20th century global terrestrial carbon balance.** *Global Change Biology*, 13, 679–706. https://doi.org/10.1111/j.1365-2486.2006.01305.x

- Jägermeyr, J., Müller, C., Ruane, A.C., Elliott, J., Balkovic, J., Castillo, O., et al. (2021). **Climate impacts on global agriculture emerge earlier in new generation of climate and crop models.** *Nature Food*, 2, 873–885. https://doi.org/10.1038/s43016-021-00400-y

### Nitrogen Cycling
- von Bloh, W., Schaphoff, S., Müller, C., Rolinski, S., Waha, K., & Zaehle, S. (2018). **Implementing the nitrogen cycle into the dynamic global vegetation, hydrology, and crop growth model LPJmL (version 5.0).** *Geoscientific Model Development*, 11, 2789–2812. https://doi.org/10.5194/gmd-11-2789-2018

### Hydrology and Irrigation
- Rost, S., Gerten, D., Bondeau, A., Lucht, W., Rohwer, J., & Schaphoff, S. (2008). **Agricultural green and blue water consumption and its influence on the global water system.** *Water Resources Research*, 44, W09405. https://doi.org/10.1029/2007WR006331

- Jägermeyr, J., Gerten, D., Heinke, J., Schaphoff, S., Kummu, M., & Lucht, W. (2015). **Water savings potentials of irrigation systems: global simulation of processes and linkages.** *Hydrology and Earth System Sciences*, 19, 3073–3091. https://doi.org/10.5194/hess-19-3073-2015

## Documentation

- **LPJmL Wiki**: https://github.com/PIK-LPJmL/LPJmL/wiki
- **Configuration guide**: See `docs/s3_configuration.md` in this KI package

## Input Data Sources

- **Climate forcing**: GSWP3-W5E5 (for ISIMIP), CRU TS (monthly)
- **Soil data**: HWSD (Harmonized World Soil Database)
- **Land use**: LandInG (Land Input Generator) or HYDE
- **CO2**: Historical from Mauna Loa / ice cores; scenarios from SSP/RCP
- **Fertilizer**: Mueller et al. (2012), Zhang et al. (2015)
