#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_initial_conditions
Stage:        s5_initial_conditions
Description:  Generate SUMMA cold-start initial conditions NetCDF.

              Sets initial states for snow (SWE=0, no layers), soil
              (temperature from mean annual T, moisture near field capacity),
              canopy (no ice/liquid), and aquifer (near-zero storage).

              CRITICAL: The initial conditions file must have dimensions that
              match the soil layer configuration. The default is 8 soil layers
              with depths [0.025, 0.075, 0.15, 0.25, 0.50, 0.50, 1.0, 1.5] m.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ATTRIBUTES_NC = ""
OUTPUT_NC = ""
N_SOIL_LAYERS = 8
SOIL_LAYER_DEPTHS = [0.025, 0.075, 0.15, 0.25, 0.50, 0.50, 1.0, 1.5]  # meters
INIT_SOIL_TEMP = 288.5     # K (15.4 C) — matches Reynolds test case
INIT_SOIL_MOISTURE = 0.29  # volumetric fraction — matches Reynolds
INIT_MATRIC_HEAD = -100.0  # m — Reynolds fallback ONLY; see derive_matric_head (dt_034)
INIT_CANOPY_LIQ = 3.16     # kg/m² — matches Reynolds (some canopy water)
TRIAL_PARAMS_NC = None     # s4 trialParams.nc — enables the vGn inversion
INIT_MOISTURE_FROM = "value"
MATRIC_HEAD_EXPLICIT = False


def derive_matric_head(n_hru):
    """Return (theta[n_hru], head[n_hru], info) consistent with each other.

    dt_034 -- THE SILENT ONE. This tool used to write mLayerVolFracLiq from
    --init_moisture while writing mLayerMatricHead from a hard-coded -100 m,
    two numbers that describe DIFFERENT soil states. SUMMA does not reconcile
    them and does not complain: under the KI's own default decision
    `f_Richards = mixdform`, matric head is the PROGNOSTIC variable in
    unsaturated soil (`updateSoil` recomputes theta from psi at the first
    step), so the head wins and --init_moisture is silently discarded.

    -100 m is close to the wilting point for most textures. On a 4 m profile
    that is ~600 mm of storage deficit, which the basin then spends YEARS
    filling before it generates any runoff at all -- surfacing much later as
    dt_011 "all runoff is zero" with an intact water balance, i.e. the most
    expensive possible way to find a one-line initial-condition bug.

    Fix: invert the van Genuchten retention curve for the requested theta,
    per HRU, using the same s4 parameters SUMMA itself will use:

        Se  = (theta - theta_r) / (theta_s - theta_r)
        m   = 1 - 1/n
        psi = -(1/alpha) * (Se**(-1/m) - 1)**(1/n)

    SUMMA stores vGn_alpha NEGATIVE (matric-head convention, SKILL.md 2b), so
    the curve is evaluated with alpha = |vGn_alpha|.
    """
    info = {"mode": INIT_MOISTURE_FROM}

    if MATRIC_HEAD_EXPLICIT:
        theta = np.full(n_hru, INIT_SOIL_MOISTURE, dtype=float)
        head = np.full(n_hru, INIT_MATRIC_HEAD, dtype=float)
        info.update(source="explicit_--init_matric_head",
                    consistent=False,
                    warning="matric head set explicitly; it is NOT guaranteed "
                            "consistent with --init_moisture")
        logger.warning(info["warning"])
        return theta, head, info

    if not TRIAL_PARAMS_NC or not Path(TRIAL_PARAMS_NC).exists():
        theta = np.full(n_hru, INIT_SOIL_MOISTURE, dtype=float)
        head = np.full(n_hru, INIT_MATRIC_HEAD, dtype=float)
        info.update(source="constant_fallback", consistent=False,
                    matric_head_m=INIT_MATRIC_HEAD)
        logger.warning(
            "no --trial_params_nc: falling back to a CONSTANT matric head of "
            f"{INIT_MATRIC_HEAD} m, which CONTRADICTS --init_moisture="
            f"{INIT_SOIL_MOISTURE}. Under f_Richards=mixdform the head wins and "
            "your --init_moisture is silently ignored (dt_034). Pass "
            "--trial_params_nc settings/trialParams.nc.")
        return theta, head, info

    from netCDF4 import Dataset as _DS
    with _DS(TRIAL_PARAMS_NC) as tp:
        def get(name):
            if name not in tp.variables:
                raise KeyError(f"{name} missing from {TRIAL_PARAMS_NC}")
            return np.asarray(tp.variables[name][:], dtype=float).reshape(-1)
        th_s = get('theta_sat')
        th_r = get('theta_res')
        alpha = np.abs(get('vGn_alpha'))
        nvg = get('vGn_n')
        fc = get('fieldCapacity') if 'fieldCapacity' in tp.variables else None

    for nm, arr in (("theta_sat", th_s), ("theta_res", th_r),
                    ("vGn_alpha", alpha), ("vGn_n", nvg)):
        if arr.size not in (1, n_hru):
            raise ValueError(f"{nm} has {arr.size} values, expected 1 or {n_hru}")
    bc = lambda a: np.full(n_hru, a[0]) if a.size == 1 else a
    th_s, th_r, alpha, nvg = map(bc, (th_s, th_r, alpha, nvg))

    if INIT_MOISTURE_FROM == "field_capacity":
        if fc is None:
            raise KeyError("fieldCapacity missing from trialParams.nc; cannot "
                           "use --init_moisture_from field_capacity")
        theta = bc(fc).copy()
        info["basis"] = "per-HRU fieldCapacity"
    else:
        theta = np.full(n_hru, INIT_SOIL_MOISTURE, dtype=float)
        info["basis"] = f"--init_moisture={INIT_SOIL_MOISTURE}"

    # Keep strictly inside (theta_r, theta_s): Se=0 -> psi=-inf, Se=1 -> psi=0
    # (saturation, which is the instability the Reynolds constant was dodging).
    lo = th_r + 0.01 * (th_s - th_r)
    hi = th_r + 0.95 * (th_s - th_r)
    clipped = int(np.sum((theta < lo) | (theta > hi)))
    theta = np.clip(theta, lo, hi)

    m = 1.0 - 1.0 / nvg
    se = (theta - th_r) / (th_s - th_r)
    head = -(1.0 / alpha) * (se ** (-1.0 / m) - 1.0) ** (1.0 / nvg)
    head = np.clip(head, -1.0e3, -1.0e-3)

    if not np.all(np.isfinite(head)):
        raise ValueError("van Genuchten inversion produced non-finite matric "
                         "head; check vGn_alpha / vGn_n in trialParams.nc")

    info.update(source="van_genuchten_inversion", consistent=True,
                theta_min=float(theta.min()), theta_max=float(theta.max()),
                theta_mean=float(theta.mean()),
                matric_head_min_m=float(head.min()),
                matric_head_max_m=float(head.max()),
                matric_head_mean_m=float(head.mean()),
                n_theta_clipped=clipped)
    logger.info(
        f"matric head from vGn inversion ({info['basis']}): theta "
        f"{theta.min():.3f}-{theta.max():.3f}, head {head.min():.2f} to "
        f"{head.max():.2f} m (was a flat {INIT_MATRIC_HEAD} m)")
    if clipped:
        logger.warning(f"{clipped} HRU(s) had theta outside "
                       f"(theta_r, theta_s) and were clipped into range")
    return theta, head, info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    """Override the module-level configuration from the command line.

    EVERY name assigned here must appear in the `global` statement below.
    Without it Python makes them function locals and the assignment silently
    evaporates on return -- in particular derive_matric_head() would keep
    seeing TRIAL_PARAMS_NC = None / MATRIC_HEAD_EXPLICIT = False and always
    take the constant-head fallback, i.e. --trial_params_nc,
    --init_moisture_from and --init_matric_head would be accepted and then
    ignored, re-opening dt_034.
    """
    global ATTRIBUTES_NC, OUTPUT_NC, N_SOIL_LAYERS, SOIL_LAYER_DEPTHS
    global INIT_SOIL_TEMP, INIT_SOIL_MOISTURE
    global TRIAL_PARAMS_NC, INIT_MOISTURE_FROM
    global INIT_MATRIC_HEAD, MATRIC_HEAD_EXPLICIT

    import argparse
    parser = argparse.ArgumentParser(description="Create SUMMA initial conditions")
    parser.add_argument("--attributes_nc", required=True)
    parser.add_argument("--output_nc", required=True)
    parser.add_argument("--n_soil_layers", type=int, default=8)
    parser.add_argument("--soil_depths", type=str, default="0.025,0.075,0.15,0.25,0.50,0.50,1.0,1.5")
    parser.add_argument("--init_temp", type=float, default=283.16)
    parser.add_argument("--init_moisture", type=float, default=0.30)
    parser.add_argument(
        "--trial_params_nc", default=None,
        help="trialParams.nc from s4. REQUIRED for a self-consistent cold "
             "start: the matric head is inverted from --init_moisture through "
             "the van Genuchten curve using this file's per-HRU vGn_alpha / "
             "vGn_n / theta_sat / theta_res. Without it the tool falls back to "
             "a constant head that CONTRADICTS --init_moisture (dt_034).")
    parser.add_argument(
        "--init_moisture_from", choices=["value", "field_capacity"],
        default="value",
        help="'value' uses --init_moisture everywhere; 'field_capacity' uses "
             "each HRU's own fieldCapacity from --trial_params_nc, which is "
             "the near-equilibrium start for a humid/monsoon basin and cuts "
             "years off the soil-moisture spinup.")
    parser.add_argument(
        "--init_matric_head", type=float, default=None,
        help="Explicit constant matric head (m, negative). Overrides the "
             "van Genuchten inversion. Use only if you know why.")
    args = parser.parse_args()
    ATTRIBUTES_NC = args.attributes_nc
    OUTPUT_NC = args.output_nc
    N_SOIL_LAYERS = args.n_soil_layers
    SOIL_LAYER_DEPTHS = [float(x) for x in args.soil_depths.split(',')]
    INIT_SOIL_TEMP = args.init_temp
    INIT_SOIL_MOISTURE = args.init_moisture
    TRIAL_PARAMS_NC = args.trial_params_nc
    INIT_MOISTURE_FROM = args.init_moisture_from
    if args.init_matric_head is not None:
        INIT_MATRIC_HEAD = args.init_matric_head
        MATRIC_HEAD_EXPLICIT = True


if len(sys.argv) > 1:
    parse_args()


def validate_inputs():
    errors = []
    if not ATTRIBUTES_NC or not Path(ATTRIBUTES_NC).exists():
        errors.append(f"Attributes NC not found: {ATTRIBUTES_NC}")
    if not OUTPUT_NC:
        errors.append("OUTPUT_NC is not set")
    if len(SOIL_LAYER_DEPTHS) != N_SOIL_LAYERS:
        errors.append(f"SOIL_LAYER_DEPTHS has {len(SOIL_LAYER_DEPTHS)} entries "
                      f"but N_SOIL_LAYERS={N_SOIL_LAYERS}")
    if INIT_SOIL_TEMP < 200 or INIT_SOIL_TEMP > 320:
        errors.append(f"INIT_SOIL_TEMP={INIT_SOIL_TEMP} K is unrealistic")
    if INIT_SOIL_MOISTURE < 0 or INIT_SOIL_MOISTURE > 0.6:
        errors.append(f"INIT_SOIL_MOISTURE={INIT_SOIL_MOISTURE} is out of range [0, 0.6]")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"Output not created: {output_path}")
    else:
        try:
            from netCDF4 import Dataset
            ds = Dataset(output_path, 'r')
            required = ['nSoil', 'nSnow', 'mLayerTemp', 'mLayerVolFracLiq',
                         'mLayerVolFracIce', 'mLayerMatricHead', 'dt_init']
            for var in required:
                if var not in ds.variables:
                    errors.append(f"Missing variable: {var}")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot read output: {e}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Create cold-start initial conditions."""
    from netCDF4 import Dataset

    os.makedirs(os.path.dirname(OUTPUT_NC) or '.', exist_ok=True)

    # Read attributes
    attr_ds = Dataset(ATTRIBUTES_NC, 'r')
    hru_ids = attr_ds.variables['hruId'][:]
    n_hru = len(hru_ids)
    attr_ds.close()

    n_snow = 0  # cold start: no snow layers
    n_soil = N_SOIL_LAYERS
    n_toto = n_snow + n_soil  # total layers (snow + soil)

    # Create NetCDF
    ds = Dataset(OUTPUT_NC, 'w', format='NETCDF4')

    # Dimensions
    ds.createDimension('hru', n_hru)
    ds.createDimension('scalarv', 1)
    ds.createDimension('midSoil', n_soil)
    ds.createDimension('midToto', n_toto)
    ds.createDimension('ifcSoil', n_soil + 1)
    ds.createDimension('ifcToto', n_toto + 1)
    ds.createDimension('spectral', 2)

    # Scalar state variables (scalarv, hru)
    def scalar_var(name, value, units='', long_name=''):
        v = ds.createVariable(name, 'f8', ('scalarv', 'hru'))
        v[:] = np.full((1, n_hru), value)
        if units:
            v.units = units
        if long_name:
            v.long_name = long_name
        return v

    scalar_var('dt_init', 360.0, 's', 'Length of initial time step')  # Reynolds uses 360s
    scalar_var('scalarCanopyIce', 0.0, 'kg m-2', 'Mass of ice on vegetation canopy')
    scalar_var('scalarCanopyLiq', INIT_CANOPY_LIQ, 'kg m-2', 'Mass of liquid water on vegetation canopy')
    scalar_var('scalarCanairTemp', INIT_SOIL_TEMP - 2.5, 'K', 'Temperature of canopy air space')  # slightly cooler than soil
    scalar_var('scalarCanopyTemp', INIT_SOIL_TEMP + 1.5, 'K', 'Temperature of vegetation canopy')  # slightly warmer
    scalar_var('scalarSnowAlbedo', 0.82, '-', 'Snow albedo for the entire spectral band')
    scalar_var('scalarSnowDepth', 0.0, 'm', 'Total snow depth')
    scalar_var('scalarSWE', 0.0, 'kg m-2', 'Snow water equivalent')
    scalar_var('scalarSfcMeltPond', 0.0, 'kg m-2', 'Ponded water caused by melt')
    scalar_var('scalarAquiferStorage', 0.0, 'm', 'Relative aquifer storage')

    # Integer scalars
    nsoil_var = ds.createVariable('nSoil', 'i4', ('scalarv', 'hru'))
    nsoil_var[:] = np.full((1, n_hru), n_soil, dtype=np.int32)

    nsnow_var = ds.createVariable('nSnow', 'i4', ('scalarv', 'hru'))
    nsnow_var[:] = np.full((1, n_hru), 0, dtype=np.int32)

    # Layer variables -- midToto dimension (soil only for cold start)
    # Layer depth
    depth_var = ds.createVariable('mLayerDepth', 'f8', ('midToto', 'hru'))
    depth_var.units = 'm'
    for i in range(n_soil):
        depth_var[i, :] = SOIL_LAYER_DEPTHS[i]

    # Layer temperature
    temp_var = ds.createVariable('mLayerTemp', 'f8', ('midToto', 'hru'))
    temp_var.units = 'K'
    for i in range(n_soil):
        # Slight gradient: surface warmer, deep cooler (or constant)
        temp_var[i, :] = INIT_SOIL_TEMP

    # Volumetric liquid fraction and matric head MUST describe the same soil
    # state -- see derive_matric_head (dt_034).
    theta_hru, head_hru, head_info = derive_matric_head(n_hru)

    liq_var = ds.createVariable('mLayerVolFracLiq', 'f8', ('midToto', 'hru'))
    liq_var.units = '-'
    for i in range(n_soil):
        liq_var[i, :] = theta_hru

    # Volumetric ice fraction
    ice_var = ds.createVariable('mLayerVolFracIce', 'f8', ('midToto', 'hru'))
    ice_var.units = '-'
    for i in range(n_soil):
        ice_var[i, :] = 0.0

    # Matric head (midSoil dimension)
    head_var = ds.createVariable('mLayerMatricHead', 'f8', ('midSoil', 'hru'))
    head_var.units = 'm'
    for i in range(n_soil):
        head_var[i, :] = head_hru

    # Interface heights (ifcToto)
    ifch_var = ds.createVariable('iLayerHeight', 'f8', ('ifcToto', 'hru'))
    ifch_var.units = 'm'
    cumulative = 0.0
    for i in range(n_toto + 1):
        if i == 0:
            ifch_var[i, :] = 0.0
        else:
            cumulative += SOIL_LAYER_DEPTHS[i - 1]
            ifch_var[i, :] = cumulative

    # Spectral band albedo
    spec_var = ds.createVariable('spectralSnowAlbedoDiffuse', 'f8', ('spectral', 'hru'))
    spec_var[:] = np.array([[0.95], [0.65]]) * np.ones((1, n_hru))

    ds.history = "Cold start initial conditions created by create_initial_conditions.py"
    ds.close()

    logger.info(f"Initial conditions written: {OUTPUT_NC}")
    logger.info(f"  {n_hru} HRUs, {n_soil} soil layers, 0 snow layers (cold start)")
    logger.info(f"  Init temp: {INIT_SOIL_TEMP} K, Init moisture: {INIT_SOIL_MOISTURE}")

    print(json.dumps({
        "status": "success",
        "n_hru": n_hru,
        "n_soil_layers": n_soil,
        "init_temp_K": INIT_SOIL_TEMP,
        "init_moisture": INIT_SOIL_MOISTURE,
        "initial_soil_state": head_info,
        "output": OUTPUT_NC
    }))

    return OUTPUT_NC


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
