# -*- mode: python ; coding: utf-8 -*-
"""Generic self-contained GeoForge Desktop bundle for Linux and Windows.

The macOS build uses ``GeoForgeDesktop.spec`` because it produces an app
bundle.  This spec records the shared runtime contract for the other desktop
platforms, including the harness/flow modules that must be frozen as Python
code rather than merely copied as loose source.
"""

from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)


SOURCE = Path(SPECPATH).resolve()
REPO = SOURCE.parent
with (SOURCE / "pyproject.toml").open("rb") as version_file:
    VERSION = tomllib.load(version_file)["project"]["version"]
KI_TOOLS_SOURCE = REPO / "ki_tools_common"
APP_NAME = "GeoForge Desktop" if sys.platform == "win32" else "GeoForge-Desktop"

trust_datas, trust_binaries, trust_hidden = collect_all("truststore")
netcdf_datas, netcdf_binaries, netcdf_hidden = collect_all("netCDF4")
certifi_datas = collect_data_files("certifi")
calibration_datas = []
for distribution in ("numpy", "PyYAML", "spotpy", "pymoo", "moocore"):
    calibration_datas.extend(copy_metadata(distribution))
calibration_binaries = collect_dynamic_libs("pymoo")
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

datas = [
    (str(SOURCE / "kiss_cli" / "web"), "kiss_cli/web"),
    (str(REPO / "models"), "models"),
    (str(SOURCE / "system_kis"), "system_kis"),
    (str(REPO / "ki_tools_common"), "ki_tools_common"),
    (str(SOURCE / "manifests"), "kiss/manifests"),
    (str(REPO / "release-manifest.json"), "."),
    (str(REPO / "DESKTOP_CHANGELOG.md"), "."),
    *trust_datas,
    *netcdf_datas,
    *certifi_datas,
    *calibration_datas,
]
vendor = SOURCE / "vendor" / "agent-calibration-framework"
if vendor.is_dir():
    datas.append((str(vendor), "agent-calibration-framework"))

a = Analysis(
    [str(SOURCE / "kiss_entry.py")],
    pathex=[str(SOURCE), str(KI_TOOLS_SOURCE)],
    binaries=[*trust_binaries, *netcdf_binaries, *calibration_binaries],
    datas=datas,
    hiddenimports=[*trust_hidden, *netcdf_hidden, *calibration_hidden, *harness_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=sys.platform != "win32",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
