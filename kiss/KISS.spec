# -*- mode: python ; coding: utf-8 -*-
"""Generic GeoForge Desktop bundle — Linux and Windows.

The macOS build has its own spec because it produces an .app bundle with a
plist and a fixed architecture. This one carries the parts that are not about
Apple: which modules must be frozen, which trees travel as data, and what must
never be dragged in.

The reason a spec exists at all rather than a line of --add-data flags is the
harness. ``--add-data "ki_tools_common:ki_tools_common"`` copies the
distribution root, so the import package lands one level below the name it is
mounted under and ``ki_tools_common.harness`` resolves to a namespace package
with nothing in it. The application caught that and substituted a weaker prompt,
so a build could ship for weeks with the KI execution contract silently absent.
Listing the harness modules as hiddenimports makes PyInstaller freeze them as
code; the data copy stays because model tools run in their own interpreters and
read those files from disk.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, copy_metadata

VERSION = "0.6.43"
SOURCE = Path(SPECPATH).resolve()          # the kiss/ directory
REPO = SOURCE.parent
# ki_tools_common sits beside kiss/, so '../ki_tools_common' from this spec.
KI_TOOLS_SOURCE = (SOURCE / '../ki_tools_common').resolve()

trust_datas, trust_binaries, trust_hidden = collect_all("truststore")

# The calibration stack is optional here: a Linux or Windows runner that has
# not installed it should still produce a working application rather than fail
# the release. Anything missing is simply not frozen.
calibration_datas = []
for distribution in ("numpy", "PyYAML", "spotpy", "pymoo", "moocore"):
    try:
        calibration_datas.extend(copy_metadata(distribution))
    except Exception:
        pass
try:
    calibration_binaries = collect_dynamic_libs("pymoo")
except Exception:
    calibration_binaries = []
calibration_hidden = [
    "numpy", "scipy", "yaml", "spotpy",
    "pymoo.core.problem", "pymoo.optimize",
    "pymoo.algorithms.moo.nsga2", "pymoo.algorithms.moo.nsga3",
    "pymoo.algorithms.moo.moead", "pymoo.util.ref_dirs",
]

# Frozen as code, not only copied as files.
harness_hidden = [
    "ki_tools_common",
    "ki_tools_common.harness",
    "ki_tools_common.harness.ki_harness",
    "ki_tools_common.harness.ki_path",
    "ki_tools_common.harness.ki_attention",
    "ki_tools_common.harness.agent_spawn",
]

datas = [
    (str(SOURCE / "kiss_cli" / "web"), "kiss_cli/web"),
    (str(REPO / "models"), "models"),
    (str(REPO / "ki_tools_common"), "ki_tools_common"),
    (str(SOURCE / "manifests"), "kiss/manifests"),
    *trust_datas,
    *calibration_datas,
]
vendor = SOURCE / "vendor" / "agent-calibration-framework"
if vendor.is_dir():
    datas.append((str(vendor), "agent-calibration-framework"))

a = Analysis(
    [str(SOURCE / "kiss_entry.py")],
    pathex=[str(SOURCE), str(KI_TOOLS_SOURCE)],
    binaries=[*trust_binaries, *calibration_binaries],
    datas=datas,
    hiddenimports=[*trust_hidden, *calibration_hidden, *harness_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # A developer machine with torch or pandas installed would otherwise add
    # hundreds of megabytes that nothing in the application imports.
    excludes=[
        "torch", "torchvision", "torchaudio", "pandas", "matplotlib",
        "PIL", "pyarrow", "IPython", "jedi", "botocore", "boto3",
        "fsspec", "lxml", "dask", "numba", "mpi4py", "pathos",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# One file, because the Linux and Windows downloads are a single artefact the
# user runs directly rather than an application directory.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GeoForge-Desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
