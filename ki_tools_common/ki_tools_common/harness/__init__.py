"""ki_tools_common.harness — the KI-usage harness, in its NEUTRAL home (moved 2026-08-18).

One contract for how ANY agent uses a model KI. Drivers (self-improve loop, GeoForge chat,
ata-kdt, future runners) import from HERE; the copies under
knowledge-dissection-toolkit/auto_dissect_multi_agent/ are back-compat SHIMS over this package
(same pattern as auto_dissect/ shims — edit the source here, never the shims).

    from ki_tools_common.harness import contract, manifest, tool_command, run_preflight
    from ki_tools_common.harness import resolve_ki_path, attention_digest, clean_env
"""
from .ki_harness import (contract, manifest, tool_command, run_preflight,
                         assert_injected, KiHarnessError, MARKER)
from .ki_path import resolve as resolve_ki_path
from .ki_attention import digest as attention_digest
from .agent_spawn import clean_env
