"""Synthetic transport/response fixtures; not proof of real MPI/model execution."""
from dataclasses import dataclass
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from kiss_cli import dependency_capabilities as cap


@dataclass(frozen=True)
class Binding:
    distro: str = "Ubuntu"
    user: str = "fixture"
    workspace: str = "/home/fixture/.local/share/geoforge/runtimes/" + "a" * 32
    workspace_id: str = "a" * 32
    python: str = "/usr/bin/python3"


def h(data):
    return hashlib.sha256(data).hexdigest()


def outputs(seed):
    mpi = []
    for rank in (0, 1):
        peer = 1-rank
        values = (rank, 2, seed+peer*101, seed*3+peer*7, -seed+peer*29,
                  2*seed+101, 6*seed+7, -2*seed+29, seed*11+43)
        mpi.append("GEOF_MPI|" + "|".join(map(str, values)))
    reader = {"seed": seed, "model": "NETCDF4",
              "values": [[seed+100*i+7*j for i in range(1, 4)] for j in range(1, 5)],
              "filters": {"zlib": True, "shuffle": True, "complevel": 1}}
    return {"mpi.stdout": ("\n".join(mpi)+"\n").encode(),
            "netcdf.stdout": f"GEOF_NETCDF|{seed}|3|{12*seed+2610}\n".encode(),
            "reader.stdout": ("GEOF_READER|"+json.dumps(reader)+"\n").encode(),
            "ncdump.stdout": b"netCDF-4\n", "probe.nc": b"\x89HDF\r\n\x1a\nfixture"}


def provenance():
    packages = {name: {"status": "ii \t1.0\tamd64",
                       "origins": [["Ubuntu", "noble", "archive.ubuntu.com"]]}
                for name in cap.PACKAGES}
    names = ("/usr/lib/libmpi.so.40", "/usr/lib/libnetcdff.so.7",
             "/usr/lib/libnetcdf.so.19", "/usr/lib/libhdf5_serial.so.103")
    files = {name: {"path": name, "sha256": h(name.encode()), "bytes": 99,
                    "package": "libopenmpi-dev"} for name in names}
    return packages, files, {"mpi": [names[0]], "netcdf": list(names[1:]), "reader": list(names[2:])}


class Backend:
    """Emulates exact transport bytes; functional output checks remain real."""
    def __init__(self):
        self.files = {}
        self.identity = "1" * 64
        self.calls = []
        self.change_outputs = lambda result: result
        self.change_evidence = lambda result: result
        self.current_system_changed = False
        self.result_status = "finished"
        self.result_returncode = 0
        self.binary_sha = "a" * 64

    def inspect(self, binding):
        return {"identity_sha256": self.identity, "transport": {"request_id": uuid.uuid4().hex}}

    def write_files(self, binding, files):
        for path, data in files.items():
            assert ".." not in path.split("/") and not path.startswith("/")
            assert path not in self.files or self.files[path] == data
            self.files[path] = data

    def read_files(self, binding, paths):
        return {path: {"data": self.files[path], "sha256": h(self.files[path]),
                       "bytes": len(self.files[path])} for path in paths}

    def run(self, binding, argv, **kwargs):
        self.calls.append((argv, kwargs))
        prefix = kwargs["cwd"][len(binding.workspace)+1:]
        assert argv == ["/usr/bin/python3", "-I", "-S", kwargs["cwd"]+"/driver.py"]
        assert self.files[prefix+"/driver.py"] == cap.DRIVER_SOURCE.encode()
        if kwargs.get("stop") and kwargs["stop"]():
            return SimpleNamespace(status="cancelled", returncode=None, detail="stopped", stderr="", stdout="")
        request = json.loads(self.files[prefix+"/request.json"])
        if request["mode"] == "verify":
            for name in cap.ARTIFACTS:
                self.files.setdefault(prefix+"/"+name, b"synthetic artifact")
            actual = self.change_outputs(outputs(request["seed"]))
            self.files.update({prefix+"/"+name: data for name, data in actual.items()})
            packages, system, loaded = provenance()
            result = {"seed": request["seed"], "workspace": kwargs["cwd"],
                      "packages": packages, "system_files": system, "loaded_libraries": loaded,
                      "linkage": {"mpi-probe": loaded["mpi"], "netcdf-probe": loaded["netcdf"]},
                      "artifacts": {name: {"sha256": h(self.files[prefix+"/"+name]),
                                           "bytes": len(self.files[prefix+"/"+name])}
                                    for name in cap.ARTIFACTS}}
            result = self.change_evidence(result)
        elif request["mode"] == "binary":
            expected = request["expected"]
            result = {"executable": request["executable"], "sha256": self.binary_sha, "bytes": 1000,
                      "libraries": expected["system_files"],
                      "mpi_imports": ["mpi_init_", "mpi_sendrecv_"],
                      "netcdf_imports": ["nf_open_", "nf_get_vara_int_"]}
        else:
            expected = request["expected"]
            old = expected["workspace"][len(binding.workspace)+1:]
            actual = {name: {"sha256": h(self.files[old+"/"+name]),
                             "bytes": len(self.files[old+"/"+name])}
                      for name in expected["artifacts"]}
            if actual != expected["artifacts"]:
                return SimpleNamespace(status="finished", returncode=2, detail="", stderr="Probe artifact bytes changed", stdout="")
            result = {key: copy.deepcopy(expected[key]) for key in
                      ("packages", "system_files", "artifacts", "linkage")}
            result["current"] = True
            if self.current_system_changed:
                first = next(iter(result["system_files"].values()))
                first["sha256"] = "f" * 64
        self.files[prefix+"/result.json"] = json.dumps(result).encode()
        return SimpleNamespace(status=self.result_status, returncode=self.result_returncode,
                               detail="", stderr="", stdout="GEOF_CAPABILITIES_OK")


@pytest.fixture
def authority(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path/"keys"))
    path = tmp_path/"host-profile"
    path.mkdir()
    return path


def test_success_is_signed_current_evidence_not_model_readiness(authority):
    backend = Backend()
    report = cap.verify(Binding(), authority=authority, backend=backend)
    assert report["profile"] == cap.PROFILE and report["model_readiness"] is False
    assert report["signature"]
    assert cap.require_current(report, Binding(), authority=authority, backend=backend) == report
    assert len(backend.calls) == 2  # verification once, current inventory once


@pytest.mark.parametrize("mutation", ["missing-rank", "duplicate-rank", "no-sendrecv", "no-reduction", "wrong-nonce"])
def test_noop_or_replayed_mpi_output_cannot_pass(authority, mutation):
    backend = Backend()
    def alter(result):
        rows = result["mpi.stdout"].decode().splitlines()
        if mutation == "missing-rank": rows = rows[:1]
        elif mutation == "duplicate-rank": rows[1] = rows[0]
        else:
            parts = rows[1].split("|")
            parts[3 if mutation == "no-sendrecv" else 6] = "0"
            rows[1] = "|".join(parts)
        result["mpi.stdout"] = ("\n".join(rows)+"\n").encode()
        return result
    backend.change_outputs = alter
    with pytest.raises(cap.CapabilityError, match="MPI ranks"):
        cap.verify(Binding(), authority=authority, backend=backend)


@pytest.mark.parametrize("name,replacement", [
    ("netcdf.stdout", b"GEOF_NETCDF|0|3|0\n"),
    ("reader.stdout", b"GEOF_READER|{}\n"),
    ("ncdump.stdout", b"classic\n"),
    ("probe.nc", b"not an HDF5 file"),
])
def test_successful_exit_without_real_netcdf_crosscheck_rejected(authority, name, replacement):
    backend = Backend()
    backend.change_outputs = lambda rows: {**rows, name: replacement}
    with pytest.raises(cap.CapabilityError):
        cap.verify(Binding(), authority=authority, backend=backend)


@pytest.mark.parametrize("change", ["workspace-lib", "missing-mpi", "untrusted-package", "missing-required", "missing-source", "other-workspace"])
def test_package_artifact_and_loaded_library_provenance_required(authority, change):
    backend = Backend()
    def alter(row):
        if change == "workspace-lib":
            row["loaded_libraries"]["mpi"] = ["/home/fixture/fake-mpi.so"]
        elif change == "missing-mpi": row["loaded_libraries"]["mpi"] = []
        elif change == "untrusted-package": row["packages"]["gfortran"]["origins"][0][0] = "agent"
        elif change == "missing-required": del row["packages"]["python3-apt"]
        elif change == "missing-source": del row["artifacts"]["mpi.f90"]
        else: row["workspace"] = "/other"
        return row
    backend.change_evidence = alter
    with pytest.raises(cap.CapabilityError):
        cap.verify(Binding(), authority=authority, backend=backend)


@pytest.mark.parametrize("changed", ["mpi.f90", "mpi-probe", "probe.nc", "mpi.stdout", "driver.py"])
def test_changed_probe_artifact_invalidates_receipt(authority, changed):
    backend = Backend()
    report = cap.verify(Binding(), authority=authority, backend=backend)
    backend.files[report["relative"]+"/"+changed] += b"tamper"
    with pytest.raises(cap.CapabilityError, match="changed"):
        cap.require_current(report, Binding(), authority=authority, backend=backend)


def test_changed_loaded_library_or_binding_invalidates(authority):
    backend = Backend()
    report = cap.verify(Binding(), authority=authority, backend=backend)
    backend.current_system_changed = True
    with pytest.raises(cap.CapabilityError, match="no longer current"):
        cap.require_current(report, Binding(), authority=authority, backend=backend)
    backend.current_system_changed = False
    backend.identity = "2" * 64
    with pytest.raises(cap.CapabilityError, match="different Linux runtime"):
        cap.require_current(report, Binding(), authority=authority, backend=backend)


def test_tampered_signature_rejected_before_transport(authority):
    backend = Backend()
    report = cap.verify(Binding(), authority=authority, backend=backend)
    report["evidence"]["seed"] += 1
    before = len(backend.calls)
    with pytest.raises(cap.CapabilityError, match="unauthenticated"):
        cap.require_current(report, Binding(), authority=authority, backend=backend)
    assert len(backend.calls) == before


def test_cancelled_probe_cannot_mint_receipt(authority):
    with pytest.raises(cap.CapabilityError, match="stopped"):
        cap.verify(Binding(), authority=authority, backend=Backend(), stop=lambda: True)


def test_profile_is_derived_from_requirements_not_model_name():
    assert cap.profiles_for_manifest({"model": "anything", "system_deps": ["mpif90", "nf-config"]}) == (cap.PROFILE,)
    assert cap.profiles_for_manifest({"model": "anything", "acquire": {"system_deps": ["mpicc", "nf-config"]}}) == (cap.PROFILE,)
    assert cap.profiles_for_manifest({"model": "WRF_Hydro", "python_deps": ["netCDF4"]}) == ()
    assert cap.profiles_for_manifest({"system_deps": ["gfortran", "nf-config"]}) == ()


def driver_namespace(tmp_path):
    tree = ast.parse(cap.DRIVER_SOURCE)
    assert isinstance(tree.body[-1], ast.Try)
    tree.body.pop()  # inspect driver helpers without running a guest operation
    namespace = {"__file__": str(tmp_path/"driver.py")}
    exec(compile(tree, "host-authored-driver", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("trusted,origin,verify_output", [
    (False, "Ubuntu", ""), (True, "agent", ""), (True, "Ubuntu", "??5?????? /usr/lib/fake.so"),
])
def test_guest_package_policy_rejects_fake_or_modified_system_package(tmp_path, monkeypatch, trusted, origin, verify_output):
    ns = driver_namespace(tmp_path)
    installed = SimpleNamespace(origins=[SimpleNamespace(trusted=trusted, origin=origin,
                                                        archive="noble", site="archive.ubuntu.com")])
    ns["package_cache"] = {"libmpi": SimpleNamespace(is_installed=True, installed=installed)}
    ns["run"] = lambda argv, **kw: (verify_output if "--verify" in argv else "ii \t1.0\tamd64")
    with pytest.raises(ValueError, match="trusted Ubuntu|verification differs"):
        ns["package"]("libmpi")


def test_sources_compile_as_python_and_preserve_real_native_operations():
    compile(cap.DRIVER_SOURCE, "driver.py", "exec")
    compile(cap.READER_SOURCE, "reader.py", "exec")
    for operation in ("MPI_SENDRECV", "MPI_ALLREDUCE", "MPI_BCAST", "MPI_GATHER", "MPI_ABORT"):
        assert "call " + operation in cap.MPI_SOURCE
    for operation in ("nf90_create", "nf90_put_var", "nf90_close", "nf90_open", "nf90_get_var", "nf90_def_var_deflate"):
        assert operation in cap.NETCDF_SOURCE
    assert "NF90_NETCDF4" in cap.NETCDF_SOURCE and "/proc/self/maps" in cap.MPI_SOURCE
    assert "LD_PRELOAD" not in cap.DRIVER_SOURCE


def test_loaded_mapping_inventory_excludes_temporary_nonexecutable_data(capsys):
    tree = ast.parse(cap.READER_SOURCE)
    loop = next(node for node in tree.body if isinstance(node, ast.For))
    rows = "\n".join([
        "100-200 r-xp 0 01:00 1 /usr/lib/libmpi.so.40",
        "200-300 rw-s 0 01:00 2 /tmp/pmix-gds-shmem.session",
        "300-400 r--p 0 01:00 3 /tmp/data",
    ])
    fake_path = lambda _: SimpleNamespace(read_text=lambda: rows)
    exec(compile(ast.Module(body=[loop], type_ignores=[]), "map-filter", "exec"),
         {"pathlib": SimpleNamespace(Path=fake_path)})
    assert capsys.readouterr().out == "GEOF_MAP|READER|0|/usr/lib/libmpi.so.40\n"
    assert "read(line, *, iostat=ios) address, permissions" in cap._MAPS
    assert "if (index(permissions, 'x') == 0) cycle" in cap._MAPS


def test_binary_receipt_binds_exact_executable_and_library_resolution(authority):
    backend = Backend()
    binding = Binding()
    report = cap.verify(binding, authority=authority, backend=backend)
    executable = binding.workspace + "/models/scientific-engine"
    binary = cap.verify_binary(report, binding, executable, authority=authority, backend=backend)
    assert binary["model_readiness"] is False
    assert cap.require_binary_current(binary, report, binding, executable,
                                      authority=authority, backend=backend) == binary
    backend.binary_sha = "b" * 64
    with pytest.raises(cap.CapabilityError, match="library bytes changed"):
        cap.require_binary_current(binary, report, binding, executable, authority=authority, backend=backend)


def test_binary_receipt_cannot_be_reused_for_another_path(authority):
    backend = Backend()
    binding = Binding()
    report = cap.verify(binding, authority=authority, backend=backend)
    executable = binding.workspace + "/engine"
    binary = cap.verify_binary(report, binding, executable, authority=authority, backend=backend)
    before = len(backend.calls)
    with pytest.raises(cap.CapabilityError, match="unauthenticated"):
        cap.require_binary_current(binary, report, binding, executable+"-other", authority=authority, backend=backend)
    assert len(backend.calls) == before


@pytest.mark.parametrize("symbols", [[], ["mpi_init_", "nf_open_", "nf_get_vara_int_"],
                                     ["mpi_init_", "mpi_sendrecv_"],
                                     ["mpi_init_", "mpi_sendrecv_", "nf_open_"]])
def test_noop_elf_without_required_dynamic_operations_rejected(tmp_path, symbols):
    ns = driver_namespace(tmp_path)
    text = "\n".join(" 1: 000000 0 FUNC GLOBAL DEFAULT UND "+name for name in symbols)
    with pytest.raises(ValueError, match="no real"):
        ns["import_contract"](text)


def test_versioned_dynamic_symbols_are_inspected_not_version_indices(tmp_path):
    ns = driver_namespace(tmp_path)
    symbols = ["mpi_init_thread_", "mpi_sendrecv_", "__netcdf_MOD_nf90_open", "__netcdf_MOD_nf90_create"]
    text = "\n".join(" 1: 000000 0 FUNC GLOBAL DEFAULT UND "+name+"@VERSION_4 (3)" for name in symbols)
    mpi, netcdf = ns["import_contract"](text)
    assert mpi == symbols[:2]
    assert netcdf == sorted(name.lower() for name in symbols[2:])


@pytest.mark.parametrize("environment", [{"LD_PRELOAD": "/tmp/fake.so"}, {"LD_AUDIT": "/usr/lib/a.so"},
                                         {"LD_LIBRARY_PATH": "/tmp"}, {"LD_LIBRARY_PATH": "/usr/lib:"},
                                         {"GLIBC_TUNABLES": "anything"}])
def test_loader_environment_cannot_redirect_verified_library(environment):
    packages, files, loaded = provenance()
    with pytest.raises(cap.CapabilityError):
        cap.validate_loader_environment({"evidence": {"system_files": files}}, environment)


def test_official_loader_directory_and_normal_environment_allowed():
    packages, files, loaded = provenance()
    cap.validate_loader_environment({"evidence": {"system_files": files}},
                                    {"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": "/usr/lib"})


@pytest.mark.parametrize("tag", ["AUDIT", "DEPAUDIT", "FILTER", "AUXILIARY"])
def test_loader_audit_modules_rejected_before_listing(tmp_path, tag):
    ns = driver_namespace(tmp_path)
    ns["run"] = lambda *a, **kw: "0x01 (" + tag + ") [evil.so]"
    with pytest.raises(ValueError, match="audit/filter"):
        ns["rpaths"](tmp_path / "engine")


def test_only_authenticated_library_can_use_absent_build_path(tmp_path):
    ns = driver_namespace(tmp_path)
    missing = (tmp_path / "absent-build" / "libs").as_posix()
    # Linux paths are used in the embedded guest program. Avoid Windows Path's
    # drive interpretation in this isolated path-classification test.
    import pathlib
    ns["pathlib"] = SimpleNamespace(Path=pathlib.PurePosixPath)
    class Missing(pathlib.PurePosixPath):
        def exists(self): return False
        def resolve(self, strict=False):
            if strict: raise FileNotFoundError(str(self))
            return self
    ns["pathlib"] = SimpleNamespace(Path=Missing)
    ns["run"] = lambda *a, **kw: "0x01 (RUNPATH) [/build/official-package/lib]"
    calls=[]
    ns["absent_official_path"] = lambda p: calls.append(p) or {"absent":p,"ancestor":"/"}
    with pytest.raises(FileNotFoundError): ns["rpaths"](Missing("/runtime/engine"))
    assert calls == []
    assert ns["rpaths"](Missing("/usr/lib/official.so"), official_library=True) == [
        {"absent":"/build/official-package/lib","ancestor":"/"}]
    assert calls == ["/build/official-package/lib"]


@pytest.mark.parametrize("value", ["relative/path", "/build/$ORIGIN/lib", "/build/../elsewhere"])
def test_absent_system_search_path_rejects_aliases(tmp_path, value):
    ns = driver_namespace(tmp_path)
    import pathlib
    ns["pathlib"] = SimpleNamespace(Path=pathlib.PurePosixPath)
    with pytest.raises(ValueError, match="Unsupported absent"):
        ns["absent_official_path"](value)


@pytest.mark.parametrize("uid,mode,writable,exists,linked", [
    (1000, 0o40755, False, False, False), (0, 0o40777, False, False, False),
    (0, 0o40755, True, False, False), (0, 0o40755, False, True, False),
    (0, 0o40755, False, False, True),
])
def test_absent_build_search_path_requires_immutable_root_parent(tmp_path, uid, mode, writable, exists, linked):
    ns = driver_namespace(tmp_path)
    import pathlib
    class VirtualPath(pathlib.PurePosixPath):
        def exists(self): return str(self) == "/" or (exists and str(self) == "/build/lib")
        def is_symlink(self): return linked and str(self) == "/build"
        def is_dir(self): return str(self) == "/"
        def lstat(self): return SimpleNamespace(st_uid=uid, st_gid=0, st_mode=mode, st_dev=1, st_ino=2)
        stat = lstat
    ns["pathlib"] = SimpleNamespace(Path=VirtualPath)
    ns["os"] = SimpleNamespace(W_OK=2, access=lambda *_: writable)
    with pytest.raises(ValueError): ns["absent_official_path"]("/build/lib")


def test_absent_build_search_path_records_ancestor_identity(tmp_path):
    ns = driver_namespace(tmp_path)
    import pathlib
    class VirtualPath(pathlib.PurePosixPath):
        def exists(self): return str(self) == "/"
        def is_symlink(self): return False
        def is_dir(self): return str(self) == "/"
        def lstat(self): return SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o40755, st_dev=4, st_ino=5)
        stat = lstat
    ns["pathlib"] = SimpleNamespace(Path=VirtualPath)
    ns["os"] = SimpleNamespace(W_OK=2, access=lambda *_: False)
    assert ns["absent_official_path"]("/build/lib") == {
        "absent":"/build/lib", "ancestor":"/", "device":4, "inode":5,
        "mode":0o40755, "uid":0, "gid":0}
