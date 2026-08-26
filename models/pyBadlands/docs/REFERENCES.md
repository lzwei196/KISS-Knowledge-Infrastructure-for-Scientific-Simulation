# pyBadlands — References

## Source Code

- **GitHub**: https://github.com/badlands-model/badlands
- **License**: GNU LGPL v3
- **Language**: Python + Fortran + C extensions
- **Build**: Meson + mesonpy

## Key Publications

1. **Salles, T. & Hardiman, L.** (2016). Badlands: An open-source, flexible and parallel framework to study landscape dynamics. *Computers & Geosciences*, 91, 1–11.

2. **Salles, T.** (2016). Badlands: A parallel basin and landscape dynamics model. *PLoS ONE*, 11(4), e0154295.

3. **Braun, J. & Willett, S.D.** (2013). A very efficient O(n), implicit and parallel method to solve the stream power equation governing fluvial incision and its application to natural and didactic examples. *Geomorphology*, 180–181, 170–179.

## Related Publications

4. **Salles, T., Ding, X., & Brocard, G.** (2018). pyBadlands: A framework to simulate sediment transport, landscape dynamics and basin stratigraphic evolution through space and time. *PLoS ONE*, 13(4), e0195557.

5. **Salles, T., Flament, N., & Müller, D.** (2017). Influence of mantle flow on the drainage of eastern Australia since the Jurassic Period. *Geochemistry, Geophysics, Geosystems*, 18(1), 280–305.

## Documentation

- **User Documentation PDF**: Included in source repo (`userdocumentation.pdf`)
- **Companion site**: https://badlands-model.github.io/badlands/

## Dependencies

| Package | Purpose | Reference |
|---------|---------|-----------|
| gFlex | Flexural isostasy | Wickert, A.D. (2016). Open-source modular solutions for flexural isostasy: gFlex v1.0. *Geoscientific Model Development*, 9(3), 997–1017. |
| triangle | Delaunay triangulation | Shewchuk, J.R. (1996). Triangle: Engineering a 2D quality mesh generator. |
| meshplex | Mesh processing | https://github.com/meshpro/meshplex |

## HydroCraft Validated Real-Site Runs

### Pearl River Basin, Mississippi/Louisiana, USA (DB row 3060)
- **DEM**: `pearl_river_dem_30m.tif` resampled to 1km UTM16N (104,569 TIN nodes)
- **Domain**: 293×450 km, 30–34°N, 88–91°W, relief 200 m
- **Parameters**: Kd=5e-5, caerial=0.5, cmarine=1.0, rain=1.5 m/yr, 1 Myr
- **Result**: 21.5 mm/kyr model vs 21.5 mm/kyr observed (PBIAS=0.0%)
- **Obs**: USGS WQP SSC stations 02489500 (Bogalusa, 86 obs) and 02492000 (Bush, 291 obs)
- **Key insight**: Low-relief landscape — diffusion (caerial) dominates, Kd is irrelevant
- **Output**: `KISSPATH_BINARIES/pyBadlands/pearl_river_run/output_v3_0`

### Modder River Basin, Free State, South Africa (DB row 3061)
- **DEM**: `srtm_modder_30m.tif` resampled to 1km UTM35S (53,109 TIN nodes)
- **Domain**: 295×225 km, 28–30°S, 24–27°E, relief 1042 m
- **Parameters**: Kd=8e-7, caerial=0.005, cmarine=0.01, rain=0.5 m/yr, 2 Myr
- **Result**: 12.76 mm/kyr model vs 5–20 mm/kyr observed (PBIAS=+2.1%)
- **Obs**: Published 10Be cosmogenic denudation (Codilean et al. 2014); GloRiSe 3 stations
- **Key insight**: High-relief landscape — SPL (Kd) dominates, caerial is irrelevant
- **Output**: `KISSPATH_BINARIES/pyBadlands/modder_river_run/output_v3_0`

### Multi-Site Statistics
- r=0.71, NSE=0.48, KGE=0.51, RMSE=4.9 mm/kyr, PBIAS=+6.3%
- Temporal elevation decay: Pearl River r=0.977 NSE=0.719; Modder r=0.996 NSE=0.862

## Observation Data Used

6. **Codilean, A.T. et al.** (2014). Controlling the scene: cosmogenic nuclide-derived erosion rates in passive margins. *Earth Surface Processes and Landforms*.

7. **GloRiSe**: Global River Sediment Database. Stations NAM-ORA-111113/4/5 (Orange River system, South Africa). TSS 2600–3400 mg/L.

8. **USGS WQP**: Water Quality Portal suspended sediment concentration (pcode 80154). Stations 02489500 (Pearl River, Bogalusa LA) and 02492000 (Bogue Chitto, Bush LA).

## Domain Context

pyBadlands models landscape evolution over geological timescales (10³–10⁸ years), coupling:
- Fluvial erosion (Stream Power Law)
- Hillslope diffusion (linear and non-linear)
- Tectonic uplift/subsidence
- Flexural isostasy
- Wave-driven sediment transport
- Carbonate reef growth
- Orographic rainfall
