"""ki_tools_common.flow — the driver-neutral plan → approve → execute → verify flow.

Sibling of `ki_tools_common.harness`, NOT part of it: the harness says how an agent
uses ONE KI (text only); the flow says WHEN an agent may plan, ask, run and claim
"done", and proves it with app-written receipts. The flow imports the harness; the
harness never imports the flow (KI_HARNESS_SPEC.md L148: "turn-taking is not
harness business").

Design: ANALYSIS/06_PLAN_harness_flow_v2.md; file map: 07_PLAN_v3_file_map.md
(both in the ki-harness-snapshot-20260829 repo).

    from ki_tools_common.flow import states, resolve, plan, approval, contracts, receipts, policy
"""
from __future__ import annotations

__all__ = ["states", "resolve", "plan", "approval", "contracts", "receipts", "policy",
           "FlowError", "State", "Capability", "Enforcement", "FlowContext"]

from .states import FlowError, State, Capability, Enforcement, FlowContext  # noqa: E402,F401


def __getattr__(name):
    if name in ("states", "resolve", "plan", "approval", "contracts", "receipts", "policy", "declared", "tools"):
        import importlib
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
