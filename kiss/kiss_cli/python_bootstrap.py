"""Host-owned, version-only CPython bootstrap for an active fresh setup.

The Windows distribution is the Python project's fixed ``python`` NuGet
package. No provider URL, executable, path or script is accepted. Installing
it grants no model readiness, KI edit approval or scientific verification.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from . import install, ki_guard, setup_runtime, tls

_ORIGIN = "https://api.nuget.org"
_FLAT = _ORIGIN + "/v3-flatcontainer/python/"
_REGISTRATION = _ORIGIN + "/v3/registration5-gz-semver2/python/"
_VERSION = re.compile(r"3\.([0-9]{1,2})(?:\.([0-9]{1,3}))?\Z")
_STABLE = re.compile(r"3\.[0-9]{1,2}\.[0-9]{1,3}\Z")
_MAX_PACKAGE = 128 * 1024 * 1024
_MAX_EXPANDED = 512 * 1024 * 1024
_MAX_MEMBERS = 20000
_MAX_JSON = 4 * 1024 * 1024
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def _url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.nuget.org"
            or parsed.query or parsed.fragment or "%" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or not parsed.path.startswith(("/v3-flatcontainer/python/",
                "/v3/registration5-gz-semver2/python/", "/v3/catalog0/data/"))):
        raise ValueError("Python package metadata must stay on the official NuGet HTTPS origin")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        _url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def _opener():
    return urllib.request.build_opener(_Redirects(),
        urllib.request.HTTPSHandler(context=tls.context()))


def _read_url(url, *, limit, destination=None, expected_size=None, expected_hash=None):
    """Bound every response; short read timeouts and polling honour GUI Stop."""
    install.check_cancelled()
    digest, count, data = hashlib.sha512(), 0, bytearray()
    started = time.monotonic()
    request = urllib.request.Request(_url(url), headers={"User-Agent": "GeoForge-Python-Bootstrap/1"})
    output = None
    try:
        with _opener().open(request, timeout=10) as response:
            _url(response.geturl())
            length = response.headers.get("Content-Length")
            if length and (int(length) > limit or
                    (expected_size is not None and int(length) != expected_size)):
                raise ValueError("Python package response length does not match its bounded catalog metadata")
            if destination is not None:
                output = Path(destination).open("xb")
            while True:
                install.check_cancelled()
                if time.monotonic() - started > 300:
                    raise TimeoutError("Python package download exceeded five minutes")
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > limit:
                    raise ValueError("Python package response exceeds its size limit")
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
                else:
                    data.extend(chunk)
        install.check_cancelled()
        if expected_size is not None and count != expected_size:
            raise ValueError("Python package size differs from its official catalog")
        if expected_hash is not None and digest.digest() != expected_hash:
            raise ValueError("Python package SHA512 differs from its official catalog")
        return bytes(data)
    finally:
        if output is not None:
            output.close()


def _json(url):
    raw = _read_url(url, limit=_MAX_JSON)
    # NuGet's registration5-gz endpoint sends gzip even without an explicit
    # Accept-Encoding header. Bound expansion as well as transferred bytes.
    if raw.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(_MAX_JSON + 1)
        if len(raw) > _MAX_JSON:
            raise ValueError("Python package metadata expanded size exceeds its limit")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("Invalid official Python package metadata")
    return doc


def resolve_package(version):
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("Python version must be a stable minor or patch, for example 3.12 or 3.12.10")
    if int(version.split(".")[1]) < 9:
        raise ValueError("The managed Python bootstrap requires Python 3.9 or newer")
    if len(version.split(".")) == 2:
        versions = _json(_FLAT + "index.json").get("versions", [])
        available = [v for v in versions if isinstance(v, str) and _STABLE.fullmatch(v)
                     and v.startswith(version + ".")]
        if not available:
            raise ValueError("No stable official Python package is available for " + version)
        version = max(available, key=lambda v: tuple(map(int, v.split("."))))
    package_url = _FLAT + version + "/python." + version + ".nupkg"
    registration = _json(_REGISTRATION + version + ".json")
    catalog_url = registration.get("catalogEntry", "")
    if (registration.get("packageContent") != package_url or not registration.get("listed")
            or not isinstance(catalog_url, str)
            or not re.fullmatch(re.escape(_ORIGIN) +
                r"/v3/catalog0/data/[0-9.]+/python\." + re.escape(version) + r"\.json", catalog_url)):
        raise ValueError("Official Python package registration does not match the requested package")
    catalog = _json(catalog_url)
    if (catalog.get("id", "").lower() != "python" or catalog.get("version") != version
            or catalog.get("packageHashAlgorithm") != "SHA512"):
        raise ValueError("Official Python package identity or checksum algorithm is invalid")
    try:
        checksum = base64.b64decode(catalog["packageHash"], validate=True)
        size = catalog["packageSize"]
        if len(checksum) != 64 or type(size) is not int or not 0 < size <= _MAX_PACKAGE:
            raise ValueError("invalid package bounds")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Official Python package checksum or size is invalid") from exc
    return {"id": "python", "version": version, "url": package_url,
            "catalog": catalog_url, "sha512": checksum.hex(), "size": size}


def _inside(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if (root.resolve() != root or path == root or root not in path.parents
            or path.resolve() != path):
        raise ValueError("Managed Python paths must stay inside the unaliased setup workspace")
    return path


def _members(archive):
    members = archive.infolist()
    if len(members) > _MAX_MEMBERS:
        raise ValueError("Python package contains too many members")
    total, seen, files, entries = 0, set(), set(), []
    for member in members:
        install.check_cancelled()
        name = member.filename.rstrip("/")
        parts = name.split("/")
        mode = member.external_attr >> 16
        if (not name or "\\" in name or "\\" in member.orig_filename
                or "\x00" in member.orig_filename or name.startswith("/")
                or member.flag_bits & 1 or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                or member.external_attr & 0x400
                or any(part in {"", ".", ".."} or ":" in part or part[-1:] in {".", " "}
                       or part.split(".", 1)[0].lower() in _RESERVED for part in parts)):
            raise ValueError("Python package contains an unsafe ZIP member")
        key = name.casefold()
        if key in seen or any("/".join(parts[:i]).casefold() in files for i in range(1, len(parts))):
            raise ValueError("Python package contains colliding ZIP paths")
        if not member.is_dir():
            if any(old.startswith(key + "/") for old in seen):
                raise ValueError("Python package contains colliding ZIP paths")
            files.add(key)
        seen.add(key)
        total += member.file_size
        if member.file_size < 0 or total > _MAX_EXPANDED:
            raise ValueError("Python package expanded size exceeds its limit")
        entries.append((member, PurePosixPath(name)))
    return entries


def _extract(package, destination, root):
    destination = _inside(root, destination)
    if destination.exists():
        raise ValueError("Python package destination already exists")
    with zipfile.ZipFile(package) as archive:
        members = _members(archive)  # validate the whole index before writing
        destination.mkdir()
        expanded = 0
        for member, relative in members:
            install.check_cancelled()
            target = _inside(destination, destination.joinpath(*relative.parts))
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("xb") as output:
                count = 0
                while True:
                    install.check_cancelled()
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    expanded += len(chunk)
                    if count > member.file_size or expanded > _MAX_EXPANDED:
                        raise ValueError("Python ZIP content exceeds its declared bounds")
                    output.write(chunk)
                if count != member.file_size:
                    raise ValueError("Python ZIP content has an invalid length")


_PROBE = ("import json,sys,ssl,sqlite3,venv,ensurepip; "
          "c=sqlite3.connect(':memory:'); c.execute('select 1').fetchone(); c.close(); "
          "ssl.create_default_context(); "
          "print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),"
          "'executable':sys.executable,'prefix':sys.prefix,'bits':64 if sys.maxsize>2**32 else 32,"
          "'openssl':ssl.OPENSSL_VERSION,'sqlite':sqlite3.sqlite_version,"
          "'ensurepip':ensurepip.version()}))")


def _probe(executable, prefix, version):
    rc, output = install._run([str(executable), "-I", "-B", "-c", _PROBE],
                             cwd=prefix, timeout=60)
    try:
        result = json.loads(output.strip())
        if (rc != 0 or result["version"] != version or result["bits"] != 64
                or not Path(result["executable"]).samefile(executable)
                or Path(result["prefix"]).resolve() != Path(prefix).resolve()):
            raise ValueError("identity mismatch")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Managed Python failed its identity/ssl/sqlite3/venv/ensurepip check: "
                         + output[-1000:]) from exc
    return result


def _acquire(root, binaries, version, emit):
    package = resolve_package(version)
    emit("Preparing official CPython " + package["version"] + " for this installation.\n")
    binaries = _inside(root, binaries)
    binaries.mkdir(parents=True, exist_ok=True)
    folder = _inside(root, binaries / ("python-" + package["version"] + "-" + uuid.uuid4().hex[:12]))
    archive = _inside(root, Path(str(folder) + ".nupkg"))
    _read_url(package["url"], limit=_MAX_PACKAGE, destination=archive,
              expected_size=package["size"], expected_hash=bytes.fromhex(package["sha512"]))
    _extract(archive, folder, root)
    base = folder / "tools" / "python.exe"
    identity = _probe(base, base.parent, package["version"])
    return base, package, identity


def _audit(root, path, document):
    path = _inside(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _inside(root, path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp"))
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(document, output, indent=2)
    _inside(root, path)
    temporary.replace(path)


def prepare_python_runtime(ticket, ki, live_ki, cfg, *, library_root, manifest, version, emit=None):
    """Provision one official runtime at the already-bound fresh venv path.

    A failed replacement is retained for diagnosis and the previous environment
    is restored. Model packages and all ordinary setup/preflight checks follow
    separately through the existing installer.
    """
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("The managed Python download currently supports Windows x64")
    emit = emit or (lambda text: None)
    with ki_guard.operation(Path(cfg.root)):
        setup_runtime.require_current(ticket, ki, live_ki, cfg,
                                      library_root=library_root, manifest=manifest)
        root = Path(cfg.root).absolute()
        environment = _inside(root, cfg.roles["python_env"])
        executable = _inside(root, cfg.python)
        binaries = _inside(root, cfg.roles["binaries"])
        if (executable != environment / "Scripts" / "python.exe"
                or environment == binaries or environment in binaries.parents
                or binaries in environment.parents or not environment.is_dir()):
            raise ValueError("Managed bootstrap requires the selected workspace venv and a separate binaries role")
        protected = [Path(live_ki.root).absolute(), Path(ki.root).absolute(),
                     *[Path(value).absolute() for key, value in cfg.roles.items() if key != "python_env"]]
        if any(path == environment or environment in path.parents for path in protected):
            raise ValueError("The selected venv must not contain a KI, helper or another configured role")
        immutable = [Path(live_ki.root).absolute(), Path(ki.root).absolute(), root / ".geoforge",
                     *[Path(cfg.roles[key]).absolute() for key in ("ki_tools_common", "data_ki", "ki_root")
                       if key in cfg.roles]]
        if any(target == path or path in target.parents for target in (binaries, environment)
               for path in immutable):
            raise ValueError("Managed Python destinations must stay outside KI, helper and host metadata trees")
        audit_path = _inside(root, root / ".geoforge" / "python-bootstrap" / (uuid.uuid4().hex + ".json"))
        audit = {"schema_version": 1, "kind": "managed_python_bootstrap", "ticket": ticket.nonce,
                 "state": "acquiring", "requested_version": version, "python": str(executable),
                 "environment": str(environment), "started_at": time.time(),
                 "model_ready": False, "preflight_passed": False}
        _audit(root, audit_path, audit)
        try:
            base, package, base_identity = _acquire(root, binaries, version, emit)
        except BaseException as error:
            audit.update(state="stopped" if isinstance(error, install.InstallStopped) else "failed",
                         detail=str(error), ended_at=time.time())
            _audit(root, audit_path, audit)
            raise
        audit.update(state="acquired", package=package, base_identity=base_identity)
        _audit(root, audit_path, audit)
        setup_runtime.require_current(ticket, ki, live_ki, cfg,
                                      library_root=library_root, manifest=manifest)
        install.check_cancelled()
        previous = _inside(root, environment.with_name(environment.name + ".before-bootstrap-" + uuid.uuid4().hex[:12]))
        if previous.exists():
            raise ValueError("Runtime backup destination already exists")
        change = setup_runtime.begin_change(ticket, ki, live_ki, cfg,
                                             library_root=library_root, manifest=manifest)
        environment.rename(previous)
        def restore_environment():
            # Never recursively delete a runtime. Preserve the failed attempt
            # and restore only these freshly checked, contained exact paths.
            _inside(root, environment)
            _inside(root, previous)
            if environment.exists():
                failed = _inside(root, environment.with_name(environment.name + ".failed-bootstrap-" + uuid.uuid4().hex[:12]))
                environment.rename(failed)
                audit["failed_environment"] = str(failed)
            previous.rename(environment)
        try:
            emit("Creating the selected Python environment with standard SSL and SQLite support.\n")
            rc, output = install._run([str(base), "-I", "-B", "-m", "venv", str(environment)],
                                     cwd=root, timeout=300)
            if rc:
                raise ValueError("Managed Python could not create the selected venv: " + output[-1000:])
            identity = _probe(executable, environment, package["version"])
            rc, output = install._run([str(executable), "-I", "-B", "-m", "pip", "--version"],
                                     cwd=root, timeout=60)
            if rc:
                raise ValueError("Managed Python pip bootstrap failed: " + output[-1000:])
            setup_runtime.require_current(ticket, ki, live_ki, cfg,
                                          library_root=library_root, manifest=manifest)
            install.check_cancelled()
            changed = setup_runtime.refresh(ticket, ki, live_ki, cfg,
                                             library_root=library_root, manifest=manifest, change=change)
            display_warning = None
            try:
                emit("Python " + package["version"] + " is ready at the selected path; model setup and preflight are still required.\n")
            except install.InstallStopped:
                raise
            except Exception as error:
                display_warning = str(error)
            install.check_cancelled()
            audit.update(state="complete", runtime_identity=identity, projection_refreshed=changed,
                         previous_environment=str(previous), ended_at=time.time())
            _audit(root, audit_path, audit)
        except BaseException as error:
            setup_runtime.rollback_change(change, restore_environment, ki, live_ki, cfg,
                                          library_root=library_root, manifest=manifest)
            audit.update(state="stopped" if isinstance(error, install.InstallStopped) else "failed",
                         detail=str(error), previous_environment_restored=True, ended_at=time.time())
            _audit(root, audit_path, audit)
            raise
        result = {"ok": True, "python": str(executable), "python_version": package["version"],
                  "package": package, "base_identity": base_identity, "runtime_identity": identity,
                  "projection_refreshed": changed, "previous_environment": str(previous),
                  "audit": str(audit_path),
                  "model_ready": False, "preflight_passed": False}
        if display_warning:
            result["display_warning"] = display_warning
        return result
