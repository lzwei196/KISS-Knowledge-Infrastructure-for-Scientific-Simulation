# S2: Soil Parameter Conversion

## Purpose
Convert soil texture/property data from HWSD or other databases to SWAP Mualem-van Genuchten (MvG) hydraulic parameters and profile discretization.

## Inputs
- **HWSD raster**: /mnt/disk1/Hydrocraft_server/data/soil/HWSD_China_Geo.img
- **Site coordinates**: lat, lon
- **OR manual texture**: Sand%, Silt%, Clay% per layer
- **Profile depth**: Total soil column depth (cm)

## Outputs
- MvG parameter table for .swp file: ORES, OSAT, ALFA, NPAR, KSATFIT, LEXP, ALFAW, H_ENPR, KSATEXM, BDENS
- Profile discretization table: ISUBLAY, ISOILLAY, HSUBLAY, HCOMP, NCOMP

## Procedure
1. **Extract soil texture**: Read HWSD at point, or use manual input
2. **Classify texture**: Apply USDA texture triangle → class name
3. **Pedotransfer function**: Map texture class → MvG parameters using Schaap et al. (2001) / Carsel & Parrish (1988)
4. **Adjust for layers**: Topsoil typically has higher Ksat, lower bulk density than subsoil
5. **Profile discretization**:
   - Fine near surface (1 cm compartments, top 10 cm)
   - Medium in root zone (5 cm, 10-60 cm)
   - Coarse at depth (10 cm, 60-200 cm)
6. **Validate parameter ranges**: All within SWAP limits

## Verification
- ORES < OSAT for all layers
- NPAR > 1.001
- ALFA > 0.0001
- KSATFIT in physically meaningful range for texture class
- Sum of HSUBLAY = total profile depth
- NCOMP × HCOMP = HSUBLAY for each sub-layer

## Traps

### TRAP 1: Ksat units
HWSD and many databases report Ksat in m/day, m/s, or cm/hr. SWAP expects cm/day.
- m/day → cm/day: × 100
- m/s → cm/day: × 8,640,000 (= 100 × 86400)
- cm/hr → cm/day: × 24

### TRAP 2: Bulk density units
SWAP BDENS is in mg/cm³, which is numerically equal to kg/m³.
- g/cm³ → mg/cm³: × 1000 (e.g., 1.35 g/cm³ = 1350 mg/cm³)
- Entering 1.35 directly: SWAP clips to minimum 100, producing nonsense

### TRAP 3: ALFA parameter sign
ALFA must be positive in SWAP. Some literature reports it as negative (e.g., HYDRUS convention). Always use absolute value.

### TRAP 4: Layer boundary mismatch
Soil physical layer boundaries (ISOILLAY) must align with sub-layer boundaries (ISUBLAY). If layer 1 extends to 30 cm but sub-layers split at 25 cm, there will be an inconsistency.

### TRAP 5: Too-coarse discretization at surface
Compartments > 5 cm near the surface cause poor representation of evaporation front and infiltration. Use 1 cm for top 10 cm.

## Example
```
* Profile discretization (200 cm total)
 ISUBLAY  ISOILLAY  HSUBLAY  HCOMP  NCOMP
       1         1     10.0    1.0     10    ! Fine near surface
       2         1     20.0    5.0      4    ! Medium in topsoil
       3         2     30.0    5.0      6    ! Transition
       4         2    140.0   10.0     14    ! Coarse at depth

* MvG parameters (sandy loam topsoil, loam subsoil)
 ORES  OSAT    ALFA   NPAR  KSATFIT    LEXP   ALFAW  H_ENPR  KSATEXM   BDENS
 0.065 0.410  0.0750  1.890   106.10   0.500  0.1500     0.0   106.10  1450.0
 0.078 0.430  0.0360  1.560    24.96   0.500  0.0720     0.0    24.96  1400.0
```
