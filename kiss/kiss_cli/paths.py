"""Path portability for KI packages.

Every KI in this repository was authored on one machine and carries that
machine's absolute paths (``/mnt/disk1/Hydrocraft_server/...``, ``/home/server/...``).
That is fine for provenance and useless for anyone else.

This module defines the *roles* those prefixes play, so a KI can be relocated
without hand-editing 600 files. Three relocation tiers are supported, in
descending order of preference:

  1. ``port``    — rewrite literals to call into this module. Permanent and
                   honest, but needs per-model verification.
  2. ``sandbox`` — materialise the authoring prefixes inside a user namespace
                   (bubblewrap) or container, bind-mounted onto the user's real
                   directories. Zero edits, works for every KI today.
  3. ``symlink`` — create the authoring prefixes as symlinks on the real
                   filesystem. Needs write access to ``/mnt``; last resort.

``kiss doctor`` reports which tier a given KI currently needs.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "kiss.toml"

#: Absolute prefixes baked into the shipped KIs, mapped to the role they play.
#: Order matters — longest / most specific prefix must be tested first.
LEGACY_PREFIXES: list[tuple[str, str]] = [
    ("/mnt/disk1/Hydrocraft_server/python_env", "python_env"),
    ("/mnt/disk1/Hydrocraft_server/models/ki_tools_common", "ki_tools_common"),
    ("/mnt/disk1/Hydrocraft_server/models", "ki_root"),
    ("/mnt/disk1/Hydrocraft_server/model", "binaries"),
    # data_ki and outputs_disk1 must precede "data"/"outputs": a plain prefix
    # replace would otherwise turn "data_ki/CMFD" into "<data-token>_ki/CMFD".
    ("/mnt/disk1/Hydrocraft_server/data_ki", "data_ki"),
    ("/mnt/disk1/Hydrocraft_server/outputs_disk1", "outputs_disk1"),
    ("/mnt/disk1/Hydrocraft_server/data/obs", "obs"),
    ("/mnt/disk1/Hydrocraft_server/data/dem", "static"),
    ("/mnt/disk1/Hydrocraft_server/data/soil", "static"),
    ("/mnt/disk1/Hydrocraft_server/data", "data"),
    ("/mnt/disk1/Hydrocraft_server/outputs", "outputs"),
    ("/mnt/disk1/Hydrocraft_server", "server_root"),
    ("/media/server/hc_ssd/forcing", "forcing"),
    ("/media/server/geoforge_sim", "outputs"),
    ("/media/server/hc_ssd", "data"),
    ("/mnt/disk3/msxw_rechunked", "forcing_rechunked"),
    ("/mnt/disk3/msxw", "forcing"),
    ("/mnt/disk3", "data"),
    ("/mnt/disk4", "data"),
    ("/mnt/datasets", "data"),
    ("/home/server/knowledge-dissection-toolkit", "kdt_internal"),
    ("/home/server", "home"),
]

#: Roles the user is expected to supply a real directory for.
USER_ROLES = ("binaries", "data", "forcing", "obs", "static", "outputs", "python_env")

#: Roles that should never have shipped in a public KI. ``kiss doctor`` flags
#: these as leaks rather than as relocatable paths — they point at the private
#: dissection toolkit, not at anything an end user needs.
LEAK_ROLES = ("kdt_internal",)

_PREFIX_RE = re.compile(
    "|".join(re.escape(p) for p, _ in LEGACY_PREFIXES).join(("(", ")"))
)


def classify(path: str) -> str | None:
    """Return the role of ``path``, or None if it is already portable."""
    for prefix, role in LEGACY_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return role
    return None


def scan_text(text: str) -> list[tuple[str, str]]:
    """Find every authoring-machine path in ``text``.

    Returns ``(matched_path, role)`` pairs. The match is greedy over characters
    that may legally appear in a path so that the caller sees the full literal,
    not just the prefix.
    """
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(?:/mnt/(?:disk\d|datasets)|/home/server|/media/server)[\w./+-]*", text):
        hit = m.group(0)
        role = classify(hit)
        if role:
            out.append((hit, role))
    return out


_BASIC_STRING_LINE = re.compile(
    r'^(?P<key>[A-Za-z0-9_-]+\s*=\s*)"(?P<val>[^"\\]*\\[^"]*)"(?P<rest>.*)$', re.M)


def _repair_backslash_strings(text: str) -> str:
    """Re-quote basic strings holding raw backslashes as literal strings."""
    def fix(m: "re.Match[str]") -> str:
        val = m.group("val")
        if "'" in val:
            val = val.replace('\\', '\\\\')
            return f'{m.group("key")}"{val}"{m.group("rest")}'
        return f"{m.group('key')}'{val}'{m.group('rest')}"
    return _BASIC_STRING_LINE.sub(fix, text)


def _toml_str(value) -> str:
    """Quote one value so a Windows path survives a TOML round-trip.

    A basic string processes escapes, so a bare C:\\Users\\... makes \\U open a
    unicode escape and the whole file fails to parse with "Invalid hex value".
    Every config this app wrote on Windows was unreadable that way, which is
    why setup could never start; macOS paths carry no backslash, so it never
    surfaced there. A literal string escapes nothing, which is exactly what a
    path wants -- so use one whenever the value can be held in one, and fall
    back to a fully escaped basic string when it cannot.
    """
    text = str(value)
    unquotable = ("'", '\\n', '\\r')
    if not any(c in text for c in unquotable) and not any(ord(c) < 0x20 for c in text):
        return "'" + text + "'"
    out = []
    for ch in text:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ord(ch) < 0x20:
            out.append('\\u' + format(ord(ch), "04X"))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'
@dataclass
class KissConfig:
    """A user's local answer to "where does everything actually live?"."""

    root: Path
    roles: dict[str, Path] = field(default_factory=dict)
    python: str = "python3"
    relocation: str = "sandbox"

    @classmethod
    def default(cls, root: Path) -> "KissConfig":
        root = Path(root).expanduser().resolve()
        # Relocation via mount namespace only exists on Linux with bubblewrap
        # present. Defaulting to "sandbox" elsewhere made every macOS chat open
        # with a warning about software that cannot be installed there — noise
        # about an internal mechanism the user never chose. Materialised
        # installs write real paths, so "none" is not a degradation.
        reloc = "sandbox" if have_sandbox() else "none"
        return cls(
            relocation=reloc,
            root=root,
            roles={
                "binaries": root / "binaries",
                "data": root / "data",
                "forcing": root / "data" / "forcing",
                "obs": root / "data" / "obs",
                "static": root / "data" / "static",
                "outputs": root / "outputs",
                "ki_root": root / "models",
                "python_env": root / "venv",
                "server_root": root,
                "home": root,
                "data_ki": root / "data_ki",
                # The shared helper library 126 of the 127 KIs import. It has to
                # have a home even before it is installed, or every KI that
                # references it fails to materialise.
                "ki_tools_common": root / "ki_tools_common",
                "forcing_rechunked": root / "data" / "forcing_rechunked",
                "outputs_disk1": root / "outputs",
            },
        )

    @classmethod
    def load(cls, start: Path | None = None) -> "KissConfig":
        """Find and parse the nearest ``kiss.toml``, walking upward."""
        here = Path(start or Path.cwd()).resolve()
        for cand in (here, *here.parents):
            cfg = cand / CONFIG_NAME
            if cfg.is_file():
                return cls._parse(cfg)
        raise FileNotFoundError(
            f"no {CONFIG_NAME} found in {here} or any parent — run `kiss init` first"
        )

    @classmethod
    def _parse(cls, cfg: Path) -> "KissConfig":
        text = cfg.read_text(encoding="utf-8")
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            # Configs written by earlier Windows builds put raw backslash paths
            # into basic strings, so they no longer parse at all. Repair rather
            # than discard: the user is invited by the file's own comment to
            # edit these paths, and regenerating would throw that away.
            repaired = _repair_backslash_strings(text)
            raw = tomllib.loads(repaired)
            try:
                cfg.write_text(repaired, encoding="utf-8")
            except OSError:
                pass                      # read-only location: parsed is enough

        root = Path(raw.get("kiss", {}).get("root", cfg.parent)).expanduser()
        obj = cls.default(root)
        for role, val in (raw.get("paths") or {}).items():
            obj.roles[role] = Path(val).expanduser()
        obj.python = raw.get("kiss", {}).get("python", obj.python)
        obj.relocation = raw.get("kiss", {}).get("relocation", obj.relocation)
        return obj

    def dumps(self) -> str:
        lines = [
            "# KISS local configuration — created by `kiss init`.",
            "# Edit the paths below to point at where the data actually lives on",
            "# this machine. Everything else is derived from them.",
            "",
            "[kiss]",
            f"root = {_toml_str(self.root)}",
            f"python = {_toml_str(self.python)}",
            f"relocation = {_toml_str(self.relocation)}  # sandbox | port | symlink",
            "",
            "[paths]",
        ]
        for role in sorted(self.roles):
            lines.append(f"{role} = {_toml_str(self.roles[role])}")
        return "\n".join(lines) + "\n"
    def resolve(self, legacy: str) -> Path:
        """Translate an authoring-machine path into this machine's equivalent."""
        for prefix, role in LEGACY_PREFIXES:
            if legacy == prefix or legacy.startswith(prefix + "/"):
                base = self.roles.get(role)
                if base is None:
                    raise KeyError(f"role {role!r} has no path configured in {CONFIG_NAME}")
                rest = legacy[len(prefix):].lstrip("/")
                return base / rest if rest else base
        return Path(legacy)

    def bind_args(self, *, missing_ok: bool = True) -> list[str]:
        """Bubblewrap arguments that recreate the authoring prefixes.

        Each distinct authoring prefix is bound onto the user's real directory
        for that role, so a KI's hardcoded literals resolve correctly with no
        edits to the KI itself.

        Ordering matters: shallower prefixes are emitted first so that a more
        specific role (``.../data/obs``) overrides a broader one (``.../data``)
        rather than being clobbered by it.
        """
        pairs: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for prefix, role in LEGACY_PREFIXES:
            if role in LEAK_ROLES or prefix in seen:
                continue
            target = self.roles.get(role)
            if target is None:
                continue
            if not target.exists():
                if not missing_ok:
                    raise FileNotFoundError(f"{role} path does not exist: {target}")
                target.mkdir(parents=True, exist_ok=True)
            seen.add(prefix)
            pairs.append((prefix, target))

        pairs.sort(key=lambda p: p[0].count("/"))
        args: list[str] = []
        for prefix, target in pairs:
            args += ["--bind", str(target), prefix]
        return args


def with_ki_tools_common(cfg: KissConfig, env: dict[str, str] | None = None) -> dict[str, str]:
    """Expose GeoForge's bundled shared KI library to child Python tools.

    The scientific agents often invoke ``python3`` themselves instead of the
    interpreter recorded in ``kiss.toml``. An editable install into one venv
    therefore cannot guarantee that those child processes can import the
    bundled library. ``PYTHONPATH`` is the process-tree contract: local CLIs,
    direct-API tools, preflight scripts, and their descendants all see the same
    materialised ``ki_tools_common`` copy.
    """
    out = dict(os.environ if env is None else env)
    common = Path(getattr(cfg, "roles", {}).get("ki_tools_common", "")).expanduser()
    if not common.is_dir():
        return out
    existing = [item for item in out.get("PYTHONPATH", "").split(os.pathsep) if item]
    common_text = str(common.resolve())
    if common_text not in existing:
        existing.insert(0, common_text)
    out["PYTHONPATH"] = os.pathsep.join(existing)
    return out


#: Top-level directories the authoring prefixes live under. Each is overlaid
#: with a tmpfs before anything is bound beneath it.
#:
#: This is not cosmetic. In an unprivileged user namespace you cannot mount
#: over a path that sits inside a mount you do not own — and ``/mnt/disk1`` is
#: its own filesystem on the authoring machine. Overlaying ``/mnt`` with a
#: tmpfs first gives bwrap a mount it does own, and it then creates the
#: intermediate directories itself.
OVERLAY_ROOTS = ("/mnt", "/media", "/home")


def bound_prefixes(cfg: KissConfig) -> list[str]:
    """The authoring prefixes this config materialises, deduplicated.

    Agent CLIs enforce their own directory allowlist on top of the namespace.
    Making a path *exist* is not enough — Claude Code will still refuse to read
    it unless the directory was granted with --add-dir. So the caller needs the
    list of prefixes it just synthesised in order to grant them.
    """
    out: list[str] = []
    for prefix, role in LEGACY_PREFIXES:
        if role in LEAK_ROLES or prefix in out:
            continue
        if cfg.roles.get(role) is not None:
            out.append(prefix)
    # Keep only the shallowest of any nested pair; granting a parent covers it.
    keep = [p for p in out if not any(p != q and p.startswith(q + "/") for q in out)]
    return keep


def sandbox_command(cfg: KissConfig, argv: list[str], *, cwd: Path | None = None,
                    extra_binds: list[Path] | None = None,
                    die_with_parent: bool = True) -> list[str]:
    """Wrap ``argv`` so it runs with the authoring prefixes present.

    **This is relocation, not confinement.** The first bind is ``/`` onto ``/``
    with full read/write, so the wrapped process can reach everything the
    calling user can. The namespace exists to make a KI's hardcoded authoring
    paths resolve somewhere real — it is not a security boundary and must not
    be described as one.

    Anything that enters this namespace must enter it *once, together*. Wrapping
    individual commands puts the agent in one world and the model in another:
    the agent then reads a path out of SKILL.md, finds it absent, and improvises
    — which is the exact failure the KI exists to prevent.

    ``die_with_parent`` reaps ordinary children when the caller exits. Jobs
    launched with ``setsid`` deliberately escape it and keep this mount
    namespace alive for as long as they run, which is what lets an hour-long
    simulation outlive the chat turn that started it and still see the
    relocated paths.
    """
    cmd = ["bwrap", "--dev-bind", "/", "/"]
    if die_with_parent:
        cmd += ["--die-with-parent"]

    for root in OVERLAY_ROOTS:
        cmd += ["--tmpfs", root]

    # Role binds first, restores second — bwrap applies in order and the last
    # bind over a path wins.
    cmd += cfg.bind_args()

    # Restores. Everything below must survive the overlays and the role binds,
    # so it is bound last and deliberately outranks them.
    #
    # Two of these are easy to forget and both fail identically, as an opaque
    # `execvp ...: No such file or directory` that names neither the sandbox
    # nor the path it lost:
    #   * the interpreter — a venv under /mnt vanishes with the python_env role
    #   * the agent CLI itself — it usually lives in ~/.local/bin, and the
    #     authoring machine's home ("/home/server") is a relocated role, so on
    #     a machine where that IS the real home the role bind replaces the very
    #     binary we are about to exec.
    restores: list[Path] = []
    home = Path.home()
    if home.exists():
        restores.append(home)
    for extra in (cfg.root, cwd, *(extra_binds or ())):
        if extra is not None:
            restores.append(Path(extra))
    interpreter = Path(cfg.python)
    if interpreter.is_absolute():
        # Bind the environment root (…/bin/python -> …), not just the file, so
        # site-packages and the rest of the venv come with it.
        restores.append(interpreter.parent.parent if interpreter.parent.name == "bin"
                        else interpreter.parent)

    seen_keep: set[str] = set()
    for p in restores:
        try:
            rp = p.resolve()
        except OSError:
            continue
        s = str(rp)
        if not s.startswith(OVERLAY_ROOTS) or s in seen_keep or not rp.exists():
            continue
        seen_keep.add(s)
        cmd += ["--bind", s, s]
    if cwd:
        cmd += ["--chdir", str(cwd)]
    return cmd + ["--"] + argv


def have_sandbox() -> bool:
    from shutil import which

    return which("bwrap") is not None


# --- runtime helper, importable from inside a ported KI ----------------------

_ACTIVE: KissConfig | None = None


def active() -> KissConfig:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = KissConfig.load(Path(os.environ.get("KISS_ROOT", Path.cwd())))
    return _ACTIVE


def P(role: str, *parts: str) -> Path:
    """Path helper for ported KI code: ``P("obs", "BB/51080_bengbu.txt")``."""
    base = active().roles[role]
    return base.joinpath(*parts) if parts else base


#: Read-only system directories a process needs simply to execute: the loader,
#: shared libraries, certificates, timezone data. Binding these is not a policy
#: decision — without them nothing runs at all, including /bin/sh.
SYSTEM_ROOTS = ("/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc", "/opt", "/var/lib")


def confined_command(cfg: KissConfig, argv: list[str], grants,
                     *, cwd: Path | None = None,
                     writable: list[Path] | None = None) -> list[str]:
    """Build a namespace that contains *only* what ``grants`` allow.

    This is the counterpart to :func:`sandbox_command`. That one starts from
    ``--dev-bind / /`` and remaps paths; it is a convenience, not a boundary.
    This one starts from nothing and adds only granted paths, so a directory
    the policy did not grant is not merely forbidden — it does not exist.

    That distinction matters because the agent's own permission layer cannot
    give us least privilege: an inherited settings file may already allow far
    more than this KI needs, and a denylist cannot express "only these paths".
    A path that is absent from the mount namespace needs no rule.

    System directories are bound read-only so the dynamic loader, shell and
    libraries work. Everything else comes from the policy.
    """
    cmd = ["bwrap", "--die-with-parent", "--unshare-pid", "--proc", "/proc", "--dev", "/dev"]

    for root in SYSTEM_ROOTS:
        p = Path(root)
        if p.exists():
            cmd += ["--ro-bind", root, root]

    # Writable scratch, plus an empty tmpfs at each root the grants live under
    # so bwrap owns those mounts and can create the intermediate directories
    # itself. Without this a grant deep under /home fails to bind because its
    # parent does not exist in the new root.
    cmd += ["--tmpfs", "/tmp"]
    for root in (*OVERLAY_ROOTS, "/srv", "/data"):
        if Path(root).exists() or root in OVERLAY_ROOTS:
            cmd += ["--tmpfs", root]

    write_set = {str(Path(w).resolve()) for w in (writable or [])}
    seen: set[str] = set()
    for g in grants:
        target = Path(g.path)
        # Grants come in two spellings for the same bytes: the host path and
        # the authoring path the KI hardcodes. An authoring path must always be
        # translated to its host source — never bound to itself. On the machine
        # the KIs were authored on both spellings exist, so testing existence
        # first would bind authoring->authoring and quietly re-expose the
        # original tree.
        if classify(str(target)) is not None:
            try:
                src = cfg.resolve(str(target))
            except KeyError:
                continue
        else:
            src = target
        # bwrap resolves symlinks, so a link pointing outside the bind set
        # fails with the *link target* in the message and no hint of which
        # grant produced it. Resolve here so the source we name is the source
        # that gets mounted.
        try:
            src = src.resolve()
        except OSError:
            continue
        if not src.exists():
            continue
        dest = str(target)
        if dest in seen:
            continue
        seen.add(dest)
        ro = g.kind == "read" and str(src.resolve()) not in write_set
        cmd += ["--ro-bind" if ro else "--bind", str(src), dest]

    home = Path.home()
    if home.exists():
        # The agent CLI's own credentials and binary live here. Bound read-only
        # so a granted-nothing policy still lets the agent authenticate.
        for sub in (".claude", ".local/bin", ".config"):
            p = home / sub
            if p.exists():
                cmd += ["--ro-bind", str(p), str(p)]

    if cwd:
        cmd += ["--chdir", str(cwd)]
    return cmd + ["--"] + argv
