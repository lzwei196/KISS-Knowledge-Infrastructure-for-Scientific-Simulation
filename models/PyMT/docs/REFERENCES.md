# PyMT References

## Source Code
- **GitHub Repository:** https://github.com/csdms/pymt
- **PyPI:** https://pypi.org/project/pymt/
- **conda-forge:** https://anaconda.org/conda-forge/pymt

## Documentation
- **CSDMS PyMT Documentation:** https://pymt.readthedocs.io/
- **CSDMS Main Site:** https://csdms.colorado.edu/wiki/Model:PyMT
- **BMI Specification:** https://bmi.readthedocs.io/
- **CSDMS Standard Names:** https://csdms.colorado.edu/wiki/CSDMS_Standard_Names

## Key Papers
- Hutton, E.W.H., Piper, M.D., and Tucker, G.E. (2020). "The Basic Model Interface 2.0: A standard interface for coupling numerical models in the geosciences." *Journal of Open Source Software*, 5(51), 2317. https://doi.org/10.21105/joss.02317
- Tucker, G.E., Hutton, E.W.H., Piper, M.D., et al. (2022). "CSDMS: a community platform for numerical modeling of Earth surface processes." *Geoscientific Model Development*, 15, 1413-1439. https://doi.org/10.5194/gmd-15-1413-2022
- Peckham, S.D., Hutton, E.W.H., and Norris, B. (2013). "A component-based approach to integrated modeling in the geosciences: The design of CSDMS." *Computers & Geosciences*, 53, 3-12. https://doi.org/10.1016/j.cageo.2012.04.002

## Related Model Plugins
- pymt_cem (Coastline Evolution Model): https://github.com/csdms-contrib/pymt_cem
- pymt_hydrotrend (Climate-driven hydrological transport model): https://github.com/csdms-contrib/pymt_hydrotrend
- pymt_child (Channel-Hillslope Integrated Landscape Development): https://github.com/csdms-contrib/pymt_child
- Full plugin list: https://pymt.readthedocs.io/en/latest/models.html

## API Reference
- BMI methods: `initialize`, `update`, `finalize`, `get_value`, `set_value`
- Grid types: `uniform_rectilinear`, `rectilinear`, `structured`, `unstructured`
- Unit system: UDUNITS via gimli.units
