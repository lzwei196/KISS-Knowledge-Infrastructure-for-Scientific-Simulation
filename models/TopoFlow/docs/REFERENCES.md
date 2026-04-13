# TopoFlow 3.6 References

## Official Resources

- **Source Code**: https://github.com/peckhams/topoflow36
- **CSDMS Model Page**: https://csdms.colorado.edu/wiki/Model:TopoFlow
- **Author**: Scott D. Peckham, INSTAAR, University of Colorado Boulder

## Key Publications

- Peckham, S.D. (2009). "Geomorphometric mapping." In *Geomorphometry: Concepts, Software, Applications* (Hengl & Reuter, eds.), Elsevier, pp. 579–602.
- Peckham, S.D., Hutton, E.W.H., & Norris, B. (2013). "A component-based approach to integrated modeling in the geosciences: The design of CSDMS." *Computers & Geosciences*, 53, 3–12. DOI: 10.1016/j.cageo.2012.04.002
- Peckham, S.D. & Goodall, J.L. (2013). "Driving plug-and-play models with data from web services: A demonstration of interoperability between CSDMS and CUAHSI-HIS." *Computers & Geosciences*, 53, 154–161.

## Framework

- **EMELI**: Experimental Modeling Environment for Linking and Interoperability
- **BMI**: Basic Model Interface — standardized initialization/time-stepping/data exchange
- **CSDMS**: Community Surface Dynamics Modeling System

## Data Sources (commonly used with TopoFlow)

- **ERA5**: ECMWF Reanalysis v5 — meteorological forcing (precipitation in kg/m²/s, temperature in K)
- **GLDAS**: Global Land Data Assimilation System — forcing data
- **CMFD**: China Meteorological Forcing Dataset — used for Chinese basin applications
- **HWSD**: Harmonized World Soil Database — soil parameters
- **SoilGrids**: ISRIC global soil property predictions at 250m resolution
- **SRTM/ASTER**: DEM sources for topographic inputs

## Related Models

- TOPMODEL (Beven & Kirkby, 1979) — conceptual topography-based model
- VIC (Liang et al., 1994) — Variable Infiltration Capacity macro-scale model
- SWAT (Arnold et al., 1998) — Soil and Water Assessment Tool
