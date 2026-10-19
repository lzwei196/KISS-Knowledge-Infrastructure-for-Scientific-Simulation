"""Launch one complete GeoForge backend in an explicitly selected WSL runtime.

The Linux backend owns its own KI projection, approval keys and run receipts.
This manager never turns Windows installation state into Linux readiness, and
never installs a scientific package or executes a model. A listening port alone
is not a successful launch: the private startup identity must match as well.
"""
from __future__ import annotations

import atexit
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import socket
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

from . import runtime_backend

POLICY = "geoforge-linux-sidecar-v1"
MAX_FILES = 80000
MAX_BYTES = 1024 * 1024 * 1024
CHUNK_BYTES = 6 * 1024 * 1024
PORTS = range(18880, 18940)
_API_KEYS = {"api:deepseek": "DEEPSEEK_API_KEY", "api:openai": "OPENAI_API_KEY",
             "api:anthropic": "ANTHROPIC_API_KEY", "api:openrouter": "OPENROUTER_API_KEY"}
_EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                  ".geoforge", ".venv", "venv", "node_modules", "flow-keys", "flow-registry"}
_EXCLUDED_FILES = {"kiss.toml", "status.json", "installation-test.json", ".geoforge-install.json",
                   "settings.json", ".DS_Store"}
_APP_DEPS = {"yaml": "pyyaml>=6", "PIL": "Pillow>=10.4", "certifi": "certifi>=2024.2.2",
             "truststore": "truststore>=0.10.4", "packaging": "packaging>=23.2"}
_PYTHON_GUARD = """
import pathlib, site, sys, sysconfig
expected = pathlib.Path(sys.argv[1])
if (pathlib.Path(sys.prefix) != expected or sys.prefix == sys.base_prefix
        or pathlib.Path(sys.executable) != expected / 'bin/python' or site.ENABLE_USER_SITE):
    raise RuntimeError('Application Python is not the expected isolated virtual environment')
for name in ('purelib', 'platlib', 'scripts', 'data'):
    target = pathlib.Path(sysconfig.get_path(name))
    if not target.is_relative_to(expected):
        raise RuntimeError('Application installation path is outside the virtual environment: ' + name)
"""
_PYTHON_CHECK = _PYTHON_GUARD + """
import importlib.util, json
print(json.dumps({'missing': [name for name in sys.argv[2:] if importlib.util.find_spec(name) is None],
                  'pip_available': importlib.util.find_spec('pip') is not None}))
"""
_PIP_INSTALL = _PYTHON_GUARD + """
import os, runpy
# Inherited system pip may be used, but it must install only into this venv.
# Disable global/user configuration that could redirect its target or prefix.
os.environ['PIP_CONFIG_FILE'] = os.devnull
requirements = sys.argv[2:]
sys.argv = ['pip', '--isolated', 'install', '--require-virtualenv', '--prefix', str(expected),
            '--disable-pip-version-check', '--no-input', *requirements]
runpy.run_module('pip', run_name='__main__')
"""


class SidecarError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SidecarError("Sidecar source/state must not use links or reparse points")
    return path


def _trees(source_root, models_root, data_root=None):
    source = _ordinary(source_root)
    models = _ordinary(models_root)
    library = models.parent
    shared = library / "ki_tools_common"
    if not (shared / "ki_tools_common" / "__init__.py").is_file():
        shared = source / "ki_tools_common"
    manifests = library / "kiss" / "manifests"
    if not manifests.is_dir():
        manifests = source / "kiss" / "manifests"
    data = Path(data_root) if data_root else library / "kiss" / "data_kis"
    if not data.is_dir():
        data = source / "kiss" / "data_kis"
    trees = [(source / "kiss" / "kiss_cli", "kiss/kiss_cli", True),
             (source / "kiss" / "manifests", "kiss/manifests", True),
             (source / "ki_tools_common", "ki_tools_common", True),
             (models, "library/models", False),
             (shared, "library/ki_tools_common", True),
             (manifests, "library/kiss/manifests", True)]
    for folder, target in ((source / "kiss" / "system_kis", "kiss/system_kis"),
                           (source / "kiss" / "vendor", "kiss/vendor"),
                           (data, "kiss/data_kis"),
                           (data, "library/kiss/data_kis")):
        if folder.is_dir():
            trees.append((_ordinary(folder), target, False))
    for folder, _target, _code in trees:
        if not folder.is_dir():
            raise SidecarError("Required portable source directory is missing: " + str(folder))
    return trees


def source_inventory(source_root, models_root, data_root=None, *, cache=None):
    """Fingerprint only the portable payload, never installed runtimes or secrets.

    Source tests are omitted; model/reference cases remain part of the library.
    Links currently fail explicitly rather than silently changing KI provenance.
    """
    rows, files, total = {}, {}, 0
    for folder, prefix, code in _trees(source_root, models_root, data_root):
        _ordinary(folder)
        for current, directories, names in os.walk(folder, followlinks=False):
            directories[:] = sorted(name for name in directories
                if name not in _EXCLUDED_DIRS and not name.endswith(".egg-info")
                and not (code and name in {"tests", "test"}))
            for name in directories:
                _ordinary(Path(current) / name)
            for name in sorted(names):
                if name in _EXCLUDED_FILES or name.endswith((".pyc", ".pyo", ".key")):
                    continue
                path = Path(current) / name
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or getattr(info, "st_file_attributes", 0) & 0x400):
                    raise SidecarError("Portable payload contains a linked or nonordinary file: " + str(path))
                relative = prefix + "/" + path.relative_to(folder).as_posix()
                if "\\" in relative or ":" in relative or any(p in {".", "..", ""} for p in relative.split("/")):
                    raise SidecarError("Portable source contains an unsupported path")
                total += info.st_size
                if total > MAX_BYTES or len(rows) >= MAX_FILES:
                    raise SidecarError("Portable source exceeds the sidecar package limit")
                key = (str(path), info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                digest = cache.get(key) if cache is not None else None
                if digest is None:
                    digest = _hash_file(path)
                    if cache is not None:
                        cache[key] = digest
                rows[relative] = {"bytes": info.st_size, "sha256": digest,
                                  "executable": path.suffix.lower() == ".sh"}
                files[relative] = path
    # Retain the declared app version beside its exact checked source payload.
    # This is source metadata, never machine settings or installed authority.
    metadata = Path(source_root) / "kiss" / "pyproject.toml"
    if metadata.exists():
        _ordinary(metadata)
        info = metadata.stat()
        if info.st_nlink != 1 or info.st_size > 256 * 1024:
            raise SidecarError("Application version metadata is linked or too large")
        rows["kiss/pyproject.toml"] = {"bytes": info.st_size,
            "sha256": _hash_file(metadata), "executable": False}
        files["kiss/pyproject.toml"] = metadata
        total += info.st_size
        if total > MAX_BYTES or len(rows) > MAX_FILES:
            raise SidecarError("Portable source exceeds the sidecar package limit")
    if not any(name.startswith("library/models/") and name.endswith("/SKILL.md") for name in rows):
        raise SidecarError("Portable model library contains no KI packages")
    fingerprint = hashlib.sha256(_canonical({"policy": POLICY, "files": rows})).hexdigest()
    return fingerprint, rows, files


def source_fingerprint(source_root, models_root, data_root=None):
    return source_inventory(source_root, models_root, data_root)[0]


def _host_environment():
    return {key: value for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA"}}


def _wsl_command(arguments, *, timeout=15):
    if os.name != "nt":
        raise SidecarError("WSL sidecars require Windows")
    exe = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "wsl.exe"
    result = subprocess.run([str(exe), *arguments], capture_output=True, timeout=timeout,
                            env=_host_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise SidecarError("WSL inventory probe failed")
    raw = result.stdout
    return raw.decode("utf-16-le" if b"\0" in raw[:100] else "utf-8", errors="strict").lstrip("\ufeff")


def describe():
    """Inspect named distributions and their default non-root Python user.

    The fixed identity probe may start a stopped distribution; it neither
    creates a workspace nor installs packages or runs a model.
    """
    try:
        names = [line.strip() for line in _wsl_command(["--list", "--quiet"]).splitlines() if line.strip()]
        if len(names) > 16:
            raise SidecarError("Too many WSL distributions for bounded discovery")
        rows = []
        probe = ("import json,os,pwd,sys; p=pwd.getpwuid(os.getuid()); "
                 "print(json.dumps(dict(user=p.pw_name,uid=os.getuid(),home=p.pw_dir,"
                 "python_version=list(sys.version_info[:3]))))")
        for name in names:
            row = {"distro": name, "available": False}
            if name.startswith("-") or any(ord(c) < 32 for c in name):
                continue
            try:
                identity = json.loads(_wsl_command(["--distribution", name, "--exec", "/usr/bin/python3", "-I", "-S", "-c", probe]))
                row.update(identity)
                row["available"] = (identity.get("uid", 0) > 0 and identity.get("user") != "root"
                                    and tuple(identity.get("python_version", [])) >= (3, 11))
                if not row["available"]:
                    row["detail"] = "A non-root default user and Python 3.11 or newer are required"
            except (OSError, ValueError, subprocess.SubprocessError, SidecarError):
                row["detail"] = "Default Linux user/Python identity could not be checked"
            rows.append(row)
        return {"available": any(row["available"] for row in rows), "distributions": rows}
    except (OSError, ValueError, subprocess.SubprocessError, SidecarError) as error:
        return {"available": False, "distributions": [], "detail": str(error)}


def _provider_settings(value, provider_id):
    if provider_id not in _API_KEYS:
        raise SidecarError("This Linux launch currently requires a configured API provider")
    if not isinstance(value, dict):
        raise SidecarError("Provider settings must be an object")
    key_name = _API_KEYS[provider_id]
    key = (value.get("api_keys") or {}).get(key_name, "")
    if not isinstance(key, str) or not key or len(key) > 8192 or "\0" in key:
        raise SidecarError("The selected API provider needs its configured credential")
    result = {"default_provider": provider_id, "api_keys": {key_name: key},
              "proxy_mode": "off", "proxy_providers": [], "proxy_targets_version": 2}
    from . import settings
    targets = settings.proxy_providers(value) & {provider_id, "network:github", "network:obs"}
    mode = settings.proxy_mode(value)
    if mode == "auto":
        # Auto is platform-specific discovery, not permission to reinterpret a
        # Windows loopback service as a Linux loopback service.
        result.update(proxy_mode="auto", proxy_providers=sorted(targets))
    elif mode == "manual" and targets:
        url = settings._normalise_proxy_url(value.get("proxy_url") or "")
        if urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}:
            raise SidecarError("A Windows loopback proxy cannot be reused as a Linux proxy; select Auto, Off, or a reachable proxy")
        result.update(proxy_mode="manual", proxy_url=url, proxy_providers=sorted(targets))
    return result


# This fixed bootstrap receives only manager-generated paths and a private
# settings object. It never reads a model installation, runs a KI, or accepts
# an agent-authored program. Archive names/bytes are checked against the host
# inventory before the source tree becomes usable.
_BOOTSTRAP = r'''
import hashlib,json,os,stat,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
req=json.load(sys.stdin)
root=Path(req["workspace"])
def safe(value):
    p=PurePosixPath(value)
    if not value or p.is_absolute() or "\\" in value or any(x in {"", ".", ".."} for x in value.split("/")):
        raise ValueError("invalid bootstrap path")
    target=root.joinpath(*p.parts)
    for part in (target,*target.parents):
        if part.is_symlink(): raise ValueError("bootstrap refuses linked paths")
    return target
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as s:
        for b in iter(lambda:s.read(1048576),b""): h.update(b)
    return h.hexdigest()
manifest=json.loads(safe(req["manifest"]).read_text())
canonical=lambda v:json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
if hashlib.sha256(canonical(manifest)).hexdigest()!=req["source_hash"]:
    raise ValueError("source manifest changed")
destination=safe("app/"+req["source_hash"])
if not destination.exists():
    staging=safe("staging/source-"+req["nonce"])
    staging.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryFile(dir=root) as archive:
        ah=hashlib.sha256()
        for name in req["parts"]:
            with safe(name).open("rb") as s:
                for block in iter(lambda:s.read(1048576),b""):
                    ah.update(block); archive.write(block)
        if ah.hexdigest()!=req["archive_sha256"]: raise ValueError("archive changed")
        archive.seek(0)
        seen=set()
        with tarfile.open(fileobj=archive,mode="r:gz") as source:
            for member in source:
                row=manifest["files"].get(member.name)
                if row is None or member.name in seen or not member.isfile() or member.size!=row["bytes"]:
                    raise ValueError("archive member does not match source manifest")
                safe(member.name)
                target=staging.joinpath(*PurePosixPath(member.name).parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                with source.extractfile(member) as stream, target.open("xb") as out:
                    h=hashlib.sha256(); size=0
                    for block in iter(lambda:stream.read(1048576),b""):
                        out.write(block); h.update(block); size+=len(block)
                if size!=row["bytes"] or h.hexdigest()!=row["sha256"]: raise ValueError("source bytes changed")
                os.chmod(target,0o555 if row["executable"] else 0o444)
                seen.add(member.name)
        if seen!=set(manifest["files"]): raise ValueError("source archive is incomplete")
    destination.parent.mkdir(parents=True,exist_ok=True)
    os.rename(staging,destination)
for name,row in manifest["files"].items():
    p=destination.joinpath(*PurePosixPath(name).parts)
    if p.is_symlink() or not p.is_file() or p.stat().st_nlink!=1 or p.stat().st_size!=row["bytes"] or digest(p)!=row["sha256"]:
        raise ValueError("retained source differs from the checked build")
actual=set()
for current,directories,names in os.walk(destination,followlinks=False):
    if any((Path(current)/name).is_symlink() for name in directories): raise ValueError("retained source has a linked directory")
    actual.update((Path(current)/name).relative_to(destination).as_posix() for name in names)
if actual!=set(manifest["files"]): raise ValueError("retained source contains unrecognized files")
for current,directories,names in os.walk(destination,topdown=False): os.chmod(current,0o555)
for folder in ("work", "profile", "authority/flow-keys", "authority/flow-registry", "authority/ki-guard", "authority/ki-adaptations", "authority/ki-investigations"):
    path=safe(folder); path.mkdir(parents=True,exist_ok=True); os.chmod(path,0o700)
settings=safe("profile/settings.json")
fd,temp=tempfile.mkstemp(prefix=".settings-",dir=settings.parent)
try:
    os.fchmod(fd,0o600)
    with os.fdopen(fd,"wb") as out: out.write(canonical(req["settings"])); out.flush(); os.fsync(out.fileno())
    os.replace(temp,settings)
finally:
    if os.path.exists(temp): os.unlink(temp)
print(json.dumps({"ok":True,"source_hash":req["source_hash"],"files":len(manifest["files"])}))
'''


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise SidecarError("Runtime identity endpoint redirected")


def _read_identity(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(url + "api/runtime/identity", timeout=2) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise SidecarError("Runtime identity response is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SidecarError("Runtime identity response is malformed")
    return value


def _available_port():
    for port in PORTS:
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise SidecarError("No free loopback port in the Linux runtime range")


class SidecarManager:
    def __init__(self, *, source_root, models_root, host_state, data_root=None):
        self.source_root, self.models_root = Path(source_root).absolute(), Path(models_root).absolute()
        self.data_root = Path(data_root).absolute() if data_root else None
        self.host_state = Path(host_state).absolute()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = self._server_thread = None
        self._identity = self._binding = None
        self._url = None
        self._cache = {}
        self._secrets = []
        self._state = {"state": "stopped", "stage": "idle", "detail": "Linux backend is not running"}
        atexit.register(self.stop)

    def describe(self):
        return describe()

    def _set(self, **values):
        with self._lock:
            self._state.update(values)

    def _view(self):
        with self._lock:
            result = dict(self._state)
            if self._identity:
                result["runtime_identity"] = {k: v for k, v in self._identity.items() if k != "nonce"}
            if result["state"] == "ready":
                result["url"] = self._url
            return result

    def status(self):
        with self._lock:
            ready = self._state["state"] in {"ready", "unavailable"}
            identity, url = self._identity, self._url
        if ready:
            try:
                fingerprint = source_inventory(self.source_root, self.models_root, self.data_root, cache=self._cache)[0]
                if fingerprint != identity["source_hash"]:
                    self._set(state="stale", detail="Desktop source/library changed; stop and restart this Linux backend")
                    self._stop.set()
                elif _read_identity(url) != identity:
                    self._set(state="failed", detail="The loopback server no longer matches this Linux backend")
                    self._stop.set()
                else:
                    self._set(state="ready", detail="Linux GUI backend identity checked; model installation remains separate")
            except (OSError, ValueError, SidecarError):
                self._set(state="unavailable", detail="The Linux backend identity could not be checked")
        return self._view()

    def launch(self, *, distro, user, provider_settings=None, provider_id="api:deepseek"):
        private = _provider_settings(provider_settings or {}, provider_id)
        if not isinstance(distro, str) or not distro or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,63}\$?", user or "") or user == "root":
            raise SidecarError("Select a named WSL distribution and non-root Linux user")
        with self._lock:
            if any(thread and thread.is_alive() for thread in (self._thread, self._server_thread)):
                raise SidecarError("Stop the current Linux backend before launching another")
            self._stop = threading.Event()
            self._identity = self._binding = self._url = None
            self._secrets = [*private["api_keys"].values(), *([private["proxy_url"]] if private.get("proxy_url") else [])]
            self._state = {"state": "starting", "stage": "identity", "detail": "Checking the selected Linux runtime"}
            self._thread = threading.Thread(target=self._start, args=(distro, user, private), daemon=True,
                                            name="geoforge-linux-start")
            self._thread.start()
        return self._view()

    def stop(self):
        with self._lock:
            active = any(thread and thread.is_alive() for thread in (self._thread, self._server_thread))
            if active:
                self._state.update(state="stopping", stage="stop", detail="Stopping this backend and its child processes")
                self._stop.set()
            elif self._state["state"] != "failed":
                self._state.update(state="stopped", stage="idle", detail="Linux backend is stopped")
        return self._view()

    def _check_stop(self):
        if self._stop.is_set():
            raise SidecarError("Linux backend start was stopped")

    def _run(self, argv, *, env=None, stdin=None, timeout=300):
        self._check_stop()
        result = runtime_backend.run(self._binding, argv, cwd=self._binding.workspace,
                                     env=env, timeout=timeout, stop=self._stop.is_set, stdin=stdin)
        if result.status != "finished" or result.returncode != 0:
            detail = self._record_error(result, stage=self._state.get("stage", "bootstrap"))
            raise SidecarError("Linux bootstrap command failed (" + result.status + "): " + detail)
        return result

    def _record_error(self, result, *, stage):
        def scrub(value):
            text = str(value or "")
            for secret in self._secrets:
                if secret:
                    text = text.replace(secret, "[redacted]")
            return text
        record = {"at": time.time(), "stage": stage, "status": result.status,
                  "returncode": result.returncode, "detail": scrub(result.detail),
                  "stdout": scrub(result.stdout)[-128000:], "stderr": scrub(result.stderr)[-128000:]}
        try:
            self.host_state.mkdir(parents=True, exist_ok=True)
            _ordinary(self.host_state)
            path = self.host_state / "last-error.json"
            if path.exists():
                _ordinary(path)
            temporary = self.host_state / (".error-" + uuid.uuid4().hex)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_canonical(record))
            os.replace(temporary, path)
        except (OSError, SidecarError):
            pass
        details = record["stderr"].strip() or record["detail"].strip() or record["stdout"].strip()
        return details[-1500:] or "No diagnostic text was returned"

    def _select_binding(self, distro, user):
        probe = ("import json,os,pwd,sys; p=pwd.getpwuid(os.getuid()); print(json.dumps("
                 "dict(user=p.pw_name,uid=os.getuid(),home=p.pw_dir,python_version=list(sys.version_info[:3]))))")
        row = json.loads(_wsl_command(["--distribution", distro, "--user", user, "--exec", "/usr/bin/python3", "-I", "-S", "-c", probe]))
        if row.get("user") != user or row.get("uid", 0) <= 0 or tuple(row.get("python_version", [])) < (3, 11):
            raise SidecarError("Selected Linux account/Python does not match requirements")
        self.host_state.mkdir(parents=True, exist_ok=True)
        _ordinary(self.host_state)
        key = hashlib.sha256(_canonical({"distro": distro, "user": user})).hexdigest()[:24]
        path = self.host_state / (key + ".json")
        if path.exists():
            _ordinary(path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            if set(saved) != {"policy", "distro", "user", "home", "workspace_id"} or saved != {
                    "policy": POLICY, "distro": distro, "user": user, "home": row["home"], "workspace_id": saved["workspace_id"]}:
                raise SidecarError("Saved Linux runtime binding changed")
            identifier = saved["workspace_id"]
        else:
            identifier = uuid.uuid4().hex
            saved = {"policy": POLICY, "distro": distro, "user": user, "home": row["home"], "workspace_id": identifier}
            with path.open("x", encoding="utf-8") as stream:
                json.dump(saved, stream)
        workspace = str(PurePosixPath(row["home"]) / ".local/share/geoforge/runtimes" / identifier)
        return runtime_backend.WSLBinding(distro=distro, user=user, workspace=workspace, workspace_id=identifier)

    def _stage(self, fingerprint, rows, files, nonce):
        prefix = "staging/" + fingerprint
        manifest = {"policy": POLICY, "files": rows}
        manifest_name = prefix + "/manifest.json"
        bootstrap_name = "bootstrap/" + hashlib.sha256(_BOOTSTRAP.encode()).hexdigest() + ".py"
        runtime_backend.write_files(self._binding, {manifest_name: _canonical(manifest), bootstrap_name: _BOOTSTRAP.encode()})
        # Always use the OS temporary volume, never the possibly full checkout.
        with tempfile.TemporaryFile() as archive:
            with gzip.GzipFile(filename="", fileobj=archive, mode="wb", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as bundle:
                for name, path in files.items():
                    self._check_stop()
                    data = path.read_bytes()
                    if len(data) != rows[name]["bytes"] or hashlib.sha256(data).hexdigest() != rows[name]["sha256"]:
                        raise SidecarError("Source changed while building the Linux payload")
                    member = tarfile.TarInfo(name)
                    member.size, member.mode, member.mtime = len(data), 0o644, 0
                    bundle.addfile(member, io.BytesIO(data))
            size = archive.tell()
            archive.seek(0)
            parts, digest, transferred = [], hashlib.sha256(), 0
            while True:
                data = archive.read(CHUNK_BYTES)
                if not data:
                    break
                self._check_stop()
                name = prefix + f"/part-{len(parts):05d}"
                runtime_backend.write_files(self._binding, {name: data})
                parts.append(name); digest.update(data); transferred += len(data)
                self._set(progress=round(transferred / max(size, 1), 3), detail="Copying checked application and portable KI files into Linux")
        return {"manifest": manifest_name, "parts": parts, "archive_sha256": digest.hexdigest()}, bootstrap_name

    def _start(self, distro, user, private):
        try:
            self._binding = self._select_binding(distro, user)
            self._check_stop()
            runtime_backend.prepare(self._binding)
            self._set(stage="source", detail="Checking portable application and KI files")
            fingerprint, rows, files = source_inventory(self.source_root, self.models_root, self.data_root, cache=self._cache)
            nonce = secrets.token_urlsafe(32)
            transfer, bootstrap = self._stage(fingerprint, rows, files, nonce)
            root = self._binding.workspace
            self._set(stage="bootstrap", detail="Preparing an isolated Linux application profile")
            request = {**transfer, "workspace": root, "source_hash": fingerprint, "nonce": nonce, "settings": private}
            result = self._run([self._binding.python, "-I", "-S", root + "/" + bootstrap], stdin=_canonical(request), timeout=600)
            if json.loads(result.stdout).get("source_hash") != fingerprint:
                raise SidecarError("Guest source staging did not confirm the expected build")
            del private, request
            self._set(stage="python", detail="Checking the Linux application interpreter")
            # Ubuntu can ship venv without ensurepip. Reuse an existing partial
            # environment and inherit distribution pip, without installing apt
            # packages or changing the system interpreter.
            self._run([self._binding.python, "-m", "venv", "--without-pip", "--system-site-packages", root + "/appenv"], timeout=180)
            python = root + "/appenv/bin/python"
            probe_command = [python, "-I", "-c", _PYTHON_CHECK, root + "/appenv", *list(_APP_DEPS)]
            probe = json.loads(self._run(probe_command).stdout)
            missing = probe.get("missing") if isinstance(probe, dict) else None
            if not isinstance(missing, list) or any(name not in _APP_DEPS for name in missing):
                raise SidecarError("Application dependency probe returned an invalid result")
            if missing:
                if probe.get("pip_available") is not True:
                    raise SidecarError("Missing application dependencies require pip in the Linux runtime; install python3-pip and retry")
                self._set(detail="Installing only missing GeoForge application dependencies")
                self._run([python, "-I", "-c", _PIP_INSTALL, root + "/appenv", *(_APP_DEPS[name] for name in missing)], timeout=600)
                checked = json.loads(self._run(probe_command).stdout)
                if not isinstance(checked, dict) or checked.get("missing") != []:
                    raise SidecarError("Application dependencies are still unavailable in the verified virtual environment")
            identity = {"id": self._binding.workspace_id, "distro": distro, "user": user,
                        "workspace": root, "source_hash": fingerprint, "nonce": nonce}
            app = root + "/app/" + fingerprint
            env = {"GEOFORGE_APP_DATA_DIR": root + "/profile", "GEOFORGE_RUNTIME_IDENTITY": _canonical(identity).decode(),
                   "GEOFORGE_FLOW_KEYS": root + "/authority/flow-keys", "GEOFORGE_FLOW_REGISTRY": root + "/authority/flow-registry",
                   "GEOFORGE_KI_GUARD_HOME": root + "/authority/ki-guard", "GEOFORGE_KI_ADAPTATION_HOME": root + "/authority/ki-adaptations",
                   "GEOFORGE_KI_INVESTIGATION_HOME": root + "/authority/ki-investigations", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": app + "/kiss:" + app + "/ki_tools_common", "PATH": root + "/appenv/bin:/usr/local/bin:/usr/bin:/bin"}
            port = _available_port()
            self._identity, self._url = identity, f"http://127.0.0.1:{port}/"
            command = [python, "-m", "kiss_cli.cli", "--models", app + "/library/models", "gui", "--no-browser", "--desktop-server",
                       "--port", str(port), "--workroot", root + "/work"]
            self._set(stage="server", detail="Starting and authenticating the Linux GUI backend", progress=1)
            self._server_thread = threading.Thread(target=self._serve, args=(command, env), daemon=True, name="geoforge-linux-server")
            self._server_thread.start()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                self._check_stop()
                if not self._server_thread.is_alive():
                    raise SidecarError("Linux GUI backend exited before it became ready")
                try:
                    observed = _read_identity(self._url)
                except (OSError, ValueError, SidecarError):
                    self._stop.wait(.25)
                    continue
                if observed != identity:
                    raise SidecarError("Port is occupied by a different runtime identity")
                if source_inventory(self.source_root, self.models_root, self.data_root, cache=self._cache)[0] != fingerprint:
                    raise SidecarError("Desktop source changed during Linux startup; restart with the current build")
                self._set(state="ready", stage="ready", detail="Linux GUI backend identity checked; model installation remains separate")
                return
            raise SidecarError("Linux GUI backend did not confirm its identity before the deadline")
        except Exception as error:
            stopped = self._stop.is_set()
            self._stop.set()
            # The server thread may already have recorded the actionable cause.
            # Do not replace it with the generic startup-exited observation.
            if self._view()["state"] == "failed":
                return
            self._set(state="stopped" if stopped else "failed", stage="idle" if stopped else "failed",
                      detail="Linux backend start was stopped" if stopped else str(error))

    def _serve(self, command, env):
        try:
            result = runtime_backend.run(self._binding, command, cwd=self._binding.workspace, env=env,
                                         timeout=86400, stop=self._stop.is_set)
        except Exception as error:
            result = runtime_backend.RunResult("failed", None, detail=str(error))
        detail = (self._record_error(result, stage="server") if not self._stop.is_set() else "")
        with self._lock:
            if self._state["state"] not in {"failed", "stale"}:
                stopped = self._stop.is_set() or result.status == "stopped"
                self._state.update(state="stopped" if stopped else "failed", stage="idle" if stopped else "failed",
                                   detail="Linux backend stopped" if stopped else "Linux GUI backend exited (" + result.status + "): " + detail)
