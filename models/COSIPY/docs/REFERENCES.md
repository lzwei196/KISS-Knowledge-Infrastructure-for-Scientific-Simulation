# COSIPY References

## Source Code
- **GitHub**: https://github.com/cryotools/cosipy
- **PyPI**: https://pypi.org/project/cosipymodel/
- **Documentation**: https://cosipy.readthedocs.io/

## Key Publications

1. **Sauter, T., & Arndt, A. (2020).** COSIPY v1.3 — An open-source coupled snowpack and ice surface energy and mass balance model. *Geoscientific Model Development*, 13, 5645–5662. doi:10.5194/gmd-13-5645-2020

2. **Oerlemans, J., & Knap, W. H. (1998).** A 1 year record of global radiation and albedo in the ablation zone of Morteratschgletscher, Switzerland. *Journal of Glaciology*, 44(147), 231–238. *(Albedo parameterization)*

3. **Bougamont, M., et al. (2005).** Sensitivity of ocean circulation to warming of the northeast Atlantic continental shelf. *Geophysical Research Letters*, 32. *(Albedo evolution scheme)*

4. **Moelg, T., et al. (2012).** Quantifying climate change in the tropical midtroposphere over East Africa from glacier shrinkage on Kilimanjaro. *Journal of Climate*, 25(21), 7406–7414. *(Roughness length parameterization)*

5. **Bintanja, R., & van den Broeke, M. R. (1995).** The surface energy balance of Antarctic snow and blue ice. *Journal of Applied Meteorology*, 34, 902–926. *(Penetrating shortwave radiation)*

## Test Datasets
- **Zhadang Glacier, Tibet**: ERA5 reanalysis 2009, included in repo (`data/input/Zhadang/`)
- **Hintereisferner (HEF), Austria**: Multi-year dataset with stake validation data (`data/input/HEF/`)

## Related Software
- **Dask**: https://dask.org/ — Distributed computing backend
- **xarray**: https://xarray.dev/ — NetCDF I/O and array operations
- **GDAL**: https://gdal.org/ — Geospatial raster processing (static file creation)
