# -*- mode: python ; coding: utf-8 -*-
"""Reproducible Windows GeoForge Desktop executable."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tomllib

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)


SOURCE = Path(SPECPATH).resolve()
REPO = SOURCE.parent
if sys.version_info >= (3, 13):
    raise RuntimeError(
        "Windows releases must be built with Python 3.11 or 3.12; "
        "pythonnet/WinForms deadlocks under Python 3.13."
    )
with (SOURCE / "pyproject.toml").open("rb") as version_file:
    VERSION = tomllib.load(version_file)["project"]["version"]
ICON = REPO / "assets" / "logo.ico"
KI_TOOLS_SOURCE = REPO / "ki_tools_common"


def portable_linux_datas(repo):
    """Ship Linux-readable source; PyInstaller's Windows PYZ is not portable.

    Use repository source roots only. Exclude local authority, settings and
    development caches, keeping case/document assets within shipped KIs.
    """
    excluded_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                     ".geoforge", ".venv", "venv", "node_modules", "flow-keys", "flow-registry"}
    excluded_files = {"kiss.toml", "status.json", "installation-test.json", ".geoforge-install.json",
                      "settings.json", ".DS_Store", ".env"}
    roots = (("kiss/kiss_cli", True), ("kiss/manifests", True),
             ("ki_tools_common", True), ("kiss/system_kis", False),
             ("kiss/data_kis", False), ("kiss/vendor", False))
    rows = []
    for relative, code in roots:
        folder = repo / relative
        if not folder.is_dir():
            raise RuntimeError("Required portable Linux source is missing: " + str(folder))
        for path in sorted(folder.rglob("*")):
            parts = path.relative_to(folder).parts
            if (any(p in excluded_dirs or p.endswith(".egg-info") for p in parts)
                    or (code and any(p in {"tests", "test"} for p in parts))
                    or path.name in excluded_files or path.name.startswith(".env.")
                    or path.suffix.lower() in {".pyc", ".pyo", ".key", ".pem"}):
                continue
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise RuntimeError("Portable Linux source cannot contain linked paths: " + str(path))
            if path.is_file():
                target = Path("linux-runtime") / path.relative_to(repo).parent
                rows.append((str(path), target.as_posix()))
    rows.append((str(repo / "kiss" / "pyproject.toml"), "linux-runtime/kiss"))
    return rows


# Development/stress-test scratch directories are not KI packages.
ki_packages = sorted(p for p in (REPO / "models").iterdir()
                     if p.is_dir() and (p / "SKILL.md").is_file()
                     and not p.name.startswith("_"))
if len(ki_packages) != 127:
    raise RuntimeError(f"Expected 127 canonical KI packages, found {len(ki_packages)}")


def git_links(repo):
    """KI paths Git records as symbolic links.

    A core.symlinks=false checkout turns them into small text files; a linked
    checkout makes real links. Neither form is shipped, so every checkout
    bundles the same bytes.
    """
    try:
        listing = subprocess.run(["git", "-C", str(repo), "ls-files", "-s", "--", "models", "kiss/data_kis"],
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {os.path.normcase(os.path.abspath(repo / line.split("\t", 1)[1]))
            for line in listing.splitlines() if line.startswith("120000 ")}


def stage_ki_library():
    """Bundle clean KI copies and record each one's content digest.

    Development caches and links never ship. The digests go into a generated
    module in the executable's archive, where the KI guard reads them: a
    bundled KI whose bytes match is accepted in any folder, even on a computer
    whose one-time trust migration happened long ago; any edited byte still
    needs KDT.
    """
    stage = Path(workpath) / "ki-library"
    if stage.exists():
        shutil.rmtree(stage)
    links = git_links(REPO)

    def skipped(directory, names):
        out = set()
        for name in names:
            path = os.path.join(directory, name)
            if (name == "__pycache__" or name.endswith((".pyc", ".pyo")) or os.path.islink(path)
                    or getattr(os.lstat(path), "st_file_attributes", 0) & 0x400
                    or os.path.normcase(os.path.abspath(path)) in links):
                out.add(name)
        return out

    for package in ki_packages:
        shutil.copytree(package, stage / "models" / package.name, ignore=skipped)
    shutil.copytree(SOURCE / "data_kis", stage / "data_kis", ignore=skipped)
    sys.path.insert(0, str(SOURCE))
    from kiss_cli import ki_verification
    fingerprints = {}
    for root in sorted([*(stage / "models").iterdir(), *(stage / "data_kis").iterdir()]):
        if not (root / "SKILL.md").is_file():
            continue
        if root.name in fingerprints:
            raise RuntimeError("Duplicate bundled KI name: " + root.name)
        digest = ki_verification.content_digest(root)
        if not digest:
            raise RuntimeError("Cannot fingerprint bundled KI: " + str(root))
        fingerprints[root.name] = digest
    generated = Path(workpath) / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (generated / "geoforge_bundled_library.py").write_text(
        '"""Generated by GeoForgeDesktopWindows.spec: content digests of the bundled KIs."""\n'
        f"FINGERPRINTS = {json.dumps(fingerprints, indent=1, sort_keys=True)}\n",
        encoding="utf-8")
    return stage, generated


KI_STAGE, GENERATED = stage_ki_library()
version_tuple = tuple(int(part) for part in VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
                     mask=0x3f, flags=0, OS=0x40004, fileType=1,
                     subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("FileDescription", "GeoForge Desktop"),
        StringStruct("FileVersion", VERSION),
        StringStruct("ProductName", "GeoForge Desktop"),
        StringStruct("ProductVersion", VERSION),
        StringStruct("OriginalFilename", "GeoForge Desktop.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)

trust_datas, trust_binaries, trust_hidden = collect_all("truststore")
netcdf_datas, netcdf_binaries, netcdf_hidden = collect_all("netCDF4")
certifi_datas = collect_data_files("certifi")
webview_hidden = []
calibration_datas = []
for distribution in ("numpy", "PyYAML", "spotpy", "pymoo", "moocore"):
    calibration_datas.extend(copy_metadata(distribution))
calibration_binaries = collect_dynamic_libs("pymoo")
calibration_hidden = [
    "numpy", "scipy", "yaml", "spotpy",
    "spotpy.database.ram",
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
    "PIL.Image", "PIL.PngImagePlugin",
    "kiss_cli.artifact_archive",
    "kiss_cli.execution_continuation",
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
    "ki_tools_common.flow.project_tools",
    "ki_tools_common.flow.project_data_formats",
    "ki_tools_common.flow.stdout_artifacts",
    "ki_tools_common.flow.declared_outputs",
    "ki_tools_common.flow.build_data",
    "ki_tools_common.flow.decisions",
    "ki_tools_common.flow.declared",
    "ki_tools_common.flow.ki_inputs",
]

a = Analysis(
    [str(SOURCE / "kiss_entry.py")],
    pathex=[str(SOURCE), str(KI_TOOLS_SOURCE), str(GENERATED)],
    binaries=[*trust_binaries, *netcdf_binaries, *calibration_binaries],
    datas=[
        *portable_linux_datas(REPO),
        (str(SOURCE / "kiss_cli" / "web"), "kiss_cli/web"),
        # Launched by the configured Python beside execution.__file__, outside PYZ.
        (str(SOURCE / "kiss_cli" / "_project_data_worker.py"), "kiss_cli"),
        # Runtime-data receipts hash these exact source bytes, including in PYZ builds.
        (str(SOURCE / "kiss_cli" / "runtime_data.py"), "kiss_cli"),
        (str(SOURCE / "system_kis"), "system_kis"),
        (str(KI_STAGE / "data_kis"), "data_kis"),
        *((str(KI_STAGE / "models" / p.name), f"models/{p.name}") for p in ki_packages),
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
    hiddenimports=[
        *trust_hidden, *netcdf_hidden, *webview_hidden, *calibration_hidden, *harness_hidden,
        "geoforge_bundled_library",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "torchaudio", "pandas", "matplotlib",
        "pyarrow", "IPython", "jedi", "botocore", "boto3",
        "fsspec", "lxml", "dask", "numba", "mpi4py", "pathos",
        "tensorflow", "keras", "cv2", "sklearn", "xarray", "h5py",
        "pyproj", "rasterio", "rioxarray",
        "webview", "pythonnet", "clr", "clr_loader", "PySide6", "qtpy",
    ],
    noarchive=False,
    optimize=0,
)
# A console companion forwards approved IPC commands without requiring Python
# on PATH. Its runtime/DLLs live beside the same self-contained desktop bundle.
bridge = Analysis(
    [str(SOURCE / "agent_bridge_entry.py")],
    pathex=[str(SOURCE), str(KI_TOOLS_SOURCE)],
    binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=a.excludes, noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
bridge_pyz = PYZ(bridge.pure)
bridge_exe = EXE(
    bridge_pyz, bridge.scripts, [], exclude_binaries=True,
    name="geoforge-agent-bridge", debug=False, strip=False, upx=False,
    console=True, icon=str(ICON), version=version_info,
)

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
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=version_info,
)
coll = COLLECT(
    exe,
    bridge_exe,
    a.binaries,
    a.datas,
    bridge.binaries,
    bridge.datas,
    strip=False,
    upx=False,
    name=f"GeoForge Desktop {VERSION} Windows",
)
