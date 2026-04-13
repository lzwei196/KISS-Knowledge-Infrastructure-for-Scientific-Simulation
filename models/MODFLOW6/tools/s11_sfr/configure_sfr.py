#!/usr/bin/env python3
"""
configure_sfr.py -- Set up a MODFLOW 6 SFR (Streamflow Routing) package
for an existing GWF model.

Part of MODFLOW 6 Knowledge Infrastructure, Stage S11 (Streamflow Routing).
KDT v5.0 approach.

The SFR package simulates 1D open-channel flow in stream networks. It routes
flow downstream through connected reaches and computes stream-aquifer
interaction based on Manning's equation for stream stage calculation.

Advantages over RIV package:
  - Computes stream stage from Manning's equation (not user-specified)
  - Routes flow downstream through connected reaches
  - Supports diversions (irrigation canals, etc.)
  - Tracks stream-aquifer exchange per reach
  - Can handle dry reaches (no flow) and rewetting

SFR key concepts:
  - REACH: A segment of stream within a single model cell
  - PACKAGEDATA: Static properties (length, width, slope, Manning's n,
    streambed K, streambed thickness, number of connections)
  - CONNECTIONDATA: Topology (which reaches connect to which)
  - PERIODDATA: Time-varying settings (inflow, diversion, status, stage)

Unit conversion:
  - Manning's equation: Q = (1/n) * A * R^(2/3) * S^(1/2)
  - For meters + days: unit_conversion = 86400.0 (seconds/day)
  - For feet + days: length_conversion = 3.28081, time_conversion = 86400.0

References:
  - mf6io.pdf pp. 123-137 (SFR Package Input)
  - MODFLOW 6.6.1 examples: ex-gwf-sfr-p01, ex-gwf-sfr-p01b
  - FloPy: flopy.mf6.ModflowGwfsfr
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
# Stream type presets -- documentation-derived parameter defaults
# ---------------------------------------------------------------------------
STREAM_PRESETS = {
    "mountain_stream": {
        "description": "Mountain/headwater stream -- steep, narrow, rocky bed",
        "manning_n": 0.04,          # rocky, cobble bottom
        "streambed_k": 1.0,         # m/day (moderate K)
        "streambed_thickness": 1.0,  # m
        "width": 5.0,               # m (typical headwater width)
        "slope": 0.01,              # 1% grade
    },
    "lowland_river": {
        "description": "Lowland/alluvial river -- gentle slope, wide, sandy bed",
        "manning_n": 0.03,          # sandy/silty bottom
        "streambed_k": 5.0,         # m/day (alluvial, high K)
        "streambed_thickness": 1.5,  # m
        "width": 30.0,              # m (typical lowland river)
        "slope": 0.001,             # 0.1% grade
    },
    "canal": {
        "description": "Engineered canal/irrigation channel",
        "manning_n": 0.015,         # concrete or smooth lining
        "streambed_k": 0.01,        # m/day (lined, very low K)
        "streambed_thickness": 0.5,  # m
        "width": 10.0,              # m
        "slope": 0.0005,            # 0.05% grade
    },
    "wetland_channel": {
        "description": "Wetland/marsh drainage channel -- very gentle, vegetated",
        "manning_n": 0.06,          # heavy vegetation
        "streambed_k": 0.5,         # m/day (organic/silty bed)
        "streambed_thickness": 2.0,  # m
        "width": 15.0,              # m
        "slope": 0.0001,            # 0.01% grade
    },
    "generic": {
        "description": "Generic stream with moderate parameters",
        "manning_n": 0.035,
        "streambed_k": 1.0,
        "streambed_thickness": 1.0,
        "width": 10.0,
        "slope": 0.001,
    },
}


def build_sfr_package(
    gwf_sim_ws,
    reach_data,
    connection_data,
    gwf_model_name=None,
    stream_preset="generic",
    diversions=None,
    period_data=None,
    unit_conversion=None,
    length_conversion=1.0,
    time_conversion=86400.0,
    save_flows=True,
    save_stage=True,
    observations=None,
    output_ws=None,
    mf6_exe=None,
    run_model=True,
):
    """
    Add an SFR package to an existing GWF model simulation.

    Parameters
    ----------
    gwf_sim_ws : str
        Path to the directory containing the existing GWF simulation
        (must contain mfsim.nam and all GWF package files).
    reach_data : list of dict
        Each dict defines one reach with keys:
          - ifno: int -- reach number (1-based)
          - cellid: tuple -- (layer, row, col), 0-indexed for FloPy
          - rlen: float -- reach length (m)
          - rwid: float -- reach width (m)  [optional, uses preset]
          - rgrd: float -- stream gradient  [optional, uses preset]
          - rtp: float -- streambed top elevation (m)
          - rbth: float -- streambed thickness (m)  [optional, uses preset]
          - rhk: float -- streambed hydraulic conductivity (m/day)  [optional]
          - man: float -- Manning's n  [optional, uses preset]
          - ncon: int -- number of connections
          - ustrf: float -- upstream fraction (default 1.0)
          - ndv: int -- number of diversions (default 0)
          - boundname: str -- optional name for the reach
    connection_data : list of list
        Each sublist: [ifno, ic1, ic2, ...] where negative values indicate
        downstream connections and positive values indicate upstream.
        Example: [1, -2] means reach 1 flows downstream to reach 2.
    gwf_model_name : str or None
        Name of the GWF model. If None, auto-detected.
    stream_preset : str
        Stream type preset for default parameters. One of:
        mountain_stream, lowland_river, canal, wetland_channel, generic.
    diversions : list of list or None
        Each sublist: [ifno, idv, iconr, cprior]
        - ifno: reach number with the diversion
        - idv: diversion number (1-based)
        - iconr: reach receiving diverted flow
        - cprior: diversion priority (FRACTION, EXCESS, THRESHOLD, UPTO)
    period_data : dict or None
        Keys are stress period numbers (0-indexed). Values are lists of
        [ifno, setting_keyword, value] tuples.
        Keywords: INFLOW, RAINFALL, EVAPORATION, RUNOFF, DIVERSION,
                  UPSTREAM_FRACTION, STAGE, STATUS, AUXILIARY.
        Example: {0: [[1, "INFLOW", 100.0], [5, "INFLOW", 50.0]]}
    unit_conversion : float
        Conversion factor for Manning's equation. For meters + days, use
        86400.0 (default). For feet + seconds, use 1.486.
    length_conversion : float or None
        Length conversion for Manning's n (e.g., 3.28081 for feet).
        If None, not set (assumes meters).
    time_conversion : float or None
        Time conversion for Manning's n (e.g., 86400.0 for days).
        If None, not set.
    save_flows : bool
        Save SFR flow terms to budget file.
    save_stage : bool
        Save SFR stage to a binary output file.
    observations : list of dict or None
        SFR observations. Each dict has:
          - name: str -- observation name
          - obs_type: str -- e.g., "stage", "downstream-flow", "sfr"
          - ifno: int -- reach number (1-based)
    output_ws : str or None
        Output workspace. If None, modifies in place.
    mf6_exe : str or None
        Path to mf6 binary.
    run_model : bool
        Whether to run the simulation after adding SFR.

    Returns
    -------
    dict
        Result dictionary with keys:
        - sim_ws, gwf_model_name, nreaches, success
        - stage_file, budget_file, listing_file
        - obs_file (if observations specified)
        - reach_summary (list of reach info)
    """
    if stream_preset not in STREAM_PRESETS:
        raise ValueError(
            f"Unknown stream preset '{stream_preset}'. "
            f"Choose from: {list(STREAM_PRESETS.keys())}"
        )

    preset = STREAM_PRESETS[stream_preset]

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
        gwf_names = [n for n in model_names
                     if n.startswith("gwf") or
                     sim.get_model(n).model_type == "gwf6"]
        gwf_model_name = gwf_names[0] if gwf_names else model_names[0]

    gwf = sim.get_model(gwf_model_name)
    if gwf is None:
        raise ValueError(
            f"GWF model '{gwf_model_name}' not found. "
            f"Available: {list(sim.model_names)}"
        )

    # --- Set up output workspace ---
    if output_ws is None:
        output_ws = gwf_sim_ws

    if output_ws != gwf_sim_ws:
        os.makedirs(output_ws, exist_ok=True)
        for fname in os.listdir(gwf_sim_ws):
            src = os.path.join(gwf_sim_ws, fname)
            dst = os.path.join(output_ws, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
        sim = flopy.mf6.MFSimulation.load(
            sim_ws=output_ws,
            exe_name=mf6_exe,
        )
        gwf = sim.get_model(gwf_model_name)

    # --- Get grid info for validation ---
    dis = gwf.get_package("DIS")
    top_arr = dis.top.get_data()
    botm_arr = dis.botm.get_data()

    # --- Build packagedata ---
    nreaches = len(reach_data)
    pkg_data = []

    for rd in reach_data:
        ifno = rd["ifno"]
        cellid = tuple(rd["cellid"])
        rlen = rd["rlen"]
        rwid = rd.get("rwid", preset["width"])
        rgrd = rd.get("rgrd", preset["slope"])
        rtp = rd["rtp"]
        rbth = rd.get("rbth", preset["streambed_thickness"])
        rhk = rd.get("rhk", preset["streambed_k"])
        man = rd.get("man", preset["manning_n"])
        ncon = rd["ncon"]
        ustrf = rd.get("ustrf", 1.0)
        ndv = rd.get("ndv", 0)

        # Validate: streambed top must be above cell bottom
        lay, row, col = cellid
        cell_botm = botm_arr[lay, row, col]
        if rtp - rbth < cell_botm:
            print(f"WARNING: Reach {ifno} streambed bottom "
                  f"({rtp - rbth:.1f}) is below cell bottom "
                  f"({cell_botm:.1f}). Adjusting rtp upward.")
            rtp = cell_botm + rbth + 0.5

        entry = [
            ifno - 1,  # FloPy uses 0-based ifno
            cellid,
            rlen, rwid, rgrd, rtp, rbth, rhk, man,
            ncon, ustrf, ndv,
        ]
        pkg_data.append(entry)

    # --- Build connectiondata ---
    # Convert 1-based to 0-based for FloPy
    conn_data = []
    for conn in connection_data:
        converted = []
        for i, val in enumerate(conn):
            if i == 0:
                converted.append(val - 1)  # ifno
            else:
                # Preserve sign for downstream (-) / upstream (+)
                sign = -1 if val < 0 else 1
                converted.append(sign * (abs(val) - 1))
        conn_data.append(converted)

    # --- Build diversions data ---
    div_data = None
    if diversions is not None and len(diversions) > 0:
        div_data = []
        for div in diversions:
            div_data.append([
                div[0] - 1,       # ifno (0-based)
                div[1] - 1,       # idv (0-based)
                div[2] - 1,       # iconr (0-based)
                div[3],           # cprior string
            ])

    # --- Build period data ---
    spd = None
    if period_data is not None:
        spd = {}
        for per, entries in period_data.items():
            per_list = []
            for entry in entries:
                ifno_1based = entry[0]
                keyword = entry[1].lower()
                value = entry[2] if len(entry) > 2 else None

                row = [ifno_1based - 1, keyword]
                if value is not None:
                    row.append(value)
                per_list.append(tuple(row))
            spd[per] = per_list

    # --- SFR options ---
    sfr_kwargs = {
        "save_flows": save_flows,
        "print_stage": True,
        "print_flows": True,
        "nreaches": nreaches,
        "packagedata": pkg_data,
        "connectiondata": conn_data,
        "pname": "sfr_0",
    }

    # Unit conversion
    if unit_conversion is not None:
        sfr_kwargs["unit_conversion"] = unit_conversion
    if length_conversion is not None:
        sfr_kwargs["length_conversion"] = length_conversion
    if time_conversion is not None:
        sfr_kwargs["time_conversion"] = time_conversion

    # Stage output
    if save_stage:
        sfr_kwargs["stage_filerecord"] = f"{gwf_model_name}.sfr.stg"
        sfr_kwargs["budget_filerecord"] = f"{gwf_model_name}.sfr.cbc"

    # Diversions
    if div_data is not None:
        sfr_kwargs["diversions"] = div_data

    # Period data
    if spd is not None:
        sfr_kwargs["perioddata"] = spd

    # --- Observations ---
    obs_file = None
    if observations is not None and len(observations) > 0:
        obs_dict = {}
        obs_records = []
        for obs in observations:
            obs_records.append(
                (obs["name"], obs["obs_type"], obs["ifno"])
            )
        obs_csv = f"{gwf_model_name}.sfr.obs.csv"
        obs_dict[obs_csv] = obs_records
        sfr_kwargs["observations"] = obs_dict
        obs_file = os.path.join(output_ws, obs_csv)

    # --- Remove existing SFR package if present ---
    try:
        gwf.remove_package("SFR")
    except Exception:
        pass

    # --- Create the SFR package ---
    sfr = flopy.mf6.ModflowGwfsfr(gwf, **sfr_kwargs)

    # Ensure GWF saves flows
    gwf.name_file.save_flows = True

    # --- Write and optionally run ---
    sim.write_simulation()

    result = {
        "sim_ws": output_ws,
        "gwf_model_name": gwf_model_name,
        "nreaches": nreaches,
        "stream_preset": stream_preset,
        "stage_file": os.path.join(output_ws, f"{gwf_model_name}.sfr.stg") if save_stage else None,
        "budget_file": os.path.join(output_ws, f"{gwf_model_name}.sfr.cbc") if save_stage else None,
        "listing_file": os.path.join(output_ws, f"{gwf_model_name}.lst"),
        "obs_file": obs_file,
        "reach_summary": [
            {
                "ifno": rd["ifno"],
                "cellid": rd["cellid"],
                "rlen": rd["rlen"],
                "rwid": rd.get("rwid", preset["width"]),
                "rgrd": rd.get("rgrd", preset["slope"]),
                "rtp": rd["rtp"],
                "man": rd.get("man", preset["manning_n"]),
                "rhk": rd.get("rhk", preset["streambed_k"]),
            }
            for rd in reach_data
        ],
    }

    if run_model:
        print(f"Running GWF+SFR simulation in {output_ws}...")
        try:
            proc = subprocess.run(
                [mf6_exe],
                cwd=output_ws,
                capture_output=True,
                text=True,
                timeout=600,
            )
            success = (proc.returncode == 0 and
                       "Normal termination" in proc.stdout)
            result["success"] = success
            result["stdout"] = (proc.stdout[-2000:]
                                if len(proc.stdout) > 2000
                                else proc.stdout)
            result["stderr"] = (proc.stderr[-1000:]
                                if proc.stderr else "")
            if not success:
                print(f"WARNING: Simulation may have failed. "
                      f"Return code: {proc.returncode}")
                lst_file = result["listing_file"]
                if os.path.exists(lst_file):
                    with open(lst_file, "r") as f:
                        lines = f.readlines()
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
        result["success"] = None

    return result


def build_simple_sfr(
    gwf_sim_ws,
    stream_cells,
    stream_elevations,
    gwf_model_name=None,
    stream_preset="generic",
    inflow_rate=10.0,
    manning_n=None,
    streambed_k=None,
    streambed_thickness=None,
    stream_width=None,
    stream_slope=None,
    output_ws=None,
    mf6_exe=None,
    run_model=True,
):
    """
    Simplified SFR builder for a single linear stream network.

    Takes a list of cells forming a stream path (upstream to downstream)
    and automatically builds reach data, connections, and period data.

    Parameters
    ----------
    gwf_sim_ws : str
        Path to existing GWF simulation directory.
    stream_cells : list of tuple
        Ordered list of (layer, row, col) tuples from upstream to downstream.
        0-indexed (FloPy convention).
    stream_elevations : list of float
        Streambed top elevation for each reach (m). Must be monotonically
        decreasing (upstream to downstream). Same length as stream_cells.
    gwf_model_name : str or None
        GWF model name (auto-detected if None).
    stream_preset : str
        Stream type preset name.
    inflow_rate : float
        Upstream inflow rate in m3/day (applied to first reach).
    manning_n : float or None
        Override Manning's n for all reaches.
    streambed_k : float or None
        Override streambed K for all reaches (m/day).
    streambed_thickness : float or None
        Override streambed thickness for all reaches (m).
    stream_width : float or None
        Override stream width for all reaches (m).
    stream_slope : float or None
        Override stream slope for all reaches.
        If None, computed from elevation difference / reach length.
    output_ws : str or None
        Output workspace.
    mf6_exe : str or None
        Path to mf6 binary.
    run_model : bool
        Run after building.

    Returns
    -------
    dict
        Same as build_sfr_package return.
    """
    if len(stream_cells) != len(stream_elevations):
        raise ValueError(
            f"stream_cells ({len(stream_cells)}) and "
            f"stream_elevations ({len(stream_elevations)}) must have "
            f"the same length."
        )

    if len(stream_cells) < 2:
        raise ValueError("Need at least 2 cells for a stream network.")

    preset = STREAM_PRESETS.get(stream_preset, STREAM_PRESETS["generic"])
    _man = manning_n if manning_n is not None else preset["manning_n"]
    _rhk = streambed_k if streambed_k is not None else preset["streambed_k"]
    _rbth = (streambed_thickness if streambed_thickness is not None
             else preset["streambed_thickness"])
    _rwid = stream_width if stream_width is not None else preset["width"]

    # Load simulation to get cell sizes for reach length calculation
    if mf6_exe is None:
        mf6_exe = "/mnt/disk1/Hydrocraft_server/model/modflow6/mf6.6.1_linux/bin/mf6"

    sim = flopy.mf6.MFSimulation.load(
        sim_ws=gwf_sim_ws,
        exe_name=mf6_exe,
    )
    if gwf_model_name is None:
        model_names = list(sim.model_names)
        gwf_names = [n for n in model_names
                     if n.startswith("gwf") or
                     sim.get_model(n).model_type == "gwf6"]
        gwf_model_name = gwf_names[0] if gwf_names else model_names[0]

    gwf = sim.get_model(gwf_model_name)
    dis = gwf.get_package("DIS")
    delr = dis.delr.get_data()
    delc = dis.delc.get_data()

    # Build reach data
    nreaches = len(stream_cells)
    reach_data = []
    connection_data = []

    for i in range(nreaches):
        lay, row, col = stream_cells[i]
        rtp = stream_elevations[i]

        # Reach length: approximate as cell dimension along flow direction
        # delr/delc from FloPy can be scalar or 1D array
        delr_arr = np.atleast_1d(delr)
        delc_arr = np.atleast_1d(delc)
        cell_dx = float(delr_arr[col]) if col < len(delr_arr) else float(delr_arr[0])
        cell_dy = float(delc_arr[row]) if row < len(delc_arr) else float(delc_arr[0])

        if i < nreaches - 1:
            next_row, next_col = stream_cells[i + 1][1], stream_cells[i + 1][2]
            dr = abs(next_row - row)
            dc = abs(next_col - col)
            if dr > 0 and dc > 0:
                # Diagonal
                rlen = float(np.sqrt(cell_dy ** 2 + cell_dx ** 2))
            elif dr > 0:
                rlen = cell_dy
            else:
                rlen = cell_dx
        else:
            # Last reach: use same length as previous
            rlen = reach_data[-1]["rlen"] if reach_data else 100.0

        # Slope
        if stream_slope is not None:
            rgrd = stream_slope
        elif i < nreaches - 1:
            dz = stream_elevations[i] - stream_elevations[i + 1]
            rgrd = max(dz / rlen, 1e-6)  # Ensure positive slope
        else:
            rgrd = reach_data[-1]["rgrd"] if reach_data else preset["slope"]

        # Number of connections
        if i == 0:
            ncon = 1  # Only downstream
        elif i == nreaches - 1:
            ncon = 1  # Only upstream
        else:
            ncon = 2  # Upstream and downstream

        reach_data.append({
            "ifno": i + 1,  # 1-based
            "cellid": (lay, row, col),
            "rlen": rlen,
            "rwid": _rwid,
            "rgrd": rgrd,
            "rtp": rtp,
            "rbth": _rbth,
            "rhk": _rhk,
            "man": _man,
            "ncon": ncon,
            "ustrf": 1.0,
            "ndv": 0,
        })

        # Connections (1-based, negative = downstream)
        if i == 0:
            connection_data.append([i + 1, -(i + 2)])
        elif i == nreaches - 1:
            connection_data.append([i + 1, i])
        else:
            connection_data.append([i + 1, i, -(i + 2)])

    # Period data: inflow at first reach
    period_data = {
        0: [[1, "INFLOW", inflow_rate]],
    }

    return build_sfr_package(
        gwf_sim_ws=gwf_sim_ws,
        reach_data=reach_data,
        connection_data=connection_data,
        gwf_model_name=gwf_model_name,
        stream_preset=stream_preset,
        period_data=period_data,
        output_ws=output_ws,
        mf6_exe=mf6_exe,
        run_model=run_model,
    )


def build_sfr_test_model(
    workspace,
    mf6_exe=None,
    nrow=10,
    ncol=10,
    delr=500.0,
    delc=500.0,
    top_left=100.0,
    top_right=80.0,
    k=10.0,
    recharge=0.001,
    stream_inflow=5000.0,
    stream_preset="generic",
    run_model=True,
):
    """
    Build a self-contained test model with SFR for validation.

    Creates a simple GWF model with a stream running diagonally from
    upper-left to lower-right, then adds an SFR package.

    Parameters
    ----------
    workspace : str
        Directory for the test model.
    mf6_exe : str or None
        Path to mf6 binary.
    nrow, ncol : int
        Grid dimensions.
    delr, delc : float
        Cell size in meters.
    top_left, top_right : float
        Elevation at left and right edges (creates a slope).
    k : float
        Hydraulic conductivity (m/day).
    recharge : float
        Recharge rate (m/day).
    stream_inflow : float
        Inflow at the upstream end of the stream (m3/day).
    stream_preset : str
        Stream type preset.
    run_model : bool
        Whether to run the simulation.

    Returns
    -------
    dict
        Result with sim_ws, success, and diagnostic information.
    """
    if mf6_exe is None:
        mf6_exe = "/mnt/disk1/Hydrocraft_server/model/modflow6/mf6.6.1_linux/bin/mf6"

    os.makedirs(workspace, exist_ok=True)

    # Create a sloping top surface
    top = np.zeros((nrow, ncol))
    for j in range(ncol):
        top[:, j] = top_left + (top_right - top_left) * j / (ncol - 1)
    # Add slight N-S slope
    for i in range(nrow):
        top[i, :] -= 2.0 * i / (nrow - 1)

    botm = top - 50.0  # 50m thick aquifer

    # --- Build GWF model ---
    sim = flopy.mf6.MFSimulation(
        sim_name="sfr_test",
        sim_ws=workspace,
        exe_name=mf6_exe,
    )

    tdis = flopy.mf6.ModflowTdis(
        sim, nper=1,
        perioddata=[(365.0, 10, 1.5)],  # 1 year, 10 time steps
    )

    ims = flopy.mf6.ModflowIms(
        sim,
        complexity="MODERATE",
        print_option="SUMMARY",
        outer_dvclose=1e-6,
        inner_dvclose=1e-6,
        rcloserecord=[1e-3, "strict"],
        linear_acceleration="BICGSTAB",
    )

    gwf = flopy.mf6.ModflowGwf(
        sim,
        modelname="gwf",
        newtonoptions="NEWTON UNDER_RELAXATION",
        save_flows=True,
    )

    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        nlay=1, nrow=nrow, ncol=ncol,
        delr=delr, delc=delc,
        top=top, botm=[botm],
    )

    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=1,
        k=k,
    )

    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=1,
        ss=1e-5,
        sy=0.15,
        transient={0: True},
    )

    ic = flopy.mf6.ModflowGwfic(gwf, strt=top - 5.0)

    rch = flopy.mf6.ModflowGwfrcha(gwf, recharge=recharge)

    # CHD on the right boundary (downstream)
    chd_data = [
        [(0, i, ncol - 1), top[i, ncol - 1] - 5.0]
        for i in range(nrow)
    ]
    chd = flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_data)

    oc = flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord="gwf.hds",
        budget_filerecord="gwf.cbc",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
        printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    )

    # --- Define stream path (diagonal from upper-left to lower-right) ---
    # Stream goes from (0,0,0) -> (0,1,1) -> (0,2,2) -> ... -> (0,N,N)
    n_reaches = min(nrow, ncol)
    stream_cells = [(0, i, i) for i in range(n_reaches)]
    stream_elevations = [
        float(top[i, i] - 2.0)  # Stream is 2m below land surface
        for i in range(n_reaches)
    ]

    # Write the base GWF simulation first
    sim.write_simulation()

    # Now add SFR using our tool
    result = build_simple_sfr(
        gwf_sim_ws=workspace,
        stream_cells=stream_cells,
        stream_elevations=stream_elevations,
        gwf_model_name="gwf",
        stream_preset=stream_preset,
        inflow_rate=stream_inflow,
        output_ws=workspace,
        mf6_exe=mf6_exe,
        run_model=run_model,
    )

    return result


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Configure MODFLOW 6 SFR (Streamflow Routing) Package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List stream presets
  python configure_sfr.py --list-presets

  # Build test model
  python configure_sfr.py --test --workspace /tmp/sfr_test

  # Add SFR to existing model (JSON reach data)
  python configure_sfr.py --gwf-dir /path/to/gwf \\
      --reach-json reaches.json \\
      --preset lowland_river
        """,
    )

    parser.add_argument("--list-presets", action="store_true",
                        help="List available stream presets")
    parser.add_argument("--test", action="store_true",
                        help="Build and run a self-contained test model")
    parser.add_argument("--workspace", type=str, default="/tmp/sfr_test",
                        help="Workspace for test model")
    parser.add_argument("--gwf-dir", type=str,
                        help="Path to existing GWF simulation directory")
    parser.add_argument("--reach-json", type=str,
                        help="JSON file with reach_data and connection_data")
    parser.add_argument("--preset", type=str, default="generic",
                        help="Stream type preset")
    parser.add_argument("--mf6-exe", type=str, default=None,
                        help="Path to mf6 binary")
    parser.add_argument("--no-run", action="store_true",
                        help="Write files but do not run simulation")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()

    if args.list_presets:
        print("\nAvailable stream type presets:")
        print("=" * 60)
        for name, preset in STREAM_PRESETS.items():
            print(f"\n  {name}:")
            print(f"    {preset['description']}")
            print(f"    Manning's n: {preset['manning_n']}")
            print(f"    Streambed K: {preset['streambed_k']} m/day")
            print(f"    Streambed thickness: {preset['streambed_thickness']} m")
            print(f"    Default width: {preset['width']} m")
            print(f"    Default slope: {preset['slope']}")
        return

    if args.test:
        print(f"Building SFR test model in {args.workspace}...")
        result = build_sfr_test_model(
            workspace=args.workspace,
            mf6_exe=args.mf6_exe,
            stream_preset=args.preset,
            run_model=not args.no_run,
        )
        if args.json:
            # Remove non-serializable items
            result_clean = {
                k: v for k, v in result.items()
                if not isinstance(v, (np.ndarray, np.generic))
            }
            print(json.dumps(result_clean, indent=2, default=str))
        else:
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")
            print(f"Workspace: {result['sim_ws']}")
            print(f"Reaches: {result['nreaches']}")
            if result.get("stage_file"):
                print(f"Stage file: {result['stage_file']}")
        return

    if args.gwf_dir and args.reach_json:
        with open(args.reach_json, "r") as f:
            data = json.load(f)
        result = build_sfr_package(
            gwf_sim_ws=args.gwf_dir,
            reach_data=data["reach_data"],
            connection_data=data["connection_data"],
            stream_preset=args.preset,
            diversions=data.get("diversions"),
            period_data=data.get("period_data"),
            mf6_exe=args.mf6_exe,
            run_model=not args.no_run,
        )
        if args.json:
            result_clean = {
                k: v for k, v in result.items()
                if not isinstance(v, (np.ndarray, np.generic))
            }
            print(json.dumps(result_clean, indent=2, default=str))
        else:
            print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
