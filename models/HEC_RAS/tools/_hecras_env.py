"""
Shared environment + run helpers for the HEC-RAS knowledge infrastructure.

HEC-RAS is proprietary USACE Windows software. We drive the real Intel-Fortran
solvers (RasSteady.exe etc.) under WINE. See docs/input_preparation.md for the
verified execution architecture.

Nothing in here approximates the physics — every run invokes the actual binary.
"""
import os
import shutil
import subprocess

# ---------------------------------------------------------------------------
# Binary locations (WINE-staged HEC-RAS 6.7 Beta 5)
# ---------------------------------------------------------------------------
RAS_INSTALL = "KISSPATH_HOME/.wine/drive_c/Program Files (x86)/HEC/HEC-RAS/6.7 Beta 5"
RAS_BIN_DIR = os.path.join(RAS_INSTALL, "x64")

BINARIES = {
    "steady":           os.path.join(RAS_BIN_DIR, "RasSteady.exe"),
    "unsteady":         os.path.join(RAS_BIN_DIR, "RasUnsteady.exe"),
    "geom_preprocess":  os.path.join(RAS_BIN_DIR, "RasGeomPreprocess.exe"),
    "unsteady_sediment":os.path.join(RAS_BIN_DIR, "RasUnsteadySediment.exe"),
    "quasi_sediment":   os.path.join(RAS_BIN_DIR, "RasQuasiSediment.exe"),
    "water_quality":    os.path.join(RAS_BIN_DIR, "RasWaterQuality.exe"),
}

WINEPREFIX = os.environ.get("WINEPREFIX", "KISSPATH_HOME/.wine")

# Path to the bundled, validated template project (steady, Mixed Flow Regime).
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "examples", "MixedFlowSteady")
TEMPLATE_PRJ = "MIXED"   # base name of the template project files


def wine_env():
    """Environment dict for invoking wine cleanly.

    A broken system-wide LD_PRELOAD (32-bit libstdc++) breaks wine on this host;
    we strip it. WINEDEBUG silences noise.
    """
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    env["WINEPREFIX"] = WINEPREFIX
    env["WINEDEBUG"] = "-all"
    return env


def check_binary(kind="steady"):
    """Return the binary path for *kind*, raising if missing."""
    if kind not in BINARIES:
        raise ValueError(f"unknown binary kind {kind!r}; choices: {sorted(BINARIES)}")
    path = BINARIES[kind]
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"HEC-RAS binary not found: {path}\n"
            "Verify the WINE-staged install (see preflight_check.py and "
            "diagnostics/triplets.yaml entry 'binary_missing')."
        )
    return path


def run_solver(kind, run_arg, cwd, timeout=600):
    """Invoke a HEC-RAS solver under wine from *cwd*.

    Parameters
    ----------
    kind : str        one of BINARIES keys (usually "steady")
    run_arg : str     argument passed to the solver, e.g. "MIXED.r01"
    cwd : str         project working directory (must contain run_arg)
    timeout : int     seconds

    Returns
    -------
    dict with keys: returncode, stdout, finished (bool), cmd
    """
    binary = check_binary(kind)
    cmd = ["wine", binary, run_arg]
    proc = subprocess.run(
        cmd, cwd=cwd, env=wine_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout,
    )
    out = proc.stdout or ""
    finished = ("Finished Steady Flow Simulation" in out
                or "Finished Unsteady" in out
                or "Computations Complete" in out)
    return {"returncode": proc.returncode, "stdout": out,
            "finished": finished, "cmd": " ".join(cmd)}


def seed_plan_hdf(workspace, prj=TEMPLATE_PRJ, plan="01"):
    """Create the <prj>.p<plan>.tmp.hdf results skeleton from the geometry HDF.

    This is the step Ras.exe (Wine Mono) would normally perform. Without it the
    Fortran solver aborts with 'HDF_ERROR trying to open HDF output file'.
    The geometry HDF must already exist (ships with the example, or is produced
    by preprocess_geometry.py).
    """
    geom_hdf = None
    for cand in (f"{prj}.g01.hdf", f"{prj}.g{plan}.hdf"):
        p = os.path.join(workspace, cand)
        if os.path.isfile(p):
            geom_hdf = p
            break
    if geom_hdf is None:
        # fall back to any *.g*.hdf in the workspace
        for f in os.listdir(workspace):
            if f.lower().endswith(".hdf") and ".g" in f.lower():
                geom_hdf = os.path.join(workspace, f)
                break
    if geom_hdf is None:
        raise FileNotFoundError(
            f"No geometry HDF (<prj>.gNN.hdf) found in {workspace}. "
            "Run preprocess_geometry.py first, or use a project that ships one. "
            "See triplets.yaml 'missing_geometry_hdf'.")
    dest = os.path.join(workspace, f"{prj}.p{plan}.tmp.hdf")
    shutil.copy2(geom_hdf, dest)
    return dest


# HDF path to the steady cross-section results block.
STEADY_XS = ("/Results/Steady/Output/Output Blocks/Base Output/"
             "Steady Profiles/Cross Sections/")
