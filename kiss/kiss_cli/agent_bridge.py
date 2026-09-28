"""Run only the shipped IPC adapters, not arbitrary Python files or commands."""
from __future__ import annotations

import sys


def _utf8_stdio() -> None:
    # Frozen Python ignores PYTHONUTF8 at interpreter startup. Agents consume
    # these pipes as UTF-8, not the Windows console's legacy ANSI code page.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    from .flowrun import _DATABASE_HELPER, _FLOW_HELPER

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {"flow", "database"}:
        print("usage: geoforge-agent-bridge {flow|database} [arguments]", file=sys.stderr)
        return 2
    mode, *arguments = arguments
    source = _FLOW_HELPER if mode == "flow" else _DATABASE_HELPER
    namespace = {"__name__": "geoforge_ipc_adapter"}
    exec(compile(source, f"<geoforge-{mode}-adapter>", "exec"), namespace)
    previous = sys.argv
    try:
        sys.argv = [f"geoforge-{mode}", *arguments]
        return namespace["main"]()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    raise SystemExit(main())
