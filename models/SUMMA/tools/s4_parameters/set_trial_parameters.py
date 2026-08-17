#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      set_trial_parameters
Stage:        s4_parameters
Description:  Generate SUMMA trial parameters NetCDF file.

TWO MODES:
  --from_hwsd     (RECOMMENDED) Automatically derive all soil parameters from
                  HWSD global soil database using ROSETTA van Genuchten lookup.
                  Also sets canopy heights from VEGPARM.TBL per vegTypeIndex.
                  All parameters are self-consistent from one framework.

  --parameters    Manual mode: provide a JSON dict of parameter overrides.
                  WARNING: if you override ANY soil parameter, you must override
                  ALL of them (SUMMA requirement). Use --from_hwsd instead.

Soil parameter estimation pipeline (--from_hwsd):
  1. HWSD raster → sand/clay/OC% per grid cell → USDA texture class
  2. Texture class → ROSETTA van Genuchten table (Schaap 2001):
     theta_res, theta_sat, alpha, n, Ksat (5 core params, self-consistent)
  3. Van Genuchten curve at standard pressure heads:
     fieldCapacity = theta(psi=-3.36m)    (= -33 kPa)
     critSoilWilting = theta(psi=-152.9m) (= -1500 kPa)
     critSoilTranspire = midpoint(WP, FC)
  4. Canopy heights from VEGPARM.TBL ZTOPV/ZBOTV per vegTypeIndex

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ROSETTA van Genuchten parameters (from SOILPARM.TBL, Schaap et al. 2001)
# ---------------------------------------------------------------------------
ROSETTA_VGN = {
    'sand':            {'theta_res': 0.068, 'theta_sat': 0.395, 'alpha': -3.524, 'n': 3.177, 'ksat': 1.76e-4},
    'loamy sand':      {'theta_res': 0.075, 'theta_sat': 0.410, 'alpha': -3.475, 'n': 1.746, 'ksat': 1.56e-4},
    'sandy loam':      {'theta_res': 0.114, 'theta_sat': 0.435, 'alpha': -2.667, 'n': 1.449, 'ksat': 3.47e-5},
    'silt loam':       {'theta_res': 0.179, 'theta_sat': 0.485, 'alpha': -0.506, 'n': 1.663, 'ksat': 7.20e-6},
    'silt':            {'theta_res': 0.179, 'theta_sat': 0.485, 'alpha': -0.658, 'n': 1.679, 'ksat': 7.20e-6},
    'loam':            {'theta_res': 0.155, 'theta_sat': 0.451, 'alpha': -1.112, 'n': 1.472, 'ksat': 6.95e-6},
    'sandy clay loam': {'theta_res': 0.175, 'theta_sat': 0.420, 'alpha': -2.109, 'n': 1.330, 'ksat': 6.30e-6},
    'silty clay loam': {'theta_res': 0.218, 'theta_sat': 0.477, 'alpha': -0.839, 'n': 1.521, 'ksat': 1.70e-6},
    'clay loam':       {'theta_res': 0.250, 'theta_sat': 0.476, 'alpha': -1.581, 'n': 1.416, 'ksat': 2.45e-6},
    'sandy clay':      {'theta_res': 0.219, 'theta_sat': 0.426, 'alpha': -3.342, 'n': 1.208, 'ksat': 2.17e-6},
    'silty clay':      {'theta_res': 0.283, 'theta_sat': 0.492, 'alpha': -1.622, 'n': 1.321, 'ksat': 1.03e-6},
    'clay':            {'theta_res': 0.286, 'theta_sat': 0.482, 'alpha': -1.496, 'n': 1.253, 'ksat': 1.28e-6},
}
# Add underscore variants (HWSD returns e.g. 'silt_loam')
for _k in list(ROSETTA_VGN.keys()):
    ROSETTA_VGN[_k.replace(' ', '_')] = ROSETTA_VGN[_k]

# VEGPARM.TBL canopy heights (USGS 27-class)
ZTOPV = {1:0, 2:0.5, 3:0.5, 4:0.5, 5:0.5, 6:0.5, 7:0.5, 8:0.5, 9:0.5, 10:5.0,
         11:20.0, 12:14.0, 13:35.0, 14:17.0, 15:18.0, 16:0, 17:0.5, 18:20.0, 19:0.02}
ZBOTV = {k: min(v * 0.3, v - 0.01) if v > 0.01 else 0.01 for k, v in ZTOPV.items()}

DEFAULT_MPTABLE = "KISSPATH_BINARIES/summa/case_study/base_settings/MPTABLE.TBL"


def read_mptable_hvt_hvb(mptable_path, scheme):
    """HVT/HVB vectors from MPTABLE.TBL for the chosen Noah-MP table.

    HVT/HVB live in the &noah_mp_<scheme>_parameters namelist, NOT in
    &noah_mp_<scheme>_veg_categories -- which carries only NVEG/ISWATER and which
    the shipped file repeats TWICE for modis. A parser keyed on veg_categories
    finds zero HVT rows and silently falls back. Asserts NVEG-many values.
    """
    import re
    want = f"&noah_mp_{scheme}_parameters"
    with open(mptable_path) as fh:
        lines = fh.read().splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().lower() == want:
            start = i
            break
    if start is None:
        raise RuntimeError(f"{mptable_path} has no {want} section")
    body = []
    for ln in lines[start + 1:]:
        if ln.strip() == "/":
            break
        body.append(ln)

    def row(key):
        pat = re.compile(r"^\s*" + key + r"\s*=", re.I)
        for ln in body:
            if pat.match(ln):
                rhs = ln.split("=", 1)[1].split("!")[0]
                vals = [float(x) for x in rhs.replace(",", " ").split()]
                if not vals:
                    raise RuntimeError(f"{key} row in {want} parsed to zero values")
                return vals
        raise RuntimeError(f"{key} not found in {want} of {mptable_path}")

    hvt, hvb = row("HVT"), row("HVB")
    if len(hvt) != len(hvb):
        raise RuntimeError(f"{want}: HVT has {len(hvt)} values but HVB has {len(hvb)}")
    expect = {"usgs": 27, "modis": 20}[scheme]
    if len(hvt) != expect:
        raise RuntimeError(f"{want}: expected NVEG={expect} HVT values, read {len(hvt)}")
    return hvt, hvb


def canopy_heights(veg, scheme, mptable_path):
    """Per-HRU (heightCanopyTop, heightCanopyBottom, provenance).

    SUMMA reads these from trialParams.nc (popMetadat.f90:212) and NEVER consults
    MPTABLE for them; the localParamInfo default is a 20 m forest on EVERY HRU.
    paramCheck requires top > bot STRICTLY, while MPTABLE gives HVT=HVB=0.0 for
    water/urban/barren/ice -- hence the floor and the clamp.
    """
    if scheme:
        hvt, hvb = read_mptable_hvt_hvb(mptable_path, scheme)
        nveg = len(hvt)
        top, bot = [], []
        for v in veg:
            iv = int(v)
            if not (1 <= iv <= nveg):
                raise RuntimeError(
                    f"vegTypeIndex {iv} outside 1..{nveg} for --veg_scheme {scheme}; the attributes "
                    f"file and the table disagree (SKILL.md 2c: vegeParTbl MUST match --veg_scheme)")
            tt, bb = hvt[iv - 1], hvb[iv - 1]
            if tt <= 0.0:
                tt, bb = 0.05, 0.01
            bb = min(max(bb, 0.01), 0.5 * tt)
            top.append(tt)
            bot.append(bb)
        top, bot = np.array(top), np.array(bot)
        prov = f"MPTABLE.TBL &noah_mp_{scheme}_parameters HVT/HVB"
    else:
        top = np.array([ZTOPV.get(int(v), 0.5) for v in veg])
        bot = np.array([max(ZBOTV.get(int(v), 0.01), 0.01) for v in veg])
        prov = "hard-coded USGS-27 VEGPARM dict (ASSUMPTION; pass --veg_scheme)"
        logger.warning("heightCanopyTop from a hard-coded USGS-27 dict. If vegTypeIndex is MODIS-numbered "
                       "this mis-maps every class. Pass --veg_scheme to read MPTABLE HVT/HVB.")
    if not (top > bot).all():
        raise RuntimeError("heightCanopyTop <= heightCanopyBottom on some HRU; SUMMA paramCheck would abort")
    return top, bot, prov


def vgn_theta(psi, alpha, theta_res, theta_sat, n):
    """Van Genuchten water content at matric head psi (m, negative)."""
    m = 1.0 - 1.0 / n
    if psi < 0:
        return theta_res + (theta_sat - theta_res) * (1.0 + (alpha * psi) ** n) ** (-m)
    return theta_sat


def rosetta_to_summa(texture):
    """Derive ALL SUMMA soil parameters from ROSETTA texture class.

    Returns dict with: k_soil, theta_sat, theta_res, vGn_alpha, vGn_n,
    fieldCapacity, critSoilWilting, critSoilTranspire, theta_mp, soil_dens_intr.
    All self-consistent from one van Genuchten parameterization.
    """
    r = ROSETTA_VGN.get(texture.lower(), ROSETTA_VGN.get(texture.lower().replace('_', ' '),
                        ROSETTA_VGN['loam']))

    alpha, n = r['alpha'], r['n']
    theta_res, theta_sat = r['theta_res'], r['theta_sat']

    # Derive FC and WP from vGn curve at standard pressure heads
    fc = vgn_theta(-3.36, alpha, theta_res, theta_sat, n)     # -33 kPa
    wp = vgn_theta(-152.9, alpha, theta_res, theta_sat, n)    # -1500 kPa
    transpire = (wp + fc) / 2.0

    return {
        'k_soil': r['ksat'],
        'theta_sat': theta_sat,
        'theta_res': theta_res,
        'vGn_alpha': alpha,
        'vGn_n': n,
        'fieldCapacity': fc,
        'critSoilWilting': wp,
        'critSoilTranspire': transpire,
        'theta_mp': fc,
        'soil_dens_intr': 2700.0,
    }


def generate_from_hwsd(attributes_nc, output_nc, veg_scheme=None, mptable_path=DEFAULT_MPTABLE):
    """Auto-generate all SUMMA trial parameters from HWSD + VEGPARM.TBL."""
    from netCDF4 import Dataset

    sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
    from ki_tools_common.soil_utils import lookup_hwsd

    attr = Dataset(attributes_nc, 'r')
    hru_ids = attr.variables['hruId'][:]
    lats = attr.variables['latitude'][:]
    lons = attr.variables['longitude'][:]
    # SUMMA attributes commonly store longitude in 0-360 convention, but
    # ki_tools_common.soil_utils.lookup_hwsd expects -180..180. Normalize so the
    # HWSD raster lookup does not silently fail (index-out-of-bounds) and fall
    # back to default loam. (KI fix 2026-06-29: from_hwsd lon-convention bug.)
    lons = np.where(np.asarray(lons) > 180.0, np.asarray(lons) - 360.0, lons)
    veg = attr.variables['vegTypeIndex'][:]
    n_hru = len(hru_ids)
    attr.close()

    # Per-HRU soil from HWSD → ROSETTA
    soil_keys = list(rosetta_to_summa('loam').keys())
    soil_params = {k: np.zeros(n_hru) for k in soil_keys}

    textures = []
    for i in range(n_hru):
        try:
            hwsd = lookup_hwsd(float(lats[i]), float(lons[i]))
            tex = hwsd['texture']
            sp = rosetta_to_summa(tex)
        except Exception:
            tex = 'loam'
            sp = rosetta_to_summa('loam')
        textures.append(tex)
        for k in soil_keys:
            soil_params[k][i] = sp[k]

    # Canopy heights: MPTABLE HVT/HVB when --veg_scheme is given, else the legacy dict.
    htop, hbot, canopy_source = canopy_heights(veg, veg_scheme, mptable_path)

    # Write NetCDF
    os.makedirs(os.path.dirname(output_nc) or '.', exist_ok=True)
    ds = Dataset(output_nc, 'w', format='NETCDF4')
    ds.createDimension('hru', n_hru)
    hv = ds.createVariable('hruId', 'i8', ('hru',))
    hv[:] = hru_ids

    all_params = {
        **soil_params,
        'heightCanopyTop': htop,
        'heightCanopyBottom': hbot,
        'rootingDepth': np.full(n_hru, 1.0),
        'aquiferScaleFactor': np.full(n_hru, 0.35),
        'aquiferBaseflowExp': np.full(n_hru, 2.0),
        'aquiferBaseflowRate': np.full(n_hru, 2.0),
        'qSurfScale': np.full(n_hru, 50.0),
    }

    for pname, vals in all_params.items():
        v = ds.createVariable(pname, 'f8', ('hru',))
        v[:] = vals

    ds.history = "Created by set_trial_parameters.py --from_hwsd (ROSETTA van Genuchten)"
    ds.close()

    # Summary
    from collections import Counter
    tex_counts = Counter(textures)
    logger.info(f"Trial parameters from HWSD+ROSETTA: {output_nc}")
    logger.info(f"  {n_hru} HRUs, textures: {dict(tex_counts.most_common(5))}")
    logger.info(f"  k_soil: [{soil_params['k_soil'].min():.2e}, {soil_params['k_soil'].max():.2e}]")
    logger.info(f"  vGn_alpha: [{soil_params['vGn_alpha'].min():.2f}, {soil_params['vGn_alpha'].max():.2f}]")

    print(json.dumps({
        "status": "success",
        "mode": "from_hwsd",
        "n_hru": n_hru,
        "n_parameters": len(all_params),
        "textures": dict(tex_counts.most_common(5)),
        "veg_scheme": veg_scheme or "unspecified",
        "canopy_source": canopy_source,
        "heightCanopyTop_range": [float(htop.min()), float(htop.max())],
        "output": output_nc,
    }))
    return output_nc


def append_basin_parameters(attributes_nc, output_nc, basin_parameters):
    """Append GRU-dimension basin parameters to an existing trialParams NetCDF.

    SUMMA reads basin (GRU-level) parameters -- routingGammaShape,
    routingGammaScale, basin__aquiferHydCond, ... -- from the trialParams file
    on the 'gru' dimension, NOT 'hru'. Writing them on 'hru' makes SUMMA fall
    back to basinParamInfo.txt defaults SILENTLY, so the sub-grid gamma
    time-delay routing is unreachable and the caller never learns why.

    (KI fix, re-restored 2026-07-10: this function was present for the
    real_case run and was subsequently reverted off disk.)
    """
    from netCDF4 import Dataset

    attr = Dataset(attributes_nc, 'r')
    if 'gruId' not in attr.variables:
        attr.close()
        logger.error("attributes.nc has no gruId variable; cannot write basin params")
        sys.exit(1)
    gru_ids = np.asarray(attr.variables['gruId'][:])
    attr.close()
    n_gru = len(gru_ids)

    ds = Dataset(output_nc, 'a')
    if 'gru' not in ds.dimensions:
        ds.createDimension('gru', n_gru)
    elif len(ds.dimensions['gru']) != n_gru:
        ds.close()
        logger.error("gru dimension mismatch")
        sys.exit(2)
    if 'gruId' not in ds.variables:
        gv = ds.createVariable('gruId', 'i8', ('gru',))
        gv[:] = gru_ids.astype('int64')

    written = []
    for pname, pval in basin_parameters.items():
        if isinstance(pval, list):
            vals = np.array(pval, dtype=np.float64)
            if vals.size != n_gru:
                ds.close()
                logger.error(f"{pname}: {vals.size} values for {n_gru} GRUs")
                sys.exit(1)
        else:
            vals = np.full(n_gru, float(pval), dtype=np.float64)
        if pname in ds.variables:
            ds.variables[pname][:] = vals
        else:
            v = ds.createVariable(pname, 'f8', ('gru',))
            v[:] = vals
        written.append(pname)

    ds.close()
    logger.info(f"Basin (GRU-dim) parameters written: {written} over {n_gru} GRUs")
    return written


def generate_manual(attributes_nc, output_nc, parameters):
    """Write user-provided parameters to trialParams NetCDF."""
    from netCDF4 import Dataset

    os.makedirs(os.path.dirname(output_nc) or '.', exist_ok=True)
    attr_ds = Dataset(attributes_nc, 'r')
    hru_ids = attr_ds.variables['hruId'][:]
    n_hru = len(hru_ids)
    attr_ds.close()

    ds = Dataset(output_nc, 'w', format='NETCDF4')
    ds.createDimension('hru', n_hru)
    hru_var = ds.createVariable('hruId', 'i8', ('hru',))
    hru_var[:] = hru_ids

    for param_name, param_value in parameters.items():
        if isinstance(param_value, list):
            values = np.array(param_value, dtype=np.float64)
        else:
            values = np.full(n_hru, float(param_value), dtype=np.float64)
        var = ds.createVariable(param_name, 'f8', ('hru',))
        var[:] = values

    ds.history = "Created by set_trial_parameters.py --parameters (manual)"
    ds.close()

    logger.info(f"Trial parameters (manual): {output_nc} ({len(parameters)} params, {n_hru} HRUs)")
    print(json.dumps({
        "status": "success",
        "mode": "manual",
        "n_parameters": len(parameters),
        "n_hru": n_hru,
        "parameters": list(parameters.keys()),
        "output": output_nc,
    }))
    return output_nc


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Set SUMMA trial parameters")
    parser.add_argument("--attributes_nc", required=True)
    parser.add_argument("--output_nc", required=True)
    parser.add_argument("--from_hwsd", action="store_true",
                        help="(RECOMMENDED) Auto-derive soil params from HWSD+ROSETTA")
    parser.add_argument("--parameters", type=str, default="{}",
                        help="JSON string of parameter overrides (manual mode)")
    parser.add_argument("--veg_scheme", choices=("usgs", "modis"), default=None,
                        help="Read heightCanopyTop/Bottom from MPTABLE.TBL HVT/HVB for this table. MUST equal "
                             "the vegeParTbl decision AND build_river_network.py --veg_scheme (SKILL.md 2c).")
    parser.add_argument("--mptable", default=DEFAULT_MPTABLE, help="Path to MPTABLE.TBL")
    parser.add_argument("--basin_parameters", type=str, default="{}",
                        help="JSON string of GRU-dimension basin parameters, e.g. "
                             "'{\"routingGammaShape\": 2.5, \"routingGammaScale\": 604800}'. "
                             "Required to reach SUMMA's sub-grid gamma time-delay routing.")
    args = parser.parse_args()
    if args.veg_scheme and not args.from_hwsd:
        parser.error("--veg_scheme applies to --from_hwsd mode only (it drives heightCanopyTop/Bottom)")

    logger.info(f"Running tool: {os.path.basename(__file__)}")

    basin_parameters = json.loads(args.basin_parameters)

    if args.from_hwsd:
        output = generate_from_hwsd(args.attributes_nc, args.output_nc,
                                    veg_scheme=args.veg_scheme, mptable_path=args.mptable)
    elif args.parameters != "{}":
        output = generate_manual(args.attributes_nc, args.output_nc, json.loads(args.parameters))
    elif basin_parameters:
        logger.error("--basin_parameters needs --from_hwsd or --parameters to seed the HRU params")
        sys.exit(1)
    else:
        logger.error("Specify --from_hwsd (recommended) or --parameters '{...}'")
        sys.exit(1)

    if not Path(output).exists():
        logger.error(f"Output not created: {output}")
        sys.exit(3)

    if basin_parameters:
        append_basin_parameters(args.attributes_nc, output, basin_parameters)

    sys.exit(0)
