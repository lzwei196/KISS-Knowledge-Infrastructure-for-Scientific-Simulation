"""Shared helpers for EPIC KI tools."""
import os
import sys
import shutil

KI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES_DIR = os.path.join(KI_DIR, "templates")
MODEL_DIR = os.path.abspath(os.path.join(KI_DIR, ".."))

# The EPIC 1102 binary used to be hard-coded to the dissection scratch
# workspace (_work_v2/EPIC/epic_workspace/...), which is transient: once that
# tree was cleaned the KI could not run at all (preflight_check reported
# "EPIC 1102 binary: NOT FOUND" while the durable install sat at
# <MODEL_DIR>/bin/). Resolve against the durable install first and keep the
# legacy scratch path only as a last-resort fallback.
BINARY_CANDIDATES = [
    os.path.join(MODEL_DIR, "bin", "epic1102-official_release.exe"),
    os.path.join(MODEL_DIR, "source", "repo", "epic1102-official_release.exe"),
    os.path.join(KI_DIR, "bin", "epic1102-official_release.exe"),
    "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/"
    "_work_v2/EPIC/epic_workspace/epic1102-official_release.exe",
]


def resolve_binary(explicit=None):
    """Return the first EPIC binary path that exists.

    Order: explicit argument -> $EPIC_BINARY -> durable model install ->
    legacy dissection scratch workspace. If none exist, returns the first
    candidate so the caller still raises a clear FileNotFoundError.
    """
    cands = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("EPIC_BINARY")
    if env:
        cands.append(env)
    cands.extend(BINARY_CANDIDATES)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return cands[0]


DEFAULT_BINARY = resolve_binary()


def template_path(name):
    p = os.path.join(TEMPLATES_DIR, name)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"Template {name} not found at {p}")
    return p


def copy_template(name, dst_dir, new_name=None):
    src = template_path(name)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, new_name or name)
    shutil.copy2(src, dst)
    return dst


def read_text_crlf(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode("ascii", errors="replace")


def write_text_crlf(path, text):
    if not text.endswith("\n"):
        text += "\n"
    norm = text.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(path, "wb") as f:
        f.write(norm.encode("ascii", errors="replace"))


def add_kdt_common_to_path():
    candidates = [
        "/home/server/knowledge-dissection-toolkit/ki_tools_common",
        "/home/server/knowledge-dissection-toolkit/kdt-release/ki_tools_common",
    ]
    for c in candidates:
        if os.path.isdir(c):
            parent = os.path.dirname(c)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            return True
    return False
