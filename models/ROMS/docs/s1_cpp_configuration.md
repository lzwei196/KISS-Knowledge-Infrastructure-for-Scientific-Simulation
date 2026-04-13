# S1: CPP Configuration

## Purpose

Select the physics options and numerical schemes for a ROMS simulation by defining
C-preprocessor (CPP) flags in an application header file. These flags are evaluated
at compile time and determine which code paths are included in the binary. Changing
any flag requires recompilation.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Application header | `.h` file | CPP `#define` directives |
| Physics requirements | User decision | Which processes to simulate |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `my_app.h` | Fortran header | Complete CPP configuration |
| Compiled binary | `romsS`/`romsM` | Binary with selected options |

## Procedure

### Step 1: Choose core physics

**Always define for 3D simulations:**
```c
#define UV_ADV          /* momentum advection */
#define UV_COR          /* Coriolis force */
#define UV_QDRAG        /* quadratic bottom drag (or UV_LDRAG for linear) */
#define DJ_GRADPS       /* Shchepetkin pressure gradient */
#define SOLVE3D         /* 3D baroclinic model */
#define SALINITY        /* include salinity tracer */
#define NONLINEAR       /* nonlinear model */
```

### Step 2: Select vertical mixing closure

Choose ONE of:
```c
#define LMD_MIXING      /* Large-McWilliams-Doney KPP */
#define GLS_MIXING       /* Generic Length Scale (k-epsilon, k-omega, gen) */
#define MY25_MIXING      /* Mellor-Yamada Level 2.5 */
```

If using LMD_MIXING, also define sub-options:
```c
#define LMD_RIMIX       /* Richardson number interior mixing */
#define LMD_CONVEC      /* convective instability mixing */
#define LMD_SKPP        /* surface KPP boundary layer */
#define LMD_BKPP        /* bottom KPP boundary layer */
#define LMD_NONLOCAL    /* nonlocal transport */
```

### Step 3: Choose atmospheric coupling

**Option A — Precomputed fluxes:**
Supply wind stress, heat flux, freshwater flux directly.
```c
/* No special define needed — just provide forcing files */
```

**Option B — Bulk flux formulas (recommended for realistic runs):**
```c
#define BULK_FLUXES     /* compute fluxes from atmospheric state */
#define EMINUSP         /* E-P freshwater flux */
#define LONGWAVE_OUT    /* compute outgoing longwave internally */
#define SOLAR_SOURCE    /* shortwave penetration */
```

**TRAP:** Do NOT define `BULK_FLUXES` AND supply precomputed fluxes. This
will double-count surface forcing.

### Step 4: Select advection scheme
```c
#define TS_U3HADVECTION  /* 3rd-order upstream for tracers */
#define TS_C4VADVECTION  /* 4th-order centered vertical */
/* OR */
#define TS_MPDATA        /* MPDATA for tracers */
```

### Step 5: Add optional physics
```c
/* Tides */
#define SSH_TIDES       /* tidal elevation forcing */
#define UV_TIDES        /* tidal current forcing */
#define ADD_FSOBC       /* add tidal elevation to boundary */
#define ADD_M2OBC       /* add tidal currents to boundary */

/* Biology */
#define BIOLOGY
#define BIO_FENNEL      /* Fennel nitrogen-based ecosystem */

/* Sediment */
#define SEDIMENT        /* sediment transport */
#define SUSPLOAD        /* suspended load */
#define BEDLOAD_MPM     /* Meyer-Peter-Mueller bed load */

/* Waves */
#define WEC_VF          /* wave effects on currents (vortex force) */

/* Nesting */
#define NESTING         /* grid nesting support */
#define ONE_WAY         /* one-way nesting */

/* Wet/dry */
#define WET_DRY         /* wetting and drying */

/* Analytical functions (for idealized cases) */
#define ANA_GRID        /* analytical grid */
#define ANA_INITIAL     /* analytical initial conditions */
#define ANA_SMFLUX      /* analytical surface momentum flux */
#define ANA_STFLUX      /* analytical surface tracer flux */
```

### Step 6: Mixing direction
```c
#define MIX_S_UV        /* mix momentum along S-surfaces */
#define MIX_S_TS        /* mix tracers along S-surfaces */
/* OR */
#define MIX_GEO_UV      /* mix momentum along geopotentials */
#define MIX_GEO_TS      /* mix tracers along geopotentials */
/* OR */
#define MIX_ISO_TS      /* mix tracers along isopycnals */
```

## Verification

```bash
# List all active CPP flags after compilation
grep -r "#define" my_app.h | grep -v "^!"

# Check build log for activated options
grep "CPP" build/CMakeCache.txt
```

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Multiple mixing closures | Defining both LMD and GLS | Compile error or undefined behavior |
| BULK_FLUXES + precomputed fluxes | Double-counting | Unrealistic surface forcing |
| Missing SALINITY | For ocean runs | Salt fixed, wrong density |
| ANA_* with data files | Analytical overrides data | Silent — analytical wins |
| SOLVE3D undefined | Only 2D shallow water | No temperature/salinity evolution |
| Wrong MIX direction | MIX_S in steep terrain | Excessive diapycnal mixing |

## Example: Realistic Mid-Atlantic Bight

```c
/* my_mab.h — Mid-Atlantic Bight configuration */
#define UV_ADV
#define UV_COR
#define UV_QDRAG
#define DJ_GRADPS
#define SOLVE3D
#define SALINITY
#define NONLINEAR
#define CURVGRID
#define MASKING
#define BULK_FLUXES
#define EMINUSP
#define LONGWAVE_OUT
#define SOLAR_SOURCE
#define GLS_MIXING
#define CANUTO_A
#define N2S2_HORAVG
#define TS_U3HADVECTION
#define TS_C4VADVECTION
#define MIX_GEO_TS
#define MIX_S_UV
#define SSH_TIDES
#define UV_TIDES
#define ADD_FSOBC
#define ADD_M2OBC
```
