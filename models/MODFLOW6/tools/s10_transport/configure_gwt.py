#!/usr/bin/env python3
"""
configure_gwt.py -- Set up a GWT (Groundwater Transport) model coupled to an
existing GWF model.

Part of MODFLOW 6 Knowledge Infrastructure, Stage S10 (Transport).
KDT v5.0 approach.

Usage modes:
  1. COUPLED mode (recommended): GWF and GWT run in the same simulation.
     The GWF-GWT Exchange passes flows from GWF to GWT automatically.
  2. STANDALONE mode: GWT runs in a separate simulation, reading
     previously saved GWF head and budget files via the FMI package.

Required packages for a basic GWT model:
  - DIS  (same grid as GWF -- shared discretization)
  - IC   (initial concentration, typically 0.0)
  - ADV  (advection -- UPSTREAM, CENTRAL, or TVD scheme)
  - DSP  (dispersion -- longitudinal/transverse dispersivity, diffusion)
  - MST  (mobile storage and transfer -- porosity, sorption, decay)
  - SSM  (source/sink mixing -- assigns concentrations to GWF stress packages)
  - OC   (output control -- save concentration, budget)

Optional packages:
  - CNC  (constant concentration boundary)
  - SRC  (mass source loading)
  - IST  (immobile storage and transfer -- dual-domain)
  - FMI  (flow model interface -- only for standalone mode)

References:
  - mf6io.pdf pp. 169-226 (GWT Model Input)
  - MODFLOW 6.6.1 examples: ex-gwt-mt3dms-p01a (coupled), ex-gwt-mt3dms-p02a (standalone)
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import numpy as np

try:
    import flopy
except ImportError:
    print("ERROR: FloPy is required. Install with: pip install flopy")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Contaminant presets -- documentation-derived parameter values
# ---------------------------------------------------------------------------
CONTAMINANT_PRESETS = {
    "conservative": {
        "description": "Conservative tracer (no sorption, no decay)",
        "porosity": 0.25,
        "longitudinal_dispersivity": 10.0,    # m (scale-dependent, see Gelhar 1992)
        "transverse_dispersivity": 1.0,       # m (typically ALH/10)
        "vertical_dispersivity": 0.1,         # m (typically ALH/100)
        "diffusion_coefficient": 1.0e-9,      # m2/s -> converted to m2/day
        "sorption": None,
        "decay": None,
        "bulk_density": None,
        "distcoef": None,
    },
    "nitrate": {
        "description": "Nitrate (NO3-) -- weakly sorbing, first-order denitrification",
        "porosity": 0.30,
        "longitudinal_dispersivity": 10.0,
        "transverse_dispersivity": 1.0,
        "vertical_dispersivity": 0.1,
        "diffusion_coefficient": 1.9e-9,      # m2/s at 25C (Li & Gregory, 1974)
        "sorption": "LINEAR",
        "decay": "first_order",
        "decay_rate": 0.001,                   # 1/day (Rivett et al., 2008 range: 0.0001-0.01)
        "bulk_density": 1.7,                   # g/cm3 = kg/L (typical aquifer)
        "distcoef": 0.0001,                    # L/kg (very weak sorption for NO3-)
    },
    "chloride": {
        "description": "Chloride (Cl-) -- conservative, no sorption, no decay",
        "porosity": 0.25,
        "longitudinal_dispersivity": 10.0,
        "transverse_dispersivity": 1.0,
        "vertical_dispersivity": 0.1,
        "diffusion_coefficient": 2.03e-9,      # m2/s at 25C
        "sorption": None,
        "decay": None,
        "bulk_density": None,
        "distcoef": None,
    },
    "ammonium": {
        "description": "Ammonium (NH4+) -- moderate sorption, nitrification decay",
        "porosity": 0.30,
        "longitudinal_dispersivity": 10.0,
        "transverse_dispersivity": 1.0,
        "vertical_dispersivity": 0.1,
        "diffusion_coefficient": 1.98e-9,
        "sorption": "LINEAR",
        "decay": "first_order",
        "decay_rate": 0.005,                   # 1/day (nitrification)
        "bulk_density": 1.7,
        "distcoef": 0.003,                     # L/kg (moderate cation exchange)
    },
    "phosphate": {
        "description": "Phosphate (PO4) -- strong sorption, negligible decay",
        "porosity": 0.30,
        "longitudinal_dispersivity": 10.0,
        "transverse_dispersivity": 1.0,
        "vertical_dispersivity": 0.1,
        "diffusion_coefficient": 0.89e-9,
        "sorption": "LINEAR",
        "decay": None,
        "bulk_density": 1.7,
        "distcoef": 0.1,                       # L/kg (strong sorption)
    },
    "generic_solute": {
        "description": "Generic solute with moderate dispersion",
        "porosity": 0.25,
        "longitudinal_dispersivity": 10.0,
        "transverse_dispersivity": 1.0,
        "vertical_dispersivity": 0.1,
        "diffusion_coefficient": 1.0e-9,
        "sorption": None,
        "decay": None,
        "bulk_density": None,
        "distcoef": None,
    },
}


def _diffusion_m2_per_day(d_m2_per_s):
    """Convert molecular diffusion from m2/s to m2/day."""
    return d_m2_per_s * 86400.0


def build_coupled_gwt(
    gwf_sim_ws,
    gwt_model_name="gwt",
    gwf_model_name=None,
    contaminant="conservative",
    initial_concentration=0.0,
    source_concentration=None,
    source_cells=None,
    advection_scheme="UPSTREAM",
    porosity=None,
    longitudinal_dispersivity=None,
    transverse_dispersivity=None,
    vertical_dispersivity=None,
    diffusion_coefficient=None,
    sorption=None,
    decay=None,
    decay_rate=None,
    bulk_density=None,
    distcoef=None,
    output_ws=None,
    mf6_exe=None,
    run_model=True,
):
    """
    Build a GWT model coupled to an existing GWF model in the same simulation.

    This is the RECOMMENDED approach: GWF and GWT share the same simulation
    and TDIS. The GWF-GWT Exchange automatically passes flow information.

    Parameters
    ----------
    gwf_sim_ws : str
        Path to the directory containing the existing GWF simulation
        (must contain mfsim.nam and all GWF package files).
    gwt_model_name : str
        Name for the GWT model (default: "gwt").
    gwf_model_name : str or None
        Name of the GWF model. If None, auto-detected from mfsim.nam.
    contaminant : str
        Contaminant preset name. One of: conservative, nitrate, chloride,
        ammonium, phosphate, generic_solute.
    initial_concentration : float
        Initial concentration in all cells (default: 0.0).
    source_concentration : float or None
        Concentration of source (used for CNC boundary or SSM aux).
        If None, no constant concentration boundary is created.
    source_cells : list of tuples or None
        List of (layer, row, col) tuples for constant concentration cells.
        0-indexed (FloPy convention).
    advection_scheme : str
        Advection scheme: UPSTREAM (default, most stable), CENTRAL, or TVD
        (most accurate but requires finer grid/timestep).
    porosity : float or None
        Override preset porosity.
    longitudinal_dispersivity : float or None
        Override preset ALH (m).
    transverse_dispersivity : float or None
        Override preset ATH1 (m).
    vertical_dispersivity : float or None
        Override preset ATV (m).
    diffusion_coefficient : float or None
        Override preset molecular diffusion (m2/s, will be converted to m2/day).
    sorption : str or None
        Override preset sorption type: LINEAR, FREUNDLICH, LANGMUIR, or None.
    decay : str or None
        Override: "first_order" or "zero_order" or None.
    decay_rate : float or None
        Override: decay rate constant (1/day for first-order, mass/L3/day for zero-order).
    bulk_density : float or None
        Override: bulk density (kg/L or g/cm3).
    distcoef : float or None
        Override: distribution coefficient (L/kg for LINEAR sorption).
    output_ws : str or None
        Output workspace directory. If None, creates a subdirectory in gwf_sim_ws.
    mf6_exe : str or None
        Path to mf6 binary. If None, uses default system location.
    run_model : bool
        Whether to run the simulation after building (default: True).

    Returns
    -------
    dict
        Dictionary with keys:
        - "sim_ws": simulation workspace path
        - "gwt_model_name": GWT model name
        - "gwf_model_name": GWF model name
        - "concentration_file": path to .ucn output file
        - "budget_file": path to .cbc output file
        - "listing_file": path to .lst file
        - "success": bool
        - "contaminant": contaminant preset used
        - "parameters": dict of transport parameters used
    """
    # --- Validate inputs ---
    if contaminant not in CONTAMINANT_PRESETS:
        raise ValueError(
            f"Unknown contaminant '{contaminant}'. "
            f"Choose from: {list(CONTAMINANT_PRESETS.keys())}"
        )

    preset = CONTAMINANT_PRESETS[contaminant]

    # Apply overrides (user params take precedence over preset)
    _porosity = porosity if porosity is not None else preset["porosity"]
    _alh = longitudinal_dispersivity if longitudinal_dispersivity is not None else preset["longitudinal_dispersivity"]
    _ath1 = transverse_dispersivity if transverse_dispersivity is not None else preset["transverse_dispersivity"]
    _atv = vertical_dispersivity if vertical_dispersivity is not None else preset["vertical_dispersivity"]
    _diffc_m2s = diffusion_coefficient if diffusion_coefficient is not None else preset["diffusion_coefficient"]
    _diffc = _diffusion_m2_per_day(_diffc_m2s)
    _sorption = sorption if sorption is not None else preset.get("sorption")
    _decay = decay if decay is not None else preset.get("decay")
    _decay_rate = decay_rate if decay_rate is not None else preset.get("decay_rate")
    _bulk_density = bulk_density if bulk_density is not None else preset.get("bulk_density")
    _distcoef = distcoef if distcoef is not None else preset.get("distcoef")

    if mf6_exe is None:
        mf6_exe = "/mnt/disk1/Hydrocraft_server/model/modflow6/mf6.6.1_linux/bin/mf6"

    # --- Load existing GWF simulation ---
    if not os.path.exists(os.path.join(gwf_sim_ws, "mfsim.nam")):
        raise FileNotFoundError(
            f"No mfsim.nam found in {gwf_sim_ws}. "
            "Provide a directory containing a valid MODFLOW 6 simulation."
        )

    sim = flopy.mf6.MFSimulation.load(
        sim_ws=gwf_sim_ws,
        exe_name=mf6_exe,
    )

    # Detect GWF model name
    if gwf_model_name is None:
        model_names = list(sim.model_names)
        gwf_names = [n for n in model_names if n.startswith("gwf") or sim.get_model(n).model_type == "gwf6"]
        if not gwf_names:
            # Take the first model
            gwf_model_name = model_names[0]
        else:
            gwf_model_name = gwf_names[0]

    gwf = sim.get_model(gwf_model_name)
    if gwf is None:
        raise ValueError(f"GWF model '{gwf_model_name}' not found in simulation. Available: {list(sim.model_names)}")

    # --- Set up output workspace ---
    if output_ws is None:
        output_ws = os.path.join(gwf_sim_ws, f"coupled_gwt_{contaminant}")

    if output_ws != gwf_sim_ws:
        os.makedirs(output_ws, exist_ok=True)
        # Copy all GWF files to new workspace
        for fname in os.listdir(gwf_sim_ws):
            src = os.path.join(gwf_sim_ws, fname)
            dst = os.path.join(output_ws, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
        # Reload simulation from new workspace
        sim = flopy.mf6.MFSimulation.load(
            sim_ws=output_ws,
            exe_name=mf6_exe,
        )
        gwf = sim.get_model(gwf_model_name)

    # --- Extract grid info from GWF model ---
    dis = gwf.get_package("DIS")
    nlay = dis.nlay.get_data()
    nrow = dis.nrow.get_data()
    ncol = dis.ncol.get_data()
    delr = dis.delr.get_data()
    delc = dis.delc.get_data()
    top = dis.top.get_data()
    botm = dis.botm.get_data()
    idomain = dis.idomain.get_data() if dis.idomain.get_data() is not None else np.ones((nlay, nrow, ncol), dtype=int)

    # Ensure GWF saves flows (required for GWT coupling)
    gwf.name_file.save_flows = True

    # Also ensure GWF OC saves budget
    oc_gwf = gwf.get_package("OC")
    if oc_gwf is not None:
        if oc_gwf.budget_filerecord.get_data() is None:
            oc_gwf.budget_filerecord = f"{gwf_model_name}.cbc"
        if oc_gwf.head_filerecord.get_data() is None:
            oc_gwf.head_filerecord = f"{gwf_model_name}.hds"

    # --- Create GWT model ---
    gwt = flopy.mf6.ModflowGwt(
        sim,
        modelname=gwt_model_name,
        save_flows=True,
    )

    # --- DIS: Same grid as GWF ---
    flopy.mf6.ModflowGwtdis(
        gwt,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
        idomain=idomain,
    )

    # --- IC: Initial concentration ---
    flopy.mf6.ModflowGwtic(
        gwt,
        strt=initial_concentration,
    )

    # --- ADV: Advection ---
    flopy.mf6.ModflowGwtadv(
        gwt,
        scheme=advection_scheme,
    )

    # --- DSP: Dispersion ---
    dsp_kwargs = {}
    if _diffc > 0:
        dsp_kwargs["diffc"] = _diffc
    if _alh > 0:
        dsp_kwargs["alh"] = _alh
        dsp_kwargs["ath1"] = _ath1
    if _atv > 0:
        dsp_kwargs["atv"] = _atv

    # Use XT3D_OFF for simpler problems (faster, less memory)
    # For production, consider removing XT3D_OFF for better accuracy
    flopy.mf6.ModflowGwtdsp(
        gwt,
        xt3d_off=True,
        **dsp_kwargs,
    )

    # --- MST: Mobile Storage and Transfer ---
    mst_kwargs = {
        "porosity": _porosity,
    }

    if _sorption is not None and _sorption.upper() in ("LINEAR", "FREUNDLICH", "LANGMUIR"):
        mst_kwargs["sorption"] = _sorption.lower()
        if _bulk_density is not None:
            mst_kwargs["bulk_density"] = _bulk_density
        if _distcoef is not None:
            mst_kwargs["distcoef"] = _distcoef
        # SP2 needed for Freundlich/Langmuir
        if _sorption.upper() in ("FREUNDLICH", "LANGMUIR"):
            sp2_val = preset.get("sp2", 1.0)
            mst_kwargs["sp2"] = sp2_val

    if _decay is not None:
        if _decay == "first_order":
            mst_kwargs["first_order_decay"] = True
        elif _decay == "zero_order":
            mst_kwargs["zero_order_decay"] = True
        if _decay_rate is not None:
            mst_kwargs["decay"] = _decay_rate
            # If sorption is active, also specify decay_sorbed
            if _sorption is not None:
                mst_kwargs["decay_sorbed"] = _decay_rate

    flopy.mf6.ModflowGwtmst(
        gwt,
        **mst_kwargs,
    )

    # --- SSM: Source and Sink Mixing ---
    # Identify which GWF stress packages exist and set up SSM sources
    ssm_sources = []
    gwf_packages = gwf.get_package_list()

    # Standard stress packages that can have SSM concentrations
    ssm_capable = ["CHD", "WEL", "RCH", "RCHA", "DRN", "RIV", "GHB", "EVT", "EVTA"]
    for pkg_type in ssm_capable:
        for pkg_name in gwf_packages:
            pkg = gwf.get_package(pkg_name)
            if pkg is not None and hasattr(pkg, 'package_type'):
                if pkg.package_type.upper().replace("6", "") in (pkg_type.lower(),):
                    # Check if this package has a CONCENTRATION auxiliary
                    # If not, we don't add it to SSM sources (default 0 conc applies)
                    pass

    flopy.mf6.ModflowGwtssm(
        gwt,
        sources=ssm_sources if ssm_sources else None,
    )

    # --- CNC: Constant Concentration (if source specified) ---
    if source_concentration is not None and source_cells is not None:
        cnc_data = []
        for cell in source_cells:
            cnc_data.append([cell, source_concentration])
        flopy.mf6.ModflowGwtcnc(
            gwt,
            stress_period_data=cnc_data,
        )
    elif contaminant != "conservative" and initial_concentration == 0.0:
        print(f"WARNING: No contaminant source (CNC/SRC) specified for '{contaminant}' "
              f"transport and initial_concentration=0. The GWT mass budget will be all "
              f"zeros. To add a source, use --source_concentration and --source_cells, "
              f"or set --initial_concentration > 0.")

    # --- OC: Output Control ---
    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{gwt_model_name}.cbc",
        concentration_filerecord=f"{gwt_model_name}.ucn",
        concentrationprintrecord=[("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")],
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("CONCENTRATION", "LAST"), ("BUDGET", "LAST")],
    )

    # --- IMS for GWT: separate solver ---
    # Transport requires BICGSTAB (asymmetric matrix due to advection)
    ims_gwt = flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_model_name}.ims",
        print_option="SUMMARY",
        outer_dvclose=1.0e-6,
        outer_maximum=100,
        under_relaxation="NONE",
        inner_maximum=300,
        inner_dvclose=1.0e-6,
        rcloserecord=[1.0e-6, "strict"],
        linear_acceleration="BICGSTAB",
        scaling_method="NONE",
        reordering_method="NONE",
    )
    sim.register_ims_package(ims_gwt, [gwt_model_name])

    # --- GWF-GWT Exchange ---
    flopy.mf6.ModflowGwfgwt(
        sim,
        exgtype="GWF6-GWT6",
        exgmnamea=gwf_model_name,
        exgmnameb=gwt_model_name,
        filename=f"{gwf_model_name}-{gwt_model_name}.gwfgwt",
    )

    # --- Write and optionally run ---
    sim.write_simulation()

    result = {
        "sim_ws": output_ws,
        "gwt_model_name": gwt_model_name,
        "gwf_model_name": gwf_model_name,
        "concentration_file": os.path.join(output_ws, f"{gwt_model_name}.ucn"),
        "budget_file": os.path.join(output_ws, f"{gwt_model_name}.cbc"),
        "listing_file": os.path.join(output_ws, f"{gwt_model_name}.lst"),
        "contaminant": contaminant,
        "parameters": {
            "porosity": _porosity,
            "longitudinal_dispersivity_m": _alh,
            "transverse_dispersivity_m": _ath1,
            "vertical_dispersivity_m": _atv,
            "diffusion_coefficient_m2_per_day": _diffc,
            "diffusion_coefficient_m2_per_s": _diffc_m2s,
            "advection_scheme": advection_scheme,
            "sorption": _sorption,
            "decay": _decay,
            "decay_rate_per_day": _decay_rate,
            "bulk_density_kg_per_L": _bulk_density,
            "distcoef_L_per_kg": _distcoef,
            "initial_concentration": initial_concentration,
        },
    }

    if run_model:
        print(f"Running coupled GWF-GWT simulation in {output_ws}...")
        try:
            proc = subprocess.run(
                [mf6_exe],
                cwd=output_ws,
                capture_output=True,
                text=True,
                timeout=600,
            )
            success = proc.returncode == 0 and "Normal termination" in proc.stdout
            result["success"] = success
            result["stdout"] = proc.stdout[-2000:] if len(proc.stdout) > 2000 else proc.stdout
            result["stderr"] = proc.stderr[-1000:] if proc.stderr else ""
            if not success:
                print(f"WARNING: Simulation may have failed. Return code: {proc.returncode}")
                # Read listing file for diagnostics
                lst_file = result["listing_file"]
                if os.path.exists(lst_file):
                    with open(lst_file, "r") as f:
                        lines = f.readlines()
                    # Get last 50 lines for diagnostics
                    result["listing_tail"] = "".join(lines[-50:])
            else:
                print("Simulation completed successfully.")
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["error"] = "Simulation timed out after 600 seconds"
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
    else:
        result["success"] = None  # Not run yet

    return result


def build_standalone_gwt(
    gwf_head_file,
    gwf_budget_file,
    gwt_ws,
    gwt_model_name="gwt",
    nlay=1,
    nrow=10,
    ncol=10,
    delr=100.0,
    delc=100.0,
    top=50.0,
    botm=None,
    idomain=None,
    nper=1,
    perlen=None,
    nstp=None,
    tsmult=None,
    contaminant="conservative",
    initial_concentration=0.0,
    source_concentration=None,
    source_cells=None,
    advection_scheme="UPSTREAM",
    porosity=None,
    longitudinal_dispersivity=None,
    transverse_dispersivity=None,
    vertical_dispersivity=None,
    diffusion_coefficient=None,
    sorption=None,
    decay=None,
    decay_rate=None,
    bulk_density=None,
    distcoef=None,
    ssm_sources=None,
    mf6_exe=None,
    run_model=True,
):
    """
    Build a standalone GWT model that reads flows from previously saved
    GWF head and budget binary files via the FMI (Flow Model Interface) package.

    This mode is useful when:
    - The GWF simulation has already been run
    - You want to test different transport scenarios without re-running flow
    - The GWF and GWT need different time stepping

    Parameters
    ----------
    gwf_head_file : str
        Path to the GWF binary head file (.hds).
    gwf_budget_file : str
        Path to the GWF binary budget file (.cbc).
    gwt_ws : str
        Workspace directory for the GWT simulation.
    gwt_model_name : str
        Model name for the GWT model.
    nlay, nrow, ncol : int
        Grid dimensions (must match the GWF model).
    delr, delc : float or array
        Cell sizes (must match the GWF model).
    top : float or array
        Top elevation (must match).
    botm : float, array, or None
        Bottom elevation(s). If None, defaults to [top - 10*nlay, ...].
    idomain : array or None
        Active/inactive domain mask (must match GWF).
    nper : int
        Number of stress periods.
    perlen : list or None
        Stress period lengths (days). If None, defaults to [1.0]*nper.
    nstp : list or None
        Number of time steps per period. If None, defaults to [1]*nper.
    tsmult : list or None
        Time step multiplier. If None, defaults to [1.0]*nper.
    contaminant : str
        Contaminant preset name.
    initial_concentration : float
        Initial concentration.
    source_concentration : float or None
        Concentration for CNC cells.
    source_cells : list of tuples or None
        CNC cell locations (0-indexed).
    advection_scheme : str
        UPSTREAM, CENTRAL, or TVD.
    porosity, longitudinal_dispersivity, transverse_dispersivity,
    vertical_dispersivity, diffusion_coefficient, sorption, decay,
    decay_rate, bulk_density, distcoef : various
        Transport parameter overrides (see build_coupled_gwt).
    ssm_sources : list of tuples or None
        SSM sources, e.g., [("WEL-1", "AUX", "CONCENTRATION")].
    mf6_exe : str or None
        Path to mf6 binary.
    run_model : bool
        Whether to run after building.

    Returns
    -------
    dict
        Result dictionary (same structure as build_coupled_gwt).
    """
    if contaminant not in CONTAMINANT_PRESETS:
        raise ValueError(f"Unknown contaminant '{contaminant}'.")

    preset = CONTAMINANT_PRESETS[contaminant]

    _porosity = porosity if porosity is not None else preset["porosity"]
    _alh = longitudinal_dispersivity if longitudinal_dispersivity is not None else preset["longitudinal_dispersivity"]
    _ath1 = transverse_dispersivity if transverse_dispersivity is not None else preset["transverse_dispersivity"]
    _atv = vertical_dispersivity if vertical_dispersivity is not None else preset["vertical_dispersivity"]
    _diffc_m2s = diffusion_coefficient if diffusion_coefficient is not None else preset["diffusion_coefficient"]
    _diffc = _diffusion_m2_per_day(_diffc_m2s)
    _sorption = sorption if sorption is not None else preset.get("sorption")
    _decay = decay if decay is not None else preset.get("decay")
    _decay_rate = decay_rate if decay_rate is not None else preset.get("decay_rate")
    _bulk_density = bulk_density if bulk_density is not None else preset.get("bulk_density")
    _distcoef = distcoef if distcoef is not None else preset.get("distcoef")

    if mf6_exe is None:
        mf6_exe = "/mnt/disk1/Hydrocraft_server/model/modflow6/mf6.6.1_linux/bin/mf6"

    os.makedirs(gwt_ws, exist_ok=True)

    if botm is None:
        layer_thickness = 10.0
        if isinstance(top, (int, float)):
            botm = [top - layer_thickness * (i + 1) for i in range(nlay)]
        else:
            botm = [np.array(top) - layer_thickness * (i + 1) for i in range(nlay)]

    if perlen is None:
        perlen = [1.0] * nper
    if nstp is None:
        nstp = [1] * nper
    if tsmult is None:
        tsmult = [1.0] * nper

    # --- Create simulation ---
    sim = flopy.mf6.MFSimulation(
        sim_name=gwt_model_name,
        sim_ws=gwt_ws,
        exe_name=mf6_exe,
    )

    # TDIS
    tdis_data = [(perlen[i], nstp[i], tsmult[i]) for i in range(nper)]
    flopy.mf6.ModflowTdis(
        sim,
        nper=nper,
        perioddata=tdis_data,
    )

    # --- GWT model ---
    gwt = flopy.mf6.ModflowGwt(
        sim,
        modelname=gwt_model_name,
        save_flows=True,
    )

    # DIS
    flopy.mf6.ModflowGwtdis(
        gwt,
        nlay=nlay, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top, botm=botm,
        idomain=idomain,
    )

    # IC
    flopy.mf6.ModflowGwtic(gwt, strt=initial_concentration)

    # ADV
    flopy.mf6.ModflowGwtadv(gwt, scheme=advection_scheme)

    # DSP
    dsp_kwargs = {}
    if _diffc > 0:
        dsp_kwargs["diffc"] = _diffc
    if _alh > 0:
        dsp_kwargs["alh"] = _alh
        dsp_kwargs["ath1"] = _ath1
    if _atv > 0:
        dsp_kwargs["atv"] = _atv

    flopy.mf6.ModflowGwtdsp(gwt, xt3d_off=True, **dsp_kwargs)

    # MST
    mst_kwargs = {"porosity": _porosity}
    if _sorption is not None and _sorption.upper() in ("LINEAR", "FREUNDLICH", "LANGMUIR"):
        mst_kwargs["sorption"] = _sorption.lower()
        if _bulk_density is not None:
            mst_kwargs["bulk_density"] = _bulk_density
        if _distcoef is not None:
            mst_kwargs["distcoef"] = _distcoef
    if _decay is not None:
        if _decay == "first_order":
            mst_kwargs["first_order_decay"] = True
        elif _decay == "zero_order":
            mst_kwargs["zero_order_decay"] = True
        if _decay_rate is not None:
            mst_kwargs["decay"] = _decay_rate
            if _sorption is not None:
                mst_kwargs["decay_sorbed"] = _decay_rate

    flopy.mf6.ModflowGwtmst(gwt, **mst_kwargs)

    # FMI: Flow Model Interface (read from saved GWF files)
    # Paths must be relative to gwt_ws or absolute
    head_path = os.path.relpath(gwf_head_file, gwt_ws) if not os.path.isabs(gwf_head_file) else gwf_head_file
    budget_path = os.path.relpath(gwf_budget_file, gwt_ws) if not os.path.isabs(gwf_budget_file) else gwf_budget_file

    pd = [
        ("GWFHEAD", head_path),
        ("GWFBUDGET", budget_path),
    ]
    flopy.mf6.ModflowGwtfmi(gwt, packagedata=pd)

    # SSM
    flopy.mf6.ModflowGwtssm(
        gwt,
        sources=ssm_sources if ssm_sources else None,
    )

    # CNC
    if source_concentration is not None and source_cells is not None:
        cnc_data = [[cell, source_concentration] for cell in source_cells]
        flopy.mf6.ModflowGwtcnc(gwt, stress_period_data=cnc_data)

    # OC
    flopy.mf6.ModflowGwtoc(
        gwt,
        budget_filerecord=f"{gwt_model_name}.cbc",
        concentration_filerecord=f"{gwt_model_name}.ucn",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("CONCENTRATION", "LAST"), ("BUDGET", "LAST")],
    )

    # IMS
    ims_gwt = flopy.mf6.ModflowIms(
        sim,
        filename=f"{gwt_model_name}.ims",
        print_option="SUMMARY",
        outer_dvclose=1.0e-6,
        outer_maximum=100,
        under_relaxation="NONE",
        inner_maximum=300,
        inner_dvclose=1.0e-6,
        rcloserecord=[1.0e-6, "strict"],
        linear_acceleration="BICGSTAB",
    )
    sim.register_ims_package(ims_gwt, [gwt_model_name])

    # Write and run
    sim.write_simulation()

    result = {
        "sim_ws": gwt_ws,
        "gwt_model_name": gwt_model_name,
        "concentration_file": os.path.join(gwt_ws, f"{gwt_model_name}.ucn"),
        "budget_file": os.path.join(gwt_ws, f"{gwt_model_name}.cbc"),
        "listing_file": os.path.join(gwt_ws, f"{gwt_model_name}.lst"),
        "contaminant": contaminant,
        "mode": "standalone_fmi",
        "parameters": {
            "porosity": _porosity,
            "longitudinal_dispersivity_m": _alh,
            "transverse_dispersivity_m": _ath1,
            "vertical_dispersivity_m": _atv,
            "diffusion_coefficient_m2_per_day": _diffc,
            "advection_scheme": advection_scheme,
            "sorption": _sorption,
            "decay": _decay,
            "decay_rate_per_day": _decay_rate,
        },
    }

    if run_model:
        print(f"Running standalone GWT simulation in {gwt_ws}...")
        try:
            proc = subprocess.run(
                [mf6_exe],
                cwd=gwt_ws,
                capture_output=True,
                text=True,
                timeout=600,
            )
            success = proc.returncode == 0 and "Normal termination" in proc.stdout
            result["success"] = success
            result["stdout"] = proc.stdout[-2000:] if len(proc.stdout) > 2000 else proc.stdout
            if not success:
                print(f"WARNING: Simulation may have failed. Return code: {proc.returncode}")
                lst_file = result["listing_file"]
                if os.path.exists(lst_file):
                    with open(lst_file, "r") as f:
                        lines = f.readlines()
                    result["listing_tail"] = "".join(lines[-50:])
            else:
                print("Simulation completed successfully.")
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["error"] = "Simulation timed out"
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
    else:
        result["success"] = None

    return result


def list_contaminant_presets():
    """Print available contaminant presets and their parameters."""
    print("\n=== Available Contaminant Presets ===\n")
    for name, params in CONTAMINANT_PRESETS.items():
        print(f"  {name}:")
        print(f"    {params['description']}")
        print(f"    porosity = {params['porosity']}")
        print(f"    ALH (longitudinal dispersivity) = {params['longitudinal_dispersivity']} m")
        print(f"    ATH1 (transverse dispersivity) = {params['transverse_dispersivity']} m")
        print(f"    Dm (molecular diffusion) = {params['diffusion_coefficient']} m2/s")
        if params.get('sorption'):
            print(f"    sorption = {params['sorption']}")
            print(f"    bulk_density = {params.get('bulk_density')} kg/L")
            print(f"    Kd (distcoef) = {params.get('distcoef')} L/kg")
        if params.get('decay'):
            print(f"    decay = {params['decay']}")
            print(f"    decay_rate = {params.get('decay_rate')} 1/day")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Configure a GWT (Groundwater Transport) model for MODFLOW 6"
    )
    parser.add_argument("--list-presets", action="store_true",
                        help="List available contaminant presets")
    parser.add_argument("--gwf-dir", type=str,
                        help="Directory containing existing GWF simulation")
    parser.add_argument("--contaminant", type=str, default="conservative",
                        help="Contaminant preset (default: conservative)")
    parser.add_argument("--gwt-name", type=str, default="gwt",
                        help="GWT model name (default: gwt)")
    parser.add_argument("--gwf-name", type=str, default=None,
                        help="GWF model name (auto-detected if not specified)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: subdirectory in gwf-dir)")
    parser.add_argument("--initial-conc", type=float, default=0.0,
                        help="Initial concentration (default: 0.0)")
    parser.add_argument("--source-conc", type=float, default=None,
                        help="Source concentration for CNC boundary")
    parser.add_argument("--source-cell", type=str, default=None,
                        help="Source cell as 'layer,row,col' (0-indexed)")
    parser.add_argument("--advection", type=str, default="UPSTREAM",
                        choices=["UPSTREAM", "CENTRAL", "TVD"],
                        help="Advection scheme (default: UPSTREAM)")
    parser.add_argument("--porosity", type=float, default=None,
                        help="Override preset porosity")
    parser.add_argument("--alh", type=float, default=None,
                        help="Override longitudinal dispersivity (m)")
    parser.add_argument("--mf6-exe", type=str, default=None,
                        help="Path to mf6 binary")
    parser.add_argument("--no-run", action="store_true",
                        help="Build model files without running")

    args = parser.parse_args()

    if args.list_presets:
        list_contaminant_presets()
        sys.exit(0)

    if args.gwf_dir is None:
        parser.error("--gwf-dir is required (or use --list-presets)")

    source_cells = None
    if args.source_cell is not None:
        parts = [int(x) for x in args.source_cell.split(",")]
        source_cells = [tuple(parts)]

    result = build_coupled_gwt(
        gwf_sim_ws=args.gwf_dir,
        gwt_model_name=args.gwt_name,
        gwf_model_name=args.gwf_name,
        contaminant=args.contaminant,
        initial_concentration=args.initial_conc,
        source_concentration=args.source_conc,
        source_cells=source_cells,
        advection_scheme=args.advection,
        porosity=args.porosity,
        longitudinal_dispersivity=args.alh,
        output_ws=args.output_dir,
        mf6_exe=args.mf6_exe,
        run_model=not args.no_run,
    )

    print("\n=== Result ===")
    print(json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr", "listing_tail")}, indent=2))
