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

## Domain Context

pyBadlands models landscape evolution over geological timescales (10³–10⁸ years), coupling:
- Fluvial erosion (Stream Power Law)
- Hillslope diffusion (linear and non-linear)
- Tectonic uplift/subsidence
- Flexural isostasy
- Wave-driven sediment transport
- Carbonate reef growth
- Orographic rainfall
