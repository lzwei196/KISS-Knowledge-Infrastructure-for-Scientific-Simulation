# -*- mode: python ; coding: utf-8 -*-
"""Reproducible Apple Silicon GeoForge Desktop bundle."""

from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)


# PyInstaller exposes SPECPATH as the directory containing this spec.
SOURCE = Path(SPECPATH).resolve()
REPO = SOURCE.parent
with (SOURCE / "pyproject.toml").open("rb") as version_file:
    VERSION = tomllib.load(version_file)["project"]["version"]
BUILD_NUMBER = "".join(VERSION.split("."))
ICON = REPO / "assets" / "logo.icns"
KI_TOOLS_SOURCE = REPO / "ki_tools_common"

trust_datas, trust_binaries, trust_hidden = collect_all("truststore")
netcdf_datas, netcdf_binaries, netcdf_hidden = collect_all("netCDF4")
certifi_datas = collect_data_files("certifi")
calibration_datas = []
for distribution in ("numpy", "PyYAML", "spotpy", "pymoo", "moocore"):
    calibration_datas.extend(copy_metadata(distribution))
calibration_binaries = collect_dynamic_libs("pymoo")
# The framework exposes six concrete algorithms. Listing their real import
# paths is more reproducible than collect_all("pymoo"), which also freezes
# experimental algorithms, visualisation helpers, scikit-learn, and tests.
calibration_hidden = [
    "numpy", "scipy", "yaml", "spotpy",
    "pymoo.core.problem", "pymoo.optimize",
    "pymoo.algorithms.moo.nsga2", "pymoo.algorithms.moo.nsga3",
    "pymoo.algorithms.moo.moead", "pymoo.util.ref_dirs",
    "pymoo.functions.compiled.calc_perpendicular_distance",
    "pymoo.functions.compiled.decomposition",
    "pymoo.functions.compiled.mnn",
    "pymoo.functions.compiled.non_dominated_sorting",
    "pymoo.functions.compiled.pruning_cd",
    "pymoo.functions.compiled.stochastic_ranking",
]
harness_hidden = [
    "ki_tools_common",
    "ki_tools_common.harness",
    "ki_tools_common.harness.ki_harness",
    "ki_tools_common.harness.ki_path",
    "ki_tools_common.harness.ki_attention",
    "ki_tools_common.harness.agent_spawn",
    # the plan → approve → execute → verify flow (lazy __getattr__ imports need these listed)
    "ki_tools_common.flow",
    "ki_tools_common.flow.states",
    "ki_tools_common.flow.resolve",
    "ki_tools_common.flow.plan",
    "ki_tools_common.flow.approval",
    "ki_tools_common.flow.contracts",
    "ki_tools_common.flow.receipts",
    "ki_tools_common.flow.policy",
    "ki_tools_common.flow.tools",
    "ki_tools_common.flow.build_data",
]

a = Analysis(
    [str(SOURCE / "kiss_entry.py")],
    pathex=[str(SOURCE), str(KI_TOOLS_SOURCE)],
    binaries=[*trust_binaries, *netcdf_binaries, *calibration_binaries],
    datas=[
        (str(SOURCE / "kiss_cli" / "web"), "kiss_cli/web"),
        (str(REPO / "models"), "models"),
        (str(SOURCE / "system_kis"), "system_kis"),
        (str(REPO / "ki_tools_common"), "ki_tools_common"),
        (str(SOURCE / "vendor" / "agent-calibration-framework"),
         "agent-calibration-framework"),
        (str(SOURCE / "manifests"), "kiss/manifests"),
        (str(REPO / "release-manifest.json"), "."),
        (str(REPO / "DESKTOP_CHANGELOG.md"), "."),
        *trust_datas,
        *netcdf_datas,
        *certifi_datas,
        *calibration_datas,
    ],
    hiddenimports=[*trust_hidden, *netcdf_hidden, *calibration_hidden, *harness_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Optimizer analysis packages expose optional plotting/data/ML helpers.
    # GeoForge's calibration engine uses their numerical APIs only; plots are
    # produced by the app's own safe plotting tool. Excluding these prevents a
    # developer machine that happens to have torch/pandas installed from
    # silently adding hundreds of MB to a release.
    excludes=[
        "torch", "torchvision", "torchaudio", "pandas", "matplotlib",
        "PIL", "pyarrow", "IPython", "jedi", "botocore", "boto3",
        "fsspec", "lxml", "dask", "numba", "mpi4py", "pathos",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GeoForge Desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    # Build the runner's native architecture.  Hard-coding arm64 made the
    # best-effort Intel release job produce the wrong architecture.
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GeoForge Desktop",
)
app = BUNDLE(
    coll,
    name="GeoForge Desktop.app",
    icon=str(ICON),
    bundle_identifier="com.geoforge.desktop",
    info_plist={
        "CFBundleDisplayName": "GeoForge Desktop",
        "CFBundleName": "GeoForge Desktop",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": BUILD_NUMBER,
        "NSHighResolutionCapable": True,
    },
)
