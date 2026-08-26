"""ki_tools_common.harness — the KI-usage harness, in its NEUTRAL home (moved 2026-08-18).

One contract for how ANY agent uses a model KI. Drivers (self-improve loop, GeoForge chat,
ata-kdt, future runners) import from HERE; the copies under
knowledge-dissection-toolkit/auto_dissect_multi_agent/ are back-compat SHIMS over this package
(same pattern as auto_dissect/ shims — edit the source here, never the shims).

    from ki_tools_common.harness import contract, manifest, tool_command, run_preflight
    from ki_tools_common.harness import resolve_ki_path, attention_digest, clean_env
"""
# Lazy exports (PEP 562): eager `from .ki_path import ...` here made `python -m
# ki_tools_common.harness.ki_path` emit a runpy RuntimeWarning (module already in
# sys.modules) — the CLIs the chat prompts advertise must run with clean stderr.
_EXPORTS = {
    "contract": ("ki_harness", "contract"),
    "manifest": ("ki_harness", "manifest"),
    "tool_command": ("ki_harness", "tool_command"),
    "run_preflight": ("ki_harness", "run_preflight"),
    "assert_injected": ("ki_harness", "assert_injected"),
    "KiHarnessError": ("ki_harness", "KiHarnessError"),
    "MARKER": ("ki_harness", "MARKER"),
    "resolve_ki_path": ("ki_path", "resolve"),
    "attention_digest": ("ki_attention", "digest"),
    "clean_env": ("agent_spawn", "clean_env"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        mod_name, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib
    return getattr(importlib.import_module(f".{mod_name}", __name__), attr)
