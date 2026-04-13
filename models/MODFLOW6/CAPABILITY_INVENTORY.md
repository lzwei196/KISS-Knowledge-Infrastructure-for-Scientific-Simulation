# MODFLOW 6.6.1 -- Capability Inventory (KDT v5.0 Stage s2)

**Generated**: 2026-04-01
**Source**: MODFLOW 6.6.1 (February 7, 2025), USGS
**Documentation**: `mf6io.pdf` (369+ pages), `release.pdf`, `mf6suptechinfo.pdf`
**Binary**: `/mnt/disk1/Hydrocraft_server/model/modflow6/mf6.6.1_linux/bin/mf6`
**Python interface**: FloPy 3.10.0 (`flopy.mf6`)
**Current KI version**: 1.2.0 (SFR streamflow routing added 2026-04-03)

---

## Summary

| Category | Total Capabilities | In Current KI | Missing from KI |
|----------|--------------------|---------------|-----------------|
| GWF Model Types | 4 | 1 (GWF basic) | 3 |
| GWF Discretization | 3 | 1 (DIS) | 2 |
| GWF Internal Flow Packages | 6 | 2 (NPF, STO) | 4 |
| GWF Stress Packages | 10 | 6 (CHD,WEL,RCH,DRN,RIV,SFR) | 4 |
| GWF Advanced Packages | 4 | 0 | 4 |
| GWT Model (Transport) | 11 | 7 (NAM,DIS,IC,ADV,DSP,MST,SSM,CNC,OC) | 4 (IST,SRC,SFT,LKT,MWT,UZT,FMI,MVT) |
| GWE Model (Energy) | 10 | 0 | 10 |
| PRT Model (Particle) | 4 | 0 | 4 |
| Exchange/Coupling | 4 | 1 (GWF-GWT) | 3 |
| Utilities | 6 | 2 (IMS, OC) | 4 |
| **Total** | **62** | **20** | **42** |

---

## 1. MODEL TYPES

### 1.1 GWF -- Groundwater Flow Model
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 24-168
- **What it does**: Solves the 3D groundwater flow equation using finite-difference or control-volume finite-difference methods. Supports confined, unconfined, and convertible layers. Newton-Raphson formulation for wetting/drying.
- **KI tools**: Full pipeline (S1-S9), validated on Bengbu basin
- **Options used**: NEWTON UNDER_RELAXATION

### 1.2 GWT -- Groundwater Transport Model
- **Status**: DONE in KI (core packages)
- **Source**: mf6io.pdf pp. 169-226
- **What it does**: Solves the advection-dispersion equation for solute transport. Must be coupled to a GWF model via GWF-GWT Exchange. Can also run standalone reading saved GWF files via FMI.
- **Known limitations (v6.6.1)**:
  - Decay/sorption not applied to LKT, SFT, MWT, UZT packages
  - Does not work with CSUB package
  - GWT-GWT Exchange requires both GWF models run concurrently
  - No steady-state option; run long transient to find equilibrium
  - No MOC or particle tracking (only FD methods: upstream, central, TVD)
- **KI tools**: `configure_gwt.py` (build coupled/standalone GWT), `parse_gwt_output.py` (concentrations, plumes, breakthrough curves)
- **Validated**: Minimal 1D advection-dispersion test (coupled mode), normal termination, correct plume evolution
- **Packages covered**: NAM, DIS, IC, ADV, DSP, MST, SSM, CNC, OC
- **Packages NOT yet covered**: IST (immobile domain), SRC (mass source), SFT/LKT/MWT/UZT (advanced transport), FMI (standalone mode -- code exists but not tested on real case), MVT

### 1.3 GWE -- Groundwater Energy Transport Model
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 227-282; introduced in v6.5.0 (May 2024)
- **What it does**: Simulates heat transport in groundwater. Solves the energy transport equation accounting for advection, conduction, dispersion, and energy storage in both aqueous and solid phases.
- **Packages**: ADV, CND, EST, SSM, CTP, ESL, SFE, LKE, MWE, UZE, FMI
- **Known limitations**: Does not work with CSUB; GWE-GWE Exchange requires concurrent GWF models
- **KI GAP**: Entirely missing. New capability (v6.5+).

### 1.4 PRT -- Particle Tracking Model
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 283-299
- **What it does**: Tracks particles through the flow field computed by GWF. Uses generalized pollock method. Supports particle release points (PRP package), cell face flows.
- **Packages**: MIP (Model Input), PRP (Particle Release Point), OC
- **Output**: Particle track file (pathlines)
- **KI GAP**: Entirely missing.

---

## 2. GWF DISCRETIZATION PACKAGES

### 2.1 DIS -- Structured Discretization
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 35-37
- **What it does**: Regular rectangular grid. Specified by NLAY, NROW, NCOL, DELR, DELC, TOP, BOTM.
- **KI tools**: `build_dis_package.py`, `build_layers_from_global.py`

### 2.2 DISV -- Discretization by Vertices
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 38-41
- **What it does**: Vertically layered but horizontally unstructured grid defined by vertices and cell connectivity. Supports quadtree refinement, Voronoi grids.
- **Use case**: Local grid refinement around wells, rivers, or areas of interest
- **KI GAP**: Not documented. Would require mesh generation tools.

### 2.3 DISU -- Unstructured Discretization
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 42-46
- **What it does**: Fully unstructured grid. Each node has explicit neighbor connections. Maximum flexibility but most complex to set up.
- **Use case**: Complex geological structures, fault zones
- **KI GAP**: Not documented. Specialized use case.

---

## 3. GWF INTERNAL FLOW PACKAGES

### 3.1 NPF -- Node Property Flow
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 53-56
- **What it does**: Specifies hydraulic conductivity (K), cell type (confined/convertible), K anisotropy, wetting/drying options, XT3D (full tensor K).
- **KI tools**: `build_npf_package.py`, `assign_k_from_glhymps.py`
- **Options used**: ICELLTYPE=1 (convertible), K from GLHYMPS/HWSD

### 3.2 STO -- Storage
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 61-63
- **What it does**: Specifies specific storage (Ss) and specific yield (Sy) for transient simulations. Supports STORAGECOEFFICIENT and ICONVERT options.
- **KI tools**: `build_sto_package.py`

### 3.3 TVK -- Time-Varying Hydraulic Conductivity
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 57-58
- **What it does**: Allows K values to change over stress periods. Useful for seasonal freezing/thawing.
- **Known limitation**: Incompatible with HFB package near flow barriers
- **KI GAP**: Not documented.

### 3.4 TVS -- Time-Varying Storage
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 64-65
- **What it does**: Allows Ss and Sy to change over stress periods.
- **KI GAP**: Not documented.

### 3.5 HFB -- Horizontal Flow Barrier
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 59-60
- **What it does**: Simulates thin, low-permeability barriers (faults, sheet piling, slurry walls) between adjacent cells.
- **KI GAP**: Not documented. Specialized use case.

### 3.6 CSUB -- Skeletal Storage, Compaction, and Subsidence
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 66-73; tm6a62.pdf (57 pages)
- **What it does**: Simulates aquifer-system compaction, land subsidence, and skeletal storage. Tracks elastic/inelastic compaction of interbeds.
- **Known limitations**: Does not work with GWT or GWE models
- **KI GAP**: Not documented. Important for regions with significant pumping.

---

## 4. GWF STRESS PACKAGES

### 4.1 CHD -- Constant Head
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 81-83
- **What it does**: Fixes hydraulic head at specified cells. Used for domain boundaries.
- **KI tools**: `build_chd_package.py`

### 4.2 WEL -- Well
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 84-87
- **What it does**: Pumping/injection wells with specified volumetric rates.
- **KI tools**: `build_wel_package.py`
- **KI GAP**: No global pumping dataset adapter.

### 4.3 DRN -- Drain
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 88-91
- **What it does**: Drains remove water when head is above drain elevation. One-way (only removes water). Used for springs, agricultural drains, baseflow.
- **KI tools**: `build_drn_package.py`

### 4.4 RIV -- River
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 92-95
- **What it does**: Two-way stream-aquifer interaction. Water can flow from river to aquifer (losing reach) or aquifer to river (gaining reach). Specified by stage, conductance, river bottom elevation.
- **KI tools**: `build_riv_package.py`, `build_riv_from_cama.py`
- **Data KI**: CaMa-Flood river network

### 4.5 RCH -- Recharge
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 100-106
- **What it does**: Applies areal recharge to the model. List-based or array-based input. Can specify which layer receives recharge (IRCH).
- **KI tools**: `build_rch_package.py` (includes VIC coupling)
- **Variants**: List-based (RCH, pp.100) and Array-based (RCHA, pp.104)

### 4.6 GHB -- General Head Boundary
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 96-99
- **What it does**: Head-dependent flux boundary. Flow proportional to difference between cell head and external head. Two-way (can add or remove water).
- **Use case**: Distant boundary conditions, regional flow systems
- **KI GAP**: Not documented. Could be useful for boundaries.

### 4.7 EVT -- Evapotranspiration
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 107-113
- **What it does**: Simulates ET as a head-dependent sink. Maximum ET at surface, linearly decreasing to extinction depth. Can apply to multiple segments.
- **Variants**: List-based (EVT) and Array-based (EVTA)
- **Data KI needed**: VIC ET output or CMFD/MSWX PET
- **Data KI exists**: CMFD (YES), MSWX (YES)
- **KI GAP**: Not documented. Important for shallow water table regions.

### 4.8 MAW -- Multi-Aquifer Well
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 114-122
- **What it does**: Simulates wells that are open to multiple aquifer layers. Computes intraborehole flow between layers. Head-dependent pumping with flowing wells.
- **Methods**: Thiem equation or screen geometry for conductance
- **KI GAP**: Not documented. Specialized use case.

### 4.9 SFR -- Streamflow Routing
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 123-137
- **What it does**: Simulates 1D open-channel flow in stream networks. Routes flow downstream through connected reaches. Computes stream-aquifer interaction, diversions. Supports irregular cross sections.
- **Features**: Reach connectivity, diversions, upstream inflows, Manning's equation, cross-section tables
- **Examples**: `ex-gwf-sfr-p01`, `ex-gwf-sfr-pindersauera/b`
- **KI tools**: `configure_sfr.py` (build SFR from reach data or simple cell list), `parse_sfr_output.py` (stages, exchange, budget)
- **Data KI**: CaMa-Flood river network (partial -- provides widths and discharge for inflow, no cross sections or Manning's n)
- **Validated**: Self-contained test model (10-reach diagonal stream, 10x10 grid), normal termination, budget closure -0.00%

### 4.10 LAK -- Lake
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 138-148
- **What it does**: Simulates lake-aquifer interaction. Lakes can receive precipitation, runoff, GW inflow; lose water to ET, GW outflow, outlet discharge. Supports multiple outlets, stage-area-volume tables.
- **Features**: Lake stage calculation, outlet flow (weir/gate/specified), lake-GW exchange
- **Examples**: `ex-gwf-lak-p01`, `ex-gwf-lak-p02`
- **Data KI needed**: HydroLAKES (lake geometry)
- **Data KI exists**: HydroLAKES (YES)
- **KI GAP**: Not documented. Important for basins with significant lakes.

---

## 5. GWF ADVANCED PACKAGES

### 5.1 UZF -- Unsaturated Zone Flow
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 151-157
- **What it does**: Simulates vertical flow through the unsaturated zone. Computes recharge to water table and ET from the unsaturated zone. Uses kinematic wave approximation.
- **Features**: Infiltration, ET from UZ, GW seepage, rejected infiltration
- **Known limitation**: UZF routing beneath lakes and streams not implemented
- **Examples**: None in distribution (but UZT examples exist for transport)
- **Data KI needed**: Soil properties (residual water content, saturated water content, Brooks-Corey epsilon)
- **KI GAP**: Not documented. **MEDIUM PRIORITY** -- would provide physics-based recharge instead of prescribed RCH.

### 5.2 MVR -- Water Mover
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 158-161
- **What it does**: Moves water between packages (e.g., SFR reach to LAK, MAW to SFR). Enables complex water management scenarios: diversions, transfers, irrigation returns.
- **Methods**: FACTOR, EXCESS, THRESHOLD, UPTO
- **KI GAP**: Not documented. Needed for coupled SFR-LAK simulations.

### 5.3 GNC -- Ghost Node Correction
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 162-163
- **What it does**: Corrects flow calculations for non-ideal cell connections in DISV/DISU grids.
- **KI GAP**: Not documented. Only needed with DISV/DISU.

### 5.4 BUY -- Buoyancy
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 74-76
- **What it does**: Simulates variable-density flow due to solute concentration differences (e.g., saltwater intrusion).
- **Known limitations**: Cannot use with XT3D or GWF-GWF Exchange
- **KI GAP**: Not documented. Specialized (coastal aquifers).

### 5.5 VSC -- Viscosity
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 77-80
- **What it does**: Simulates viscosity effects on groundwater flow due to temperature or concentration changes.
- **Known limitations**: Cannot use with GWF-GWF Exchange
- **KI GAP**: Not documented. Specialized (thermal/saline systems).

---

## 6. GWT (GROUNDWATER TRANSPORT) PACKAGES

Core GWT packages are **DONE in KI** (7 of 11+). Advanced transport packages (SFT, LKT, MWT, UZT) remain NOT in KI.

### 6.1 GWT Model Name File
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 172-174
- **What it does**: Defines the GWT model, specifies packages, enables save/print options.
- **KI tools**: `configure_gwt.py` creates NAM file automatically

### 6.2 ADV -- Advection
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 180
- **Schemes**: UPSTREAM (default, most stable), CENTRAL, TVD (Total Variation Diminishing, most accurate)
- **KI notes**: UPSTREAM recommended for general use. TVD better for sharp fronts but may require finer grid.

### 6.3 DSP -- Dispersion
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 181-182
- **What it does**: Specifies longitudinal/transverse dispersivity, molecular diffusion coefficient.
- **KI notes**: XT3D_OFF used by default for speed. Remove for 2D/3D diagonal flow problems.
- **Key params**: DIFFC (m2/day), ALH (m), ATH1 (m), ATV (m), ALV (m)

### 6.4 SSM -- Source and Sink Mixing
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 183-185
- **What it does**: Assigns concentrations to GWF stress package flows (recharge, wells, etc.).
- **KI notes**: Required if GWF has any stress packages. Three methods: default (C=0), AUX (auxiliary variable on GWF package), SPC6 (separate file).

### 6.5 MST -- Mobile Storage and Transfer
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 186-187
- **What it does**: Sorption (linear, Freundlich, Langmuir), first/zero-order decay in mobile domain.
- **KI notes**: Porosity is REQUIRED. Sorption needs bulk_density + distcoef. Decay needs decay rate.

### 6.6 IST -- Immobile Storage and Transfer
- **Source**: mf6io.pdf pp. 188-190
- **What it does**: Dual-domain mass transfer between mobile and immobile zones.

### 6.7 CNC -- Constant Concentration
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 191-193
- **KI tools**: `configure_gwt.py` creates CNC when source_concentration + source_cells provided

### 6.8 SRC -- Mass Source Loading
- **Source**: mf6io.pdf pp. 194-196

### 6.9 SFT -- Streamflow Transport
- **Source**: mf6io.pdf pp. 197-201

### 6.10 LKT -- Lake Transport
- **Source**: mf6io.pdf pp. 203-208

### 6.11 MWT -- Multi-Aquifer Well Transport
- **Source**: mf6io.pdf pp. 209-213

### 6.12 UZT -- Unsaturated Zone Transport
- **Source**: mf6io.pdf pp. 214-218

### 6.13 FMI -- Flow Model Interface
- **Source**: mf6io.pdf pp. 219-221
- **What it does**: Reads GWF flow solution for use by GWT/GWE models.

### 6.14 MVT -- Mover Transport
- **Source**: mf6io.pdf pp. 222

---

## 7. GWE (GROUNDWATER ENERGY TRANSPORT) PACKAGES

All GWE packages are **NOT in KI**. Introduced in v6.5.0.

| Package | Description | mf6io page |
|---------|-------------|------------|
| GWE NAM | Model name file | 230-231 |
| ADV | Advection | 238 |
| CND | Conduction and Dispersion | 239-240 |
| EST | Energy Storage and Transfer | 241-242 |
| SSM | Source and Sink Mixing | 243-244 |
| CTP | Constant Temperature | 246-248 |
| ESL | Energy Source Loading | 249-251 |
| SFE | Streamflow Energy Transport | 252-256 |
| LKE | Lake Energy Transport | 258-263 |
| MWE | Multi-Aquifer Well Energy Transport | 264-268 |
| UZE | Unsaturated Zone Energy Transport | 270-274 |
| FMI | Flow Model Interface | 275-277 |
| MVE | Mover Energy Transport | 278 |

---

## 8. EXCHANGE MODELS AND COUPLING

### 8.1 GWF-GWF Exchange
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 165-168
- **What it does**: Couples two GWF models for local grid refinement (LGR) or regional-local coupling.
- **Examples**: `ex-gwf-lgr`, `ex-gwf-u1gwfgwf-s1` through `s4`, `ex-gwf-lgrv-*`

### 8.2 GWF-GWT Exchange
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 223-226
- **What it does**: Couples GWF and GWT models. Passes flow information from GWF to GWT.
- **KI tools**: `configure_gwt.py` handles exchange setup automatically
- **Validated**: Coupled GWF-GWT runs successfully with normal termination

### 8.3 GWF-GWE Exchange
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 279-282
- **What it does**: Couples GWF and GWE models for heat transport.

### 8.4 GWT-GWT Exchange
- **Status**: NOT in KI
- **What it does**: Couples two GWT models.
- **Known limitation**: Requires both corresponding GWF models run concurrently.

---

## 9. UTILITIES

### 9.1 IMS -- Iterative Model Solution
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 300-306
- **Complexity levels**: SIMPLE, MODERATE, COMPLEX
- **KI notes**: Newton requires MODERATE or COMPLEX (not SIMPLE due to CG incompatibility with asymmetric matrices)

### 9.2 EMS -- Explicit Model Solution
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 307
- **What it does**: Explicit time stepping for transport models. Alternative to IMS for GWT/GWE.

### 9.3 OC -- Output Control
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 48-50 (GWF), pp. 176-177 (GWT), pp. 234-235 (GWE), pp. 295-297 (PRT)

### 9.4 OBS -- Observation Utility
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 308-324
- **What it does**: Extracts simulated values at observation locations. Supports head, drawdown, flow observations for all packages.
- **KI GAP**: Not documented. Useful for calibration/validation.

### 9.5 ATS -- Adaptive Time Stepping
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 22-23
- **What it does**: Automatically adjusts time step length based on convergence behavior. New ATS support for GWT ADV (v6.6.0) and GWE ADV (v6.6.1).

### 9.6 TDIS -- Temporal Discretization
- **Status**: DONE in KI
- **Source**: mf6io.pdf pp. 20-21
- **KI tools**: `build_tdis_package.py`

### 9.7 Extended MODFLOW (NetCDF, HPC)
- **Status**: NOT in KI
- **Source**: mf6io.pdf pp. 366-369
- **Features**: NetCDF input/output (NCF package), parallel computing (HPC package)
- **Requirements**: Requires extended MODFLOW binary with third-party libraries
- **KI GAP**: Not documented. Only needed for very large models.

---

## 10. EXAMPLES IN DISTRIBUTION

The MODFLOW 6.6.1 distribution includes 107 example problems:

| Category | Count | Examples |
|----------|-------|---------|
| GWF basic | ~30 | ex-gwf-twri01, ex-gwf-toth, ex-gwf-bump-*, ex-gwf-bcf2ss-* |
| GWF-SFR | 4 | ex-gwf-sfr-p01, ex-gwf-sfr-p01b, ex-gwf-sfr-pindersauer* |
| GWF-LAK | 2 | ex-gwf-lak-p01, ex-gwf-lak-p02 |
| GWF-MAW | 6 | ex-gwf-maw-p01a/b, ex-gwf-maw-p02, ex-gwf-maw-p03a/b/c |
| GWF-DRN | 2 | ex-gwf-drn-p01a/b |
| GWF-CSUB | 5 | ex-gwf-csub-p01, ex-gwf-csub-p02a/b/c, ex-gwf-csub-p03a/b, p04 |
| GWF-LGR | 6 | ex-gwf-lgr, ex-gwf-lgrv-*, ex-gwf-u1gwfgwf-s1..s4 |
| GWF-NWT | 4 | ex-gwf-nwt-p02a/b, ex-gwf-nwt-p03a/b |
| GWT | ~30 | ex-gwt-mt3dms-p01..p10, ex-gwt-henry-*, ex-gwt-moc3d-*, etc. |
| GWE | 7 | ex-gwe-ates, ex-gwe-barends, ex-gwe-danckwerts, etc. |
| PRT | 2 | ex-prt-mp7-p01, ex-prt-mp7-p03 |

---

## 11. DATA KI MAPPING

| MODFLOW Capability | Required Data | Data KI | Status |
|--------------------|---------------|---------|--------|
| Grid (DIS) | DEM, basin boundary | ChinaDEM, SRTM | AVAILABLE + tool exists |
| Layer elevations | DEM + DTB | ChinaDEM, DTB | AVAILABLE + tool exists |
| K values (NPF) | Subsurface K | GLHYMPS, HWSD | AVAILABLE + tool exists |
| Storage (STO) | Ss, Sy | Literature defaults | AVAILABLE |
| Initial heads (IC) | Water table depth | FanWTD | AVAILABLE + tool exists |
| Recharge (RCH) | Precip/ET/runoff | VIC output, CMFD | AVAILABLE + tool exists |
| River (RIV) | Stream network | CaMa-Flood | AVAILABLE + tool exists |
| CHD boundaries | Regional heads | DEM-derived | AVAILABLE + tool exists |
| Drain (DRN) | Drain elevations | DEM-derived | AVAILABLE + tool exists |
| Well (WEL) | Pumping rates | No global dataset | MISSING |
| EVT | Max ET rate, extinction depth | CMFD/MSWX | AVAILABLE (no adapter) |
| SFR | Stream network + cross sections | CaMa-Flood (partial) | AVAILABLE + tool exists |
| LAK | Lake geometry | HydroLAKES | AVAILABLE (no adapter) |
| UZF | Unsaturated zone properties | SoilGrids, HWSD | AVAILABLE (no adapter) |
| GWT/GWE transport | Contaminant/temperature data | WQP (water quality) | PARTIAL |
| Observed heads | GW monitoring wells | No global dataset | MISSING |

---

## 12. PRIORITY RANKING FOR KI EXPANSION

### High Priority (enable new HydroCraft capabilities)
1. ~~**GWT Model** (Section 6) -- DONE in KI v1.1.0~~
2. ~~**SFR Package** (4.9) -- DONE in KI v1.2.0~~
3. **LAK Package** (4.10) -- Lake-aquifer interaction. Complements HydroLAKES data.
4. **OBS Utility** (9.4) -- Enables model calibration and validation.

### Medium Priority (improve existing runs)
5. **UZF Package** (5.1) -- Physics-based recharge replaces prescribed RCH.
6. **EVT Package** (4.7) -- ET from shallow water table.
7. **GWF-GWF Exchange** (8.1) -- Local grid refinement for detailed studies.
8. **GHB Package** (4.6) -- Better boundary conditions than CHD.
9. **ATS Utility** (9.5) -- Adaptive time stepping for convergence.
10. **GWE Model** (Section 7) -- Heat transport. Geothermal applications.

### Lower Priority (specialized applications)
11. **CSUB Package** (3.6) -- Land subsidence. Important in specific regions (e.g., Beijing, Shanghai).
12. **MAW Package** (4.8) -- Multi-aquifer wells.
13. **MVR Package** (5.2) -- Water mover for complex management.
14. **BUY Package** (5.4) -- Saltwater intrusion.
15. **VSC Package** (5.5) -- Viscosity effects.
16. **PRT Model** (Section 8) -- Particle tracking for capture zones, travel times.
17. **DISV/DISU** (2.2, 2.3) -- Unstructured grids.
18. **TVK/TVS** (3.3, 3.4) -- Time-varying properties.
19. **HFB** (3.5) -- Flow barriers.
20. **Extended MODFLOW** (9.7) -- NetCDF/HPC.

---

## 13. CROSS-MODEL COUPLING OPPORTUNITIES

| Coupling | From | To | Mechanism | Status |
|----------|------|----|-----------|--------|
| VIC -> MODFLOW RCH | VIC deep percolation | RCH package | mm/day -> m/day | DONE in KI |
| MODFLOW DRN -> Routing | Drain discharge | Lohmann/CaMa baseflow | m3/day extraction | DONE in KI |
| CaMa-Flood -> MODFLOW RIV | River stage | RIV package stage | Direct | DONE in KI |
| MODFLOW WT -> VIC | Water table depth | VIC soil capacity | Feedback | DOCUMENTED (not automated) |
| HYPE N/P -> MODFLOW GWT | Nutrient leachate | GWT source terms | SSM package | NOT DONE |
| MODFLOW GWT -> HYPE | GW concentrations | HYPE return flow conc. | Not defined | NOT DONE |
| HYPE lake -> MODFLOW LAK | Lake stage/volume | LAK package | Not defined | NOT DONE |
| VIC ET -> MODFLOW EVT | ET demand | EVT package | mm/day -> m/day | NOT DONE |
