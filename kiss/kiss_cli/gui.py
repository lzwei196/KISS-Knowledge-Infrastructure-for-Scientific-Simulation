"""``kiss gui`` — the KISS frontend: catalogue, install, and chat with a KI.

Deliberately not Electron. One stdlib HTTP server and one HTML file, so it
installs with ``pip install kiss-ki`` and starts in under a second.

The chat does not implement an agent loop. It composes the KI opening prompt
(see :mod:`kiss_cli.prompt`) and spawns whichever agent CLI the user already
has authenticated, in the KI's working directory. That is the same architecture
the HydroCraft deployment runs against these packages in production, and it
means the frontend inherits each CLI's tools, approvals and sessions instead of
reimplementing them badly.

Every install action calls the identical functions ``kiss init`` uses. The GUI
adds discovery, a progress view and chat — never its own install logic. If the
two ever disagree, that is a bug in the GUI.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import doctor, handoff, install, paths, policy, port, prompt, providers
from .catalog import Catalog
from .manifest import Manifest

PAGE = (Path(__file__).parent / "web" / "app.html")


class Handler(BaseHTTPRequestHandler):
    catalog: Catalog
    repo_root: Path
    workroot: Path

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # keep the console clean
        pass

    # --- plumbing ----------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _manifest(self, ki) -> Manifest:
        if ki.manifest:
            return Manifest.load(ki.manifest)
        shipped = self.repo_root / "kiss" / "manifests" / f"{ki.name}.yaml"
        return Manifest.load(shipped) if shipped.exists() else Manifest.stub_for(ki)

    def _ki(self, name: str):
        return self.catalog.get(unquote(name))

    def _workdir(self, ki) -> Path:
        return self.workroot / ki.name.lower()

    # --- GET ---------------------------------------------------------------
    def do_GET(self) -> None:
        route = urlparse(self.path).path

        if route == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")

        if route == "/api/providers":
            return self._json([
                {"name": p.name, "label": p.label, "notes": p.notes}
                for p in providers.available()
            ])

        if route == "/api/models":
            out = []
            for ki in self.catalog:
                man = self._manifest(ki)
                shipped = (self.repo_root / "kiss" / "manifests" / f"{ki.name}.yaml").exists()
                out.append({
                    "name": ki.name, **ki.meta,
                    "verified": man.verified,
                    "has_manifest": bool(ki.manifest) or shipped,
                    "paths": ki.portability.total,
                })
            return self._json(out)

        if route.startswith("/api/model/"):
            try:
                ki = self._ki(route.rsplit("/", 1)[-1])
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            man = self._manifest(ki)
            wd = self._workdir(ki)
            return self._json({
                "name": ki.name, **ki.meta,
                "verified": man.verified, "notes": man.notes,
                "strategy": man.acquire.strategy if man.acquire else None,
                "depends_on": man.depends_on,
                "has_manifest": bool(ki.manifest),
                "paths": ki.portability.total,
                "workdir": str(wd),
                "installed": (wd / paths.CONFIG_NAME).exists(),
                "forcing": ki.forcing_vars,
            })

        if route.startswith("/api/doctor/"):
            try:
                ki = self._ki(route.rsplit("/", 1)[-1])
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            return self._json([f.__dict__ for f in doctor.check_ki(ki)])

        if route.startswith("/api/prompt/"):
            # Exposed so the prompt is inspectable rather than magic.
            try:
                ki = self._ki(route.rsplit("/", 1)[-1])
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            cfg = self._config(ki)
            return self._send(200, prompt.compose(ki, cfg).encode(), "text/plain; charset=utf-8")

        self._json({"error": "not found"}, 404)

    # --- POST --------------------------------------------------------------
    def do_POST(self) -> None:
        route = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")

        if route == "/api/init":
            return self._stream_init(req)
        if route == "/api/chat":
            return self._stream_chat(req)
        self._json({"error": "not found"}, 404)

    def _open_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _chunk(self, text: str) -> bool:
        """Write one HTTP chunk. Returns False once the client has gone."""
        if not text:
            return True
        data = text.encode("utf-8", "replace")
        try:
            self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def _end_stream(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _config(self, ki) -> paths.KissConfig:
        wd = self._workdir(ki)
        if (wd / paths.CONFIG_NAME).exists():
            return paths.KissConfig.load(wd)
        cfg = paths.KissConfig.default(wd)
        cfg.python = sys.executable
        return cfg

    # --- install -----------------------------------------------------------
    def _stream_init(self, req) -> None:
        try:
            ki = self._ki(req["model"])
        except KeyError as e:
            return self._json({"error": str(e)}, 404)
        self._open_stream()
        try:
            run_install(ki, self._manifest(ki), self._workdir(ki), self._chunk, self.repo_root)
        except Exception as e:
            self._chunk(f"\nkiss: {type(e).__name__}: {e}\n")
        self._end_stream()

    # --- chat --------------------------------------------------------------
    def _stream_chat(self, req) -> None:
        try:
            ki = self._ki(req["model"])
        except KeyError as e:
            return self._json({"error": str(e)}, 404)

        avail = providers.available()
        if not avail:
            self._open_stream()
            self._chunk("No agent CLI found on PATH. Install one of: "
                        "claude, codex, gemini, kimi, qwen.")
            return self._end_stream()

        try:
            prov = providers.get(req.get("provider") or avail[0].name)
        except KeyError as e:
            return self._json({"error": str(e)}, 400)

        cfg = self._config(ki)
        wd = self._workdir(ki)
        wd.mkdir(parents=True, exist_ok=True)
        if not (wd / paths.CONFIG_NAME).exists():
            (wd / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")

        # The agent must be able to read the KI itself, not just the workdir.
        full = prompt.compose(ki, cfg, task=req.get("message", ""))

        self._open_stream()
        # cfg puts the agent inside the same relocated view the installer and
        # every simulation it launches will see. The prefixes must ALSO be
        # granted to the agent explicitly: the namespace makes them exist, the
        # CLI's own allowlist decides whether it may read them.
        grants = [str(ki.root)] + paths.bound_prefixes(cfg)

        # Least privilege derived from what this KI declares, plus anything the
        # user has previously approved for this workdir.
        pol = policy.Policy.derive(ki, self._manifest(ki), cfg)
        saved_posture, approved = policy.Policy.load_approved(wd)
        if saved_posture is not None:
            pol.posture = saved_posture
        pol.approved = approved

        for piece in providers.run(prov, full, wd, extra_dirs=grants,
                                   cfg=cfg, ki_root=ki.root, pol=pol):
            if not self._chunk(piece):
                break
        self._end_stream()


def run_install(ki, man: Manifest, root: Path, emit, repo_root: Path) -> None:
    """The same six steps as ``kiss init``, streamed line by line."""
    root.mkdir(parents=True, exist_ok=True)
    cfg_file = root / paths.CONFIG_NAME
    if cfg_file.exists():
        cfg = paths.KissConfig.load(root)
        emit(f"using {cfg_file}\n")
    else:
        cfg = paths.KissConfig.default(root)
        cfg.python = sys.executable
        cfg_file.write_text(cfg.dumps(), encoding="utf-8")
        emit(f"wrote {cfg_file}\n")

    strategy = man.acquire.strategy if man.acquire else "none"
    emit(f"\ninitialising {ki.name} (strategy: {strategy})\n\n")
    result = install.InstallResult(model=ki.name)

    def step(label: str, s):
        result.add(s)
        emit(f"  {label:<22} {s.mark}\n")
        if not s.ok and s.detail:
            for ln in s.detail.strip().splitlines()[:8]:
                emit(f"      {ln}\n")
        return s

    # Materialise, then operate on the working copy — identical to `kiss init`.
    # Skipping this ran preflight against the repository package with its
    # KISSPATH_* placeholders still in place, so the GUI and the CLI disagreed
    # about what "installed" meant.
    live = root / "ki"
    mrep = port.materialise(ki.root, live, cfg)
    ok = not mrep.unresolved
    result.add(install.Step(
        "materialise", ok,
        f"{mrep.tokens_replaced} placeholders resolved into {live}" if ok else
        f"unresolved placeholders: {', '.join(sorted(mrep.unresolved))}"))
    emit(f"  {'[1/8] materialise KI':<22} {'ok' if ok else 'FAILED'}"
         f"  ({mrep.tokens_replaced} paths written)\n")
    if mrep.undeliverable_files:
        emit(f"      note: {mrep.undeliverable_files} files reference the author's "
             "private tooling; those instructions cannot be followed\n")
    ki = type(ki)(name=ki.name, root=live)

    step("[2/8] python env", install.ensure_python_env(cfg))
    cfg_file.write_text(cfg.dumps(), encoding="utf-8")

    step("[3/8] ki_tools_common", install.install_ki_tools_common(cfg, repo_root))
    step("[4/8] system deps", install.check_system_deps(man.system_deps))
    step("[5/8] python deps", install.install_python_deps(man.python_deps, cfg.python))
    prefix = cfg.roles["binaries"] / (man.install_dir or ki.name)
    s, binary = install.acquire(man, prefix, cfg.python)
    result.binary = binary
    step("[6/8] acquire", s)
    if man.depends_on:
        emit(f"      couples with: {', '.join(man.depends_on)}\n")
    step("[7/8] data", install.check_data(man, cfg))
    step("[8/8] preflight", install.run_preflight(ki, cfg.python, cfg))
    written = handoff.write(ki, result, man, cfg, root)
    emit(f"  {'      agent handoff':<22} ok ({len(written)} files)\n\n")

    if result.ok:
        emit(f"{ki.name} is ready.  {root}\n")
    else:
        emit(f"{ki.name} is not finished — {len(result.failures)} step(s) need attention.\n")
        emit("Ask the agent in this window to finish it — it has the KI's own "
             "diagnostics.\n")


def serve(models_dir: Path | None, port: int = 8765, open_browser: bool = True,
          workroot: Path | None = None) -> int:
    cat = Catalog(models_dir) if models_dir else Catalog.discover()
    Handler.catalog = cat
    Handler.repo_root = cat.models_dir.parent
    Handler.workroot = Path(workroot or Path.home() / "kiss").expanduser()
    Handler.workroot.mkdir(parents=True, exist_ok=True)

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    agents = ", ".join(p.label for p in providers.available()) or "none found"
    print(f"KISS — {len(cat)} KI packages · agents: {agents}")
    print(f"  {url}\n  workdir root: {Handler.workroot}\nCtrl-C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0
