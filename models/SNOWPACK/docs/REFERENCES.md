# SNOWPACK References

## Official Resources

- **Homepage**: https://snowpack.slf.ch/
- **Source code**: https://github.com/snowpack-model/snowpack
- **MeteoIO library**: https://github.com/snowpack-model/snowpack (bundled in same repo)
- **Documentation wiki**: https://models.slf.ch/docserver/snowpack/html/
- **Developer**: WSL Institute for Snow and Avalanche Research SLF, Davos, Switzerland

## Key Publications

- Bartelt, P. and Lehning, M. (2002). A physical SNOWPACK model for the Swiss avalanche warning. Part I: numerical model. *Cold Regions Science and Technology*, 35(3), 123–145. doi:10.1016/S0165-232X(02)00074-5

- Lehning, M., Bartelt, P., Brown, B., Fierz, C., and Satyawali, P. (2002). A physical SNOWPACK model for the Swiss avalanche warning. Part II: Snow microstructure. *Cold Regions Science and Technology*, 35(3), 147–167. doi:10.1016/S0165-232X(02)00073-3

- Lehning, M., Bartelt, P., Brown, B., and Fierz, C. (2002). A physical SNOWPACK model for the Swiss avalanche warning. Part III: meteorological forcing, thin layer formation and evaluation. *Cold Regions Science and Technology*, 35(3), 169–184. doi:10.1016/S0165-232X(02)00072-1

- Lehning, M., Völksch, I., Gustafsson, D., Nguyen, T.A., Stähli, M., and Zappa, M. (2006). ALPINE3D: a detailed model of mountain surface processes and its application to snow hydrology. *Hydrological Processes*, 20(10), 2111–2128. doi:10.1002/hyp.6204

## MeteoIO

- Bavay, M. and Egger, T. (2014). MeteoIO 2.4.2: a preprocessing library for meteorological data. *Geoscientific Model Development*, 7, 3135–3151. doi:10.5194/gmd-7-3135-2014

## Data Formats

- **SMET**: Swiss Meteorological Exchange Text format — MeteoIO's native ASCII format for time series
- **SNO**: SNOWPACK initial snow/soil profile format
- **INI**: Configuration file format (Windows INI-style sections)

## Related Models

- **Alpine3D**: 3D distributed snow model wrapping SNOWPACK (same codebase)
- **FSM**: Factorial Snow Model (simpler alternative for intercomparison)
- **CROCUS**: French detailed snow model (comparable complexity)
