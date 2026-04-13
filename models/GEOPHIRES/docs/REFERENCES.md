# GEOPHIRES-X References

## Source Code
- **GitHub Repository**: https://github.com/NREL/GEOPHIRES-X
- **License**: MIT
- **Current Version**: 3.11.25

## Official Documentation
- **NREL GEOPHIRES Page**: https://www.nrel.gov/geothermal/geophires.html
- **Installation Guide**: INSTALL.rst in source repository
- **README**: README.rst in source repository
- **Built-in Examples**: tests/examples/ directory (30+ example input/output pairs)

## Key Publications
- Beckers, K.F., & McCabe, K. (2019). "GEOPHIRES v2.0: updated geothermal techno-economic simulation tool." *Geothermal Energy*, 7(1), 5. https://doi.org/10.1186/s40517-019-0119-6
- Beckers, K.F., Lukawski, M.Z., Anderson, B.J., Moore, M.C., & Tester, J.W. (2014). "Levelized costs of electricity and direct-use heat from Enhanced Geothermal Systems." *Journal of Renewable and Sustainable Energy*, 6(1), 013141.

## Developer
- **Organization**: National Renewable Energy Laboratory (NREL), Golden, CO, USA
- **Lead Developer**: Koenraad Beckers (NREL)

## Key Dependencies
| Package | Purpose |
|---------|---------|
| numpy | Numerical computation |
| pint | Unit conversion system |
| scipy | Scientific computing, interpolation |
| matplotlib | Plotting and visualization |
| pandas | Data handling |
| h5py | HDF5 file I/O (AGS/SBT) |
| iapws | Water/steam thermodynamic properties |
| coolprop | Fluid thermodynamic properties |
| nrel-pysam | SAM economic model integration |

## Related Models
- **TOUGH2**: Reservoir simulator often coupled with GEOPHIRES for complex reservoir modeling
- **SUTRA**: Saturated-Unsaturated Transport model for thermal energy storage
- **SAM (System Advisor Model)**: NREL financial model integrated via nrel-pysam
