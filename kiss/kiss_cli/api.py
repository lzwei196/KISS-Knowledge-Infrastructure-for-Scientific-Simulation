"""The API driver: talk to a model directly instead of spawning an agent CLI.

The CLI driver reuses an agent the user has already installed and signed in, so
it needs no key and inherits that agent's tools. This driver is the other half:
an API key, and KISS owns the loop.

Two things follow from owning the loop, and they are the reason to have it:

* **The tools are typed.** The model asks for ``run_preflight`` or
  ``read_ki_file(path)``; it cannot express an arbitrary shell command. The
  permission question changes from "is this command safe" — undecidable from a
  string — to "is this argument in range", which is checkable.
* **It can stop and ask mid-turn.** A one-shot ``claude -p`` exits when the turn
  ends, so a CLI agent can only ask between turns. Here the loop is ours, so a
  request for approval can suspend it and resume on an answer.

No SDK dependency: both wire formats are a single POST of JSON, and taking a
dependency on two vendor SDKs to send one request each would be a poor trade for
a tool meant to install cleanly anywhere.
"""

from __future__ import annotations

import csv
import itertools
import http.client
import ssl
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from . import skilllib, tls
from .presentation import activity_marker

TIMEOUT = 300
# Hard wall-clock cap for one streamed provider response.  The socket timeout
# only bounds silence between chunks; a proxy sending keep-alive lines could
# otherwise hold a dead or looping generation open forever.
STREAM_MAX_SECONDS = 900
# A plan plus its data inventory is easily 20 KB of JSON in one tool call.
# DeepSeek's default output limit (4K tokens) truncated exactly that call.
MAX_OUTPUT_TOKENS = 8192
INTAKE_ESTIMATE_CAP = 5          # read-only clip estimates allowed while understanding the task


class TurnHandle:
    """Stop switch and heartbeat for one in-process API turn.

    A provider turn has no child process, so the GUI needs its own way to
    stop it and to see that the stream is still delivering chunks.  ``stop``
    closes the in-flight HTTP response, which unblocks the reading thread.
    """

    def __init__(self):
        self.stopped = threading.Event()
        self.last_chunk_at: float | None = None
        self._response = None
        self._lock = threading.Lock()

    def attach(self, response) -> None:
        with self._lock:
            self._response = response
            if self.stopped.is_set():
                self._close_locked()

    def detach(self) -> None:
        with self._lock:
            self._response = None

    def stop(self) -> None:
        self.stopped.set()
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        response, self._response = self._response, None
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001 — closing is best-effort
                pass


@dataclass
class ApiProvider:
    """One API endpoint and how to authenticate to it."""

    name: str
    label: str
    #: "anthropic" (native messages API) or "openai" (chat/completions shape)
    wire: str
    base_url: str
    env_key: str
    models: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    signup: str = ""

    def key(self) -> str | None:
        return os.environ.get(self.env_key) or None

    def available(self) -> bool:
        return bool(self.key())


#: Mirrors the provider table the HydroCraft backend already serves, so a key
#: that works there works here.
PROVIDERS: dict[str, ApiProvider] = {
    "anthropic": ApiProvider(
        name="anthropic", label="Claude (API)", wire="anthropic",
        base_url="https://api.anthropic.com/v1/messages",
        env_key="ANTHROPIC_API_KEY",
        models={"claude-sonnet-4-5": "claude-sonnet-4-5",
                "claude-opus-4-1": "claude-opus-4-1"},
        default_model="claude-sonnet-4-5",
        signup="https://console.anthropic.com/settings/keys",
    ),
    "deepseek": ApiProvider(
        name="deepseek", label="DeepSeek (API)", wire="openai",
        base_url="https://api.deepseek.com/chat/completions",
        env_key="DEEPSEEK_API_KEY",
        models={"deepseek-chat": "deepseek-chat",
                "deepseek-reasoner": "deepseek-reasoner"},
        default_model="deepseek-chat",
        signup="https://platform.deepseek.com/api_keys",
    ),
    "openai": ApiProvider(
        name="openai", label="OpenAI (API)", wire="openai",
        base_url="https://api.openai.com/v1/chat/completions",
        env_key="OPENAI_API_KEY",
        models={"gpt-4o": "gpt-4o", "gpt-4o-mini": "gpt-4o-mini"},
        default_model="gpt-4o",
        signup="https://platform.openai.com/api-keys",
    ),
    "openrouter": ApiProvider(
        name="openrouter", label="OpenRouter (API)", wire="openai",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        env_key="OPENROUTER_API_KEY",
        models={"claude-sonnet-4-5": "anthropic/claude-sonnet-4.5",
                "deepseek-chat": "deepseek/deepseek-chat"},
        default_model="deepseek-chat",
        signup="https://openrouter.ai/keys",
    ),
}


def available() -> list[ApiProvider]:
    return [p for p in PROVIDERS.values() if p.available()]


# --- the tools the model may call ------------------------------------------
#
# Deliberately typed and narrow. There is no `bash` here: a KI declares what a
# model needs, so the useful operations are enumerable, and enumerating them is
# what lets the permission layer check an argument instead of guessing at a
# command string.

def tool_schemas(ki, *, setup_mode: bool = False,
                 project_mode: bool = False, flow=None,
                 installation_only: bool = False) -> list[dict]:
    """``flow`` (a flowgate.FlowSession) filters the list by the project's flow state
    (plan v3 B4): the agent never sees a tool it may not call in this state."""
    installation_only = installation_only or (setup_mode and flow is not None)
    tools = [
        {
            "name": "read_ki_file",
            "description": (
                "Read a file from this model's Knowledge Infrastructure package "
                "(SKILL.md, dag.yaml, diagnostics/triplets, docs/, tools/). "
                "Always read SKILL.md before proposing how to run the model."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "path relative to the KI root, e.g. 'SKILL.md'"},
                    "start_line": {"type": "integer", "minimum": 1,
                                   "description": "first line to return; defaults to 1"},
                    "line_count": {"type": "integer", "minimum": 1, "maximum": 2000,
                                   "description": "maximum lines to return; defaults to 1000"},
                    "ki": {"type": "string",
                           "description": "which selected KI to read (multi-model chats); default: the primary KI"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_ki_files",
            "description": "List the files in this KI package, optionally under a subdirectory.",
            "input_schema": {
                "type": "object",
                "properties": {"subdir": {"type": "string"},
                               "ki": {"type": "string",
                                      "description": "which selected KI to list (multi-model chats)"}},
            },
        },
        {
            "name": "run_preflight",
            "description": (
                "Run this KI's preflight_check.py and return its output. This is "
                "the authoritative answer to whether the model is ready to run."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_skills",
            "description": (
                "List the agent skills installed on this machine (name + one-line "
                "description). Skills are reusable instruction packages — use one "
                "when a task matches its description (plotting, statistics, "
                "literature review, document formats, ...)."
            ),
            "input_schema": {"type": "object",
                             "properties": {"query": {"type": "string",
                                            "description": "optional substring filter"}}},
        },
        {
            "name": "read_skill",
            "description": (
                "Read one installed skill's SKILL.md instructions by name. Read it "
                "before applying the skill; follow it like a procedure."
            ),
            "input_schema": {"type": "object",
                             "properties": {"name": {"type": "string"}},
                             "required": ["name"]},
        },
        {
            "name": "search_diagnostics",
            "description": (
                "Search this KI's diagnostics/triplets for an error keyword. Use "
                "this before debugging from first principles — the failure is "
                "often already catalogued with a verified remedy."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    ]
    if project_mode:
        tools += [
            {
                "name": "list_project_files",
                "description": (
                    "List files already present in this chat's local project. "
                    "Inspect these before asking the user to supply data."
                ),
                "input_schema": {"type": "object", "properties": {
                    "subdir": {"type": "string",
                               "description": "relative project directory, normally inputs"},
                }},
            },
            {
                "name": "read_project_file",
                "description": (
                    "Preview up to 120000 characters from a text file in this chat's local "
                    "project, including large CSV files. A truncated preview does not establish "
                    "full-file coverage or record counts. Use a format-aware KI reader for "
                    "binary files or complete dataset analysis."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                }, "required": ["path"]},
            },
            {
                "name": "write_project_file",
                "description": (
                    "Write a small prepared input, run configuration, provenance "
                    "record, or report inside the chat project. Use the KI's tools "
                    "for generated grids and large scientific files."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string",
                             "description": "relative path under inputs, runs, outputs, artifacts, or references"},
                    "content": {"type": "string"},
                }, "required": ["path", "content"]},
            },
            {
                "name": "run_ki_tool",
                "description": (
                    "Run one Python preparation tool shipped inside the selected KI. "
                    "Use this for data conversion, grid/soil/weather preparation, "
                    "configuration generation, validation, and model harness steps. "
                    "Arguments may reference this chat project, this KI package, or "
                    "the current KI's GeoForge-managed shared binaries directory. "
                    "Read the shipped tool or wrapper's documented flags; do not guess argument names. "
                    "Write generated scientific results to a fresh outputs/<run>/ or artifacts/ "
                    "directory consistent with the approved plan. An arbitrary runs/<name> "
                    "directory is bookkeeping and is not captured as scientific output; "
                    "runs/logs/ is the tracked log exception. Process success alone is insufficient. "
                    "Do not replace a KI tool with improvised calculations. Required "
                    "environment values are taken automatically from this approved plan step; "
                    "do not try to install startup hooks or mutate the system environment."
                ),
                "input_schema": {"type": "object", "properties": {
                    "tool_path": {"type": "string", "description": "Python tool path relative to the KI root, "
                                  "including tools/, for example tools/s5_execution/run_crhm.py. "
                                  "An absolute Python path stored in an approved plan is not the API "
                                  "tool address; use its KI-root-relative path here. Only a model "
                                  "binary declared by the KI may use an absolute path."},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string",
                            "description": "relative project working directory; defaults to project root"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "ki": {"type": "string",
                           "description": "which selected KI the tool belongs to (multi-model runs); "
                                          "defaults to the chat's primary KI"},
                    "plan_step_id": {"type": "string",
                                     "description": "the approved plan step this run executes "
                                                    "(runs/plan.json steps[].id); required once a "
                                                    "plan is approved — the receipt is bound to it"},
                }, "required": ["tool_path"]},
            },
            {
                "name": "write_project_data_tool",
                "description": (
                    "Planning/replan only: write a small project-local Python reader, converter or data check "
                    "when no suitable shipped data tool exists. Executes nothing. Use acquired project inputs or "
                    "explicit inventory files from this selected KI's project-local test_cases (data/metadata only); "
                    "directory traversal requires a declared case inputs/ directory. Never read or execute KI code. "
                    "preserve raw values/flags/units and missingness; never invent model output or replace model science. "
                    "Return includes the exact tool path and project_data_tool binding: fill its arguments, cwd "
                    "and timeout_seconds, then include it in a kind=check or prepare plan step for normal review. "
                    "This is trusted reviewed source, not an OS sandbox. Data outputs must be fresh outputs/ or "
                    "artifacts/ files, including staging. Unsupported formats pass structure checks only as exact "
                    "byte/hash copies of granted inputs; this is not scientific validation. No network, native "
                    "process, credential access or input modification."),
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {
                    "ki": {"type": "string"}, "name": {"type": "string", "description": "short Python identifier, without .py"},
                    "source": {"type": "string"}, "purpose": {"type": "string", "enum": ["reader", "converter", "check"]},
                }, "required": ["ki", "name", "source", "purpose"]},
            },
            {
                "name": "run_project_data_tool",
                "description": (
                    "Run the exact approved project-local data reader/converter/check with a signed receipt. "
                    "Use the existing plan's project_data_tool invocation; omit arguments/cwd/timeout to use "
                    "its reviewed values. Different source or invocation requires request_replan and review. "
                    "Inputs are read-only; write fresh outputs/ or artifacts/ files. SQLite uses a file URI "
                    "with mode=ro, uri=True and PRAGMA query_only=ON. No model/native execution or network."),
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {
                    "ki": {"type": "string"}, "tool_path": {"type": "string"}, "plan_step_id": {"type": "string"},
                    "arguments": {"type": "array", "items": {"type": "string"}}, "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                }, "required": ["ki", "tool_path", "plan_step_id"]},
            },
            {
                "name": "write_calibration_adapter",
                "description": (
                    "Planning only. Prepare a selected KI's project calibration contract and "
                    "Python runner for review. Writes only calibration/kis/<KI>/calibration.yaml "
                    "and tools/calib_run.py; executes nothing. The contract must invoke the "
                    "Python interpreter followed by {ki_path}/tools/calib_run.py. Use the real "
                    "model KI, explicit parameter bounds, observation provenance and independent "
                    "holdout. Then submit a kind=calibrate plan step for approval."),
                "input_schema": {"type": "object", "additionalProperties": False, "properties": {
                    "ki": {"type": "string", "description": "One of this project's selected KIs."},
                    "contract": {"type": "object", "description": "The calibration.yaml contract as an object."},
                    "runner_source": {"type": "string", "description": "Full Python source of tools/calib_run.py."},
                }, "required": ["ki", "contract", "runner_source"]},
            },
            {
                "name": "run_calibration",
                "description": (
                    "Run this KI's project calibration adapter through GeoForge's "
                    "bundled calibration engine. numpy, SPOTPY, and pymoo run "
                    "inside the app, not the user's system Python. Use only after "
                    "the real model, observations, adapter, and holdout definition "
                    "are ready. The full report and engine log are saved in the "
                    "chat project's calibration/runs directory. Approval requires kind=calibrate, "
                    "tool=the absolute project adapter runner path, and calibration={algorithm, "
                    "budget, seed, determining_metric, obs_shape_by_var}; the host fills bound hashes."
                ),
                "input_schema": {"type": "object", "properties": {
                    "obs_shape_by_var": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": (
                            "Map every calibration target variable exactly as named "
                            "in calibration.yaml to its dag observation shape."
                        ),
                    },
                    "algorithm": {"type": "string", "enum": [
                        "dds", "sceua", "dream", "nsga2", "nsga3", "moead"]},
                    "budget": {"type": "integer", "minimum": 1, "maximum": 10000},
                    "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                    "determining_metric": {"type": "string"},
                    "plan_step_id": {"type": "string", "description":
                        "The approved kind=calibrate step, bound to this project's adapter, "
                        "contract, algorithm, budget, seed, target shapes and metric."},
                }, "required": ["obs_shape_by_var"]},
            },
            {
                "name": "create_project_plot",
                "description": (
                    "Create a safe line, scatter, or bar plot in this chat's "
                    "artifacts folder. Use a relevant plotting/visualization skill "
                    "to choose an honest chart, then call this tool when the direct "
                    "API has no plotting runtime. GeoForge displays the SVG inline. "
                    "For a project CSV, prefer source_path plus x_column/y_column "
                    "instead of copying every data point through the model."
                ),
                "input_schema": {"type": "object", "properties": {
                    "output_path": {"type": "string",
                                    "description": "relative .svg path below artifacts/"},
                    "kind": {"type": "string", "enum": ["line", "scatter", "bar"]},
                    "title": {"type": "string"},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "y2_label": {"type": "string",
                                 "description": "optional right-axis label"},
                    "source_path": {"type": "string",
                                    "description": "optional relative .csv file in this chat project"},
                    "x_column": {"type": "string",
                                 "description": "CSV column used for the x axis"},
                    "series": {"type": "array", "items": {"type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "x": {"type": "array", "items": {}},
                            "y": {"type": "array", "items": {"type": "number"}},
                            "y_column": {"type": "string",
                                         "description": "CSV column used for this series"},
                            "axis": {"type": "string", "enum": ["left", "right"],
                                     "description": "use right when units or scale differ from the main series"},
                        }, "required": ["y"]}},
                }, "required": ["output_path", "series"]},
            },
            {
                "name": "publish_project_view",
                "description": (
                    "Publish or update this chat's safe dynamic Project View after "
                    "creating real artifacts. GeoForge renders the declared metrics, "
                    "images, animations, maps, CSV tables, files, and 3D-model "
                    "previews; it never executes model-written HTML or JavaScript. "
                    "Every path must name an existing file below artifacts/."
                ),
                "input_schema": {"type": "object", "properties": {
                    "version": {"type": "integer", "enum": [1]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "layout": {"type": "string", "enum": ["grid", "single"]},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "kis": {"type": "array", "items": {"type": "string"}},
                    "panels": {"type": "array", "maxItems": 24, "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "kind": {"type": "string", "enum": [
                                "metric", "image", "animation", "map", "table",
                                "file", "model3d"]},
                            "title": {"type": "string"},
                            "caption": {"type": "string"},
                            "status": {"type": "string"},
                            "value": {},
                            "unit": {"type": "string"},
                            "path": {"type": "string"},
                            "renderer": {"type": "string"},
                        }, "required": ["kind", "title"]}},
                }, "required": ["title", "panels"]},
            },
            {
                "name": "request_user_action",
                "description": (
                    "Pause project preparation and show one concrete action to the "
                    "user. During planning, ask ONE unresolved decision at a time, "
                    "including a critical parameter set or data-source choice. Offer "
                    "the KI-supported default with its evidence and allow a custom answer. "
                    "Do not re-ask settled choices or ask about every low-level default. "
                    "Also use for protected downloads, licence/login, or system permission."
                ),
                "input_schema": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": [
                        "download", "licence", "login", "permission", "choice", "other"]},
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "options": {"type": "array", "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "response": {"type": "string",
                                         "description": "exact answer sent back to the agent when selected"},
                        }, "required": ["label"]}},
                    "allow_note": {"type": "boolean"},
                    "url": {"type": "string"},
                    "expected_path": {"type": "string"},
                    "command": {"type": "string"},
                    "resume_hint": {"type": "string"},
                }, "required": ["kind", "title", "message"]},
            },
        ]
    if project_mode or setup_mode:
        tools.append({
            "name": "report_project_progress",
            "description": (
                "Update GeoForge's small project-status display at a meaningful "
                "transition. Report only work actually reached. This records use "
                "of the general KI; it does not create an adaptive KI harness."
            ),
            "input_schema": {"type": "object", "properties": {
                "stage": {"type": "string", "enum": [
                    "understanding", "choosing_ki", "software", "researching",
                    "preparing", "validating", "running", "results"]},
                "status": {"type": "string", "enum": [
                    "idle", "working", "waiting_for_user", "complete", "failed"]},
                "goal": {"type": "string", "description": (
                    "The current modelling goal. Include this only when the user "
                    "has materially replaced or refined the scientific case; do "
                    "not replace it for a simple continue/retry message."
                )},
                "summary": {"type": "string"},
                "selected_kis": {"type": "array", "items": {"type": "string"}},
                "intake": {"type": "object", "description": (
                    "Structured task understanding. GeoForge validates the KI names and will "
                    "enter planning only when ready_for_planning is true."
                ), "properties": {
                    "ready_for_planning": {"type": "boolean"},
                    "understanding": {"type": "string"},
                    "study_area": {"type": "string"},
                    "period": {"type": "string"},
                    "process": {"type": "string"},
                    "scenario": {"type": "string"},
                    "requested_outputs": {"type": "array", "items": {"type": "string"}},
                    "missing": {"type": "array", "items": {"type": "string"}},
                }, "required": ["ready_for_planning", "understanding", "missing"]},
            }, "required": ["stage", "status", "summary"]},
        })
    if setup_mode:
        tools += [
            {
                "name": "run_builtin_setup",
                "description": (
                    "Run GeoForge's bundled setup recipe and return its full step "
                    "report. Use it as a fast first attempt, then diagnose and repair "
                    "the first real failure instead of stopping."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_work_files",
                "description": "List files in the writable model setup workspace.",
                "input_schema": {"type": "object", "properties": {
                    "subdir": {"type": "string", "description": "relative workspace path"},
                }},
            },
            {
                "name": "read_work_file",
                "description": (
                    "Read a text file from the writable setup workspace. Use "
                    "start_line/line_count to page through large build files."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "line_count": {"type": "integer", "minimum": 1,
                                   "maximum": 2000},
                }, "required": ["path"]},
            },
            {
                "name": "write_work_file",
                "description": (
                    "Write a small text file inside the model setup workspace. "
                    "Use this to repair build files or configuration, not to replace "
                    "the scientific model with a surrogate."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                }, "required": ["path", "content"]},
            },
            {
                "name": "replace_work_text",
                "description": (
                    "Apply one exact, bounded text replacement inside an "
                    "existing setup-workspace file. Use this for a small "
                    "source/build portability patch when rewriting the whole "
                    "file would be unsafe. The old text must match exactly "
                    "apart from LF/CRLF line endings; replacement lines keep the matched file's newline style."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string", "minLength": 1},
                    "new": {"type": "string"},
                    "expected_count": {"type": "integer", "minimum": 1,
                                       "maximum": 20},
                }, "required": ["path", "old", "new"]},
            },
            {
                "name": "run_setup_command",
                "description": (
                    "Run one non-shell command inside the model workspace and return "
                    "stdout, stderr, and its exit code. The executable, working "
                    "directory, and explicit path arguments are checked against a "
                    "build-tool/workspace allowlist; sudo, inline Python, credentials, "
                    "and system package installation are intentionally unavailable. "
                    "env.PATH may contain workspace-local toolchain directories; "
                    "GeoForge validates and prepends them to the inherited PATH."
                ),
                "input_schema": {"type": "object", "properties": {
                    "argv": {"type": "array", "items": {"type": "string"},
                             "description": "argument vector, e.g. [\"cmake\",\"-S\",\".\",\"-B\",\"build\"]"},
                    "cwd": {"type": "string", "description": "relative workspace directory"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "env": {"type": "object", "additionalProperties": {"type": "string"}},
                }, "required": ["argv"]},
            },
            *([{
                "name": "publish_setup_output",
                "description": (
                    "Copy a completed generated output or run directory from the "
                    "model setup workspace into this chat project. Use this after "
                    "a successful setup-mode simulation so full binary/text results "
                    "are preserved in the session without rerunning or encoding them "
                    "through chat."
                ),
                "input_schema": {"type": "object", "properties": {
                    "source": {"type": "string",
                               "description": "relative path below outputs/, runs/, or data/ in the setup workspace"},
                    "destination": {"type": "string",
                                    "description": "relative path below inputs/, runs/, outputs/, artifacts/, or references/ in the chat project"},
                }, "required": ["source", "destination"]},
            }] if project_mode else []),
            {
                "name": "request_user_action",
                "description": (
                    "Pause setup and put one concrete human action on GeoForge's "
                    "Setup page. Use only for a licence, protected download, login, "
                    "system privilege, or scientific choice you cannot resolve."
                ),
                "input_schema": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": [
                        "download", "licence", "login", "permission", "choice", "other"]},
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "options": {"type": "array", "maxItems": 8, "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "response": {"type": "string",
                                         "description": "exact answer sent back to the agent when selected"},
                        }, "required": ["label"]}},
                    "allow_note": {"type": "boolean"},
                    "url": {"type": "string"},
                    "expected_path": {"type": "string"},
                    "command": {"type": "string"},
                    "resume_hint": {"type": "string"},
                }, "required": ["kind", "title", "message"]},
            },
        ]
    if project_mode:
        tools += [
            {
                "name": "search_catalogue",
                "description": (
                    "Search the GeoForge Database catalogue (local copy, no credentials). Filter by "
                    "keywords, bbox, period, variable, category or delivery. Pass parent_id to list the "
                    "real delivery children of a split product instead of a keyword search. Results are "
                    "metadata: 'served' downloads after approval, 'manual' is handed to the user after "
                    "approval (a normal path, never a dead end). Record the exact dataset id in the plan."
                ),
                "input_schema": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "keywords, variable, place, or dataset id"},
                    "bbox": {"type": "string", "description": "min_lon,min_lat,max_lon,max_lat (WGS84)"},
                    "start": {"type": "string", "description": "YYYY-MM-DD"},
                    "end": {"type": "string", "description": "YYYY-MM-DD"},
                    "variable": {"type": "string", "description": "comma-separated variable names, e.g. prec,temp"},
                    "category": {"type": "string", "description": "forcing, gauge, gridded, static_dataset, ..."},
                    "delivery": {"type": "string", "enum": ["served", "manual"]},
                    "parent_id": {"type": "string", "description": "split product to resolve into children; combine with variable/start/end/time_step/bbox"},
                    "time_step": {"type": "string", "enum": ["daily", "3hr"]},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                }},
            },
            {
                "name": "describe_dataset",
                "description": (
                    "Read the live source-file schema of one catalogue dataset: exact variable names, "
                    "units, dimensions, member files, versions. Call it before estimate_clip; use the "
                    "returned names, not catalogue labels. Read-only; proves nothing about data values."
                ),
                "input_schema": {"type": "object", "properties": {
                    "dataset_id": {"type": "string"},
                }, "required": ["dataset_id"]},
            },
            {
                "name": "estimate_clip",
                "description": (
                    "Read-only estimate of a server-side clip: output bytes, parts, grid, versions. "
                    "Use exact source names from describe_dataset; an empty variables list means the "
                    "whole file. Creates no job and no download. Put the returned acquisition_id on the "
                    "matching data-inventory item in write_plan; the user approves it with the plan."
                ),
                "input_schema": {"type": "object", "properties": {
                    "dataset_id": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "variables": {"type": "array", "items": {"type": "string"}},
                    "start": {"type": "string"}, "end": {"type": "string"},
                }, "required": ["dataset_id", "bbox"], "additionalProperties": False},
            },
            {
                "name": "estimate_preparation",
                "description": (
                    "Inspect a read-only server plan to prepare inputs for a specific model KI step. "
                    "State the source, output mode, site/grid and exact dates explicitly. Review native "
                    "cadence, transforms, outputs and blockers. This creates no job or download and "
                    "does not establish input readiness. Its preparation_id is an estimate reference, "
                    "not an acquisition_id for write_plan. Never silently fall back to raw data."
                ),
                "input_schema": {"type": "object", "properties": {
                    "model": {"type": "string", "enum": ["shaw", "crhm", "vic"]},
                    "ki_step": {"type": "string"}, "ki_version": {"type": "string"},
                    "source": {"type": "string", "enum": ["cmfd", "nasa_power", "mswx"]},
                    "mode": {"type": "string", "enum": ["daily", "hourly", "3-hourly"]},
                    "lat": {"type": "number"}, "lon": {"type": "number"},
                    "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "grid_res": {"type": "number"},
                    "start": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                    "end": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                    "utc_offset": {"type": "integer"},
                }, "required": ["model", "source", "mode", "start", "end"], "additionalProperties": False},
            },
            {
                "name": "request_replan",
                "description": (
                    "EXECUTING or COMPLETED. Use when the user requests work beyond a completed "
                    "phase, or when the approved plan cannot be carried out as written "
                    "(a tool needs a different input, a data source is unusable, a step or "
                    "scientific choice must change). GeoForge moves the project to REPLAN_REQUIRED, "
                    "revokes the approval, and makes write_plan available immediately, so you "
                    "write the corrected plan in this same turn. Do not improvise around the plan."
                ),
                "input_schema": {"type": "object", "properties": {
                    "reason": {"type": "string", "description": "one sentence: what must change and why"},
                }, "required": ["reason"]},
            },
            {
                "name": "write_plan",
                "description": (
                    "PLANNING or REPLAN_REQUIRED. Write runs/plan.json and runs/data-inventory.json (the "
                    "schemas are in your instructions). GeoForge validates them; errors come "
                    "back and nothing is written until they pass. No downloads, no inputs, no "
                    "model runs happen in planning — the user approves the plan first. If the "
                    "two documents together are large, send them in two calls: first only "
                    "plan, then only data_inventory; GeoForge combines these two complete documents. "
                    "Each supplied document replaces its previous version. An inventory must include "
                    "its entire items array: splitting items across calls does NOT append or merge them."
                ),
                "input_schema": {"type": "object", "properties": {
                    "plan": {"type": "object"},
                    "data_inventory": {"type": "object"},
                }},
            },
            {
                "name": "fetch_data",
                "description": (
                    "EXECUTING only. Download one public http(s) file into inputs/raw/<item_id>/ "
                    "and write a signed download receipt (URL, status, sha256). Use it for every "
                    "download the approved data inventory calls for; a download made any other "
                    "way has no receipt and cannot count."
                ),
                "input_schema": {"type": "object", "properties": {
                    "url": {"type": "string"},
                    "item_id": {"type": "string", "description": "the data-inventory item id"},
                    "filename": {"type": "string"},
                    "plan_step_id": {"type": "string"},
                }, "required": ["url", "item_id"]},
            },
        ]
    # Combined installation + project turns intentionally expose both tool
    # families.  A shared operation such as request_user_action must still be
    # declared only once; the later (setup-aware) definition wins.
    out = list({tool["name"]: tool for tool in tools}.values())
    if installation_only:
        forbidden = {
            "run_preflight", "run_ki_tool", "run_calibration", "write_calibration_adapter",
            "write_project_data_tool", "run_project_data_tool",
            "create_project_plot", "publish_project_view", "fetch_data",
            "publish_setup_output",
        }
        out = [tool for tool in out if tool["name"] not in forbidden]
    if flow is not None:
        allowed = flow.api_tools()
        out = [t for t in out if t["name"] in allowed]
        for tool in out:
            if tool["name"] == "report_project_progress":
                # under the flow the stage is GeoForge's; the agent reports status/summary only
                schema = json.loads(json.dumps(tool["input_schema"]))
                schema["properties"].pop("stage", None)
                schema["required"] = [k for k in schema.get("required", []) if k != "stage"] or ["status", "summary"]
                tool["input_schema"] = schema
                tool["description"] = ("Update GeoForge's project-status display (status + summary; the stage "
                                       "is tracked by GeoForge from the plan, approval and receipts). Report "
                                       "selected_kis when you choose a model.")
    return out


class ToolError(Exception):
    pass


def _safe_relative_file_listing(base: Path, root: Path, limit: int,
                                exclude=None) -> list[str]:
    """List a large agent workspace without failing on one transient path.

    Scientific source trees contain deep generated directories, junctions and
    occasionally paths another build process removes while the agent is
    inspecting them. ``Path.rglob`` aborts the entire tool call on any such
    Windows ``FileNotFoundError``. A directory-listing aid is diagnostic only,
    so skip the unreadable entry and return the bounded evidence collected.
    """
    names: list[str] = []
    for directory, dirs, files in os.walk(
            base, topdown=True, onerror=lambda _error: None,
            followlinks=False):
        dirs.sort()
        for filename in sorted(files):
            path = Path(directory) / filename
            try:
                if exclude is not None and exclude(path):
                    continue
                names.append(path.relative_to(root).as_posix())
            except (OSError, ValueError):
                continue
            if len(names) >= limit:
                return sorted(names)
    return sorted(names)


def _read_text_page(path: Path, start_line: object = 1,
                    line_count: object = 1000) -> str:
    """Read a bounded page without forcing agents to invent shell pipelines."""
    try:
        start = int(start_line or 1)
        count = int(line_count or 1000)
    except (TypeError, ValueError) as error:
        raise ToolError("start_line and line_count must be integers") from error
    if start < 1 or count < 1 or count > 2000:
        raise ToolError("start_line must be >= 1 and line_count must be 1..2000")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    return "".join(lines[start - 1:start - 1 + count])[:60000]


def _replace_workspace_text(text: str, old: str, new: str, expected: int) -> str:
    """Match the reader's logical newlines without rewriting untouched bytes.

    Count LF and CRLF matches together: an exact CRLF match must not conceal
    a second, logically identical LF match. Each replacement uses its matched
    span's first newline, or the surrounding line's newline for inline edits.
    """
    pattern = re.compile(r"\r?\n".join(re.escape(part) for part in old.replace("\r\n", "\n").split("\n")))
    found = pattern.finditer(text)
    matches = list(itertools.islice(found, expected + 1))
    actual = len(matches) + sum(1 for _ in found)
    if actual != expected:
        raise ToolError(
            f"expected {expected} exact match(es), found {actual}; "
            "read the relevant page and retry with more context"
        )
    logical_new = new.replace("\r\n", "\n")
    pieces = []
    previous = 0
    for match in matches:
        ending = re.search(r"\r?\n", match.group()) or re.search(r"\r?\n", text[match.end():])
        if ending:
            newline = ending.group()
        else:
            last = text.rfind("\n", 0, match.start())
            newline = "\r\n" if last > 0 and text[last - 1] == "\r" else "\n" if last >= 0 else os.linesep
        pieces.extend((text[previous:match.start()], logical_new.replace("\n", newline)))
        previous = match.end()
    pieces.append(text[previous:])
    return "".join(pieces)


_INSTALL_ONLY_PROBE_FLAGS = {"--version", "-version", "-V", "-v", "--help", "-h"}
_INSTALL_ONLY_BUILD_NAMES = (
    "build", "compile", "configure", "setup", "install", "bootstrap",
    "quickbuild", "mkmf", "checkout", "external",
)
_INSTALL_ONLY_CODEGEN_NAMES = {
    "bison", "win_bison", "flex", "win_flex", "m4", "swig", "protoc",
    "cython", "f2py",
}
_INSTALL_ONLY_PYTHON_CODEGEN = {
    # RHESSys upstream build generator: committed headers -> one committed
    # build-time C translation unit. It is not a model/data execution path.
    "dynamic_field_lookup.py",
}
_INSTALL_ONLY_LICENSE_ACCEPTANCE = (
    "--accept-license", "--accept-licenses", "--accept-eula",
    "--accept-source-agreements", "--accept-package-agreements",
    "accept_eula", "accept-eula", "eula=accept", "license=accept",
)


def _is_inside(path: Path, root: Path) -> bool:
    """Return whether a resolved path is the root or one of its descendants."""
    return path == root or root in path.parents


def _guard_generated_dependency_shim(path: Path, content: str) -> None:
    """Reject generated modules or packaging that counterfeit dependencies.

    Setup agents may patch an official consumer source tree and rebuild it, but
    must not manufacture a same-named Python module or wheel merely to make an
    import probe green.  Direct site-packages writes are already rejected; this
    also closes the two-step variant where a helper first builds a fake wheel.
    """
    path_text = path.as_posix().lower()
    source = content.lower()
    path_markers = (
        "fcntl_shim", "winfcntl", "build_fcntl", "wurlitzer_shim",
        "install_wurlitzer",
    )
    source_module_markers = (
        "fcntl.py", "winfcntl", "name: fcntl", "name: winfcntl",
        "wurlitzer.py",
    )
    packaging_markers = (
        "site-packages", "dist-packages", "dist-info", ".whl",
        "wheel-version", "metadata-version", "zipfile",
    )
    fake_fcntl_api = (
        re.search(r"(?m)^\s*def\s+fcntl\s*\(", source) is not None and
        "f_getfl" in source
    )
    hand_assembled_wheel = (
        ("zipfile" in source or "tarfile" in source) and
        any(marker in source for marker in (
            ".whl", "dist-info", "wheel-version", "metadata-version",
            "record,"))
    )
    synthetic_binary_setup = (
        path.name.lower() in {"setup.py", "pyproject.toml"} and
        any(marker in source for marker in (".pyd", "*.so", "*.dll")) and
        any(marker in source for marker in (
            "package_data", "data_files", "include_package_data"))
    )
    handwritten_metadata = (
        any(part.lower().endswith(".dist-info") for part in path.parts) or
        (path.name.upper() in {"METADATA", "WHEEL", "RECORD"} and
         "dist-info" in path_text)
    )
    if (hand_assembled_wheel or synthetic_binary_setup or handwritten_metadata):
        raise ToolError(
            "installation agents may not hand-assemble wheels, package "
            "metadata, or a replacement setup project; patch and run the "
            "official source package's build backend instead"
        )
    if (any(marker in path_text for marker in path_markers) or
            fake_fcntl_api or
            (any(marker in source for marker in source_module_markers) and
             any(marker in source for marker in packaging_markers))):
        raise ToolError(
            "installation agents may not generate fcntl/wurlitzer shims or "
            "replacement wheels; patch the official consumer source and "
            "rebuild/install it"
        )


def _guard_local_dependency_shim_wheels(argv: list[str], cwd: Path,
                                        workroot: Path) -> None:
    """Inspect local wheel arguments so a generated shim cannot reach pip."""
    for token in argv[1:]:
        if not token.lower().endswith(".whl"):
            continue
        candidate = Path(token)
        wheel = (candidate.resolve() if candidate.is_absolute()
                 else (cwd / candidate).resolve())
        if (wheel != workroot and workroot not in wheel.parents) or not wheel.is_file():
            continue
        try:
            with zipfile.ZipFile(wheel) as archive:
                members = {name.lower() for name in archive.namelist()}
        except (OSError, zipfile.BadZipFile):
            continue
        if any(
                name == "fcntl.py" or name.endswith("/fcntl.py") or
                name == "wurlitzer.py" or name.endswith("/wurlitzer.py")
                for name in members):
            raise ToolError(
                "installation agents may not install a local wheel that "
                "replaces fcntl or wurlitzer; patch the official consumer "
                "source and rebuild/install it"
            )


def _guard_installation_only_command(argv: list[str], cwd: Path,
                                     workroot: Path) -> None:
    """Enforce the bounded installation command policy.

    This is a defence-in-depth policy aid around the setup allowlist, not an
    operating-system sandbox.  Reject allowlisted programs with known
    child-process escape forms rather than pretending their arguments are
    passive data.
    """
    command = Path(argv[0]).name.lower()
    # Workspace-local Windows tools arrive as absolute ``*.exe`` paths. The
    # policy names the programs, not the platform's executable suffix; without
    # normalising it, staged gcc.exe/gfortran.exe were mistaken for model
    # binaries and restricted to --version/--help.
    command_key = (Path(command).stem if Path(command).suffix.lower() in {
        ".exe", ".cmd", ".bat",
    } else command)
    args = argv[1:]
    if command in {"octave", "octave-cli"}:
        from .octpackage import guard
        try:
            guard(args, cwd, workroot)
        except (ValueError, OSError, UnicodeError) as e:
            raise ToolError(str(e)) from e
        return
    if command == "julia":
        from .jpackage import guard
        try:
            guard(args, cwd, workroot)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return
    if command in {"r", "rscript"}:
        from .rpackage import guard
        try:
            guard(command, args, cwd, workroot)
        except ValueError as e:
            raise ToolError(str(e)) from e
        return
    resolved_command = Path(argv[0]).resolve()
    in_workspace = _is_inside(resolved_command, workroot)

    joined_args = " ".join(args).lower()
    if any(token in joined_args for token in _INSTALL_ONLY_LICENSE_ACCEPTANCE):
        raise ToolError(
            "installation-only mode cannot accept a licence or EULA on the "
            "user's behalf"
        )

    if command_key == "tar" and any(arg.lower().endswith(".whl") for arg in args):
        raise ToolError(
            "installation agents may not hand-assemble wheel archives; run "
            "the official source package's build backend instead"
        )

    if command_key in {"awk", "find"}:
        raise ToolError(
            f"installation-only mode blocks {command_key}; it can launch arbitrary "
            "child processes. Use a bounded Python inspection probe instead"
        )
    if command_key == "git" and any(arg in {"-c", "--config-env"}
                                 or arg.startswith("--config-env=")
                                 for arg in args):
        raise ToolError(
            "installation-only mode blocks per-command Git configuration "
            "because aliases, pagers, filters and hooks can launch programs"
        )

    # Permit checksum verification from the freshly unpacked portable root,
    # but only for one workspace file. This lets an agent prove the archive's
    # pinned digest without exposing a general workspace executable.
    if command_key in {"sha256sum", "b2sum"}:
        command_parts = tuple(part.lower() for part in resolved_command.parts)
        expected_name = f"{command_key}.exe"
        if (not in_workspace or len(command_parts) < 3 or
                command_parts[-3:] != ("usr", "bin", expected_name)):
            raise ToolError(
                "installation-only checksum utility must be the portable "
                f"workspace MSYS2 usr/bin/{expected_name}"
            )
        if len(args) != 1 or args[0].startswith("-"):
            raise ToolError(
                "portable checksum verification requires exactly one "
                "workspace file"
            )
        candidate = Path(args[0])
        candidate = (candidate.resolve() if candidate.is_absolute()
                     else (cwd / candidate).resolve())
        if not _is_inside(candidate, workroot) or not candidate.is_file():
            raise ToolError("checksum target must be a workspace file")
        return

    # PETSc officially supports the GNU compilers supplied by MSYS2 on
    # Windows. A portable MSYS2 archive is useful for that build, but its
    # package manager must never become a route to the host installation.
    # Only the pacman located at <workspace>/<portable-root>/usr/bin is
    # accepted, and options that redirect its database/root are forbidden.
    if command_key == "pacman":
        expected_tail = ("usr", "bin", "pacman.exe")
        command_parts = tuple(part.lower() for part in resolved_command.parts)
        if (not in_workspace or len(command_parts) < len(expected_tail) or
                command_parts[-3:] != expected_tail):
            raise ToolError(
                "installation-only pacman must be the portable workspace "
                "MSYS2 usr/bin/pacman.exe"
            )
        if len(args) == 1 and args[0] in _INSTALL_ONLY_PROBE_FLAGS:
            return
        blocked_options = {
            "--root", "--sysroot", "--dbpath", "--cachedir", "--gpgdir",
            "--config", "--hookdir", "--logfile", "--nodeps",
            "--noscriptlet", "--overwrite", "--assume-installed", "-u",
            "-r",
        }
        if any(
                token.lower() in blocked_options or
                any(token.lower().startswith(option + "=")
                    for option in blocked_options if option.startswith("--"))
                for token in args):
            raise ToolError(
                "portable pacman may not redirect its root/database, remove "
                "packages, or bypass dependency/script safety"
            )
        operations = [token for token in args if token.startswith("-") and
                      token in {
                          "-Q", "-Qq", "-Qi", "-Qk", "-Ql", "-Qs", "-Qdt",
                          "-Ss", "-Si", "-Sl", "-S", "-Sy", "-Syy", "-Su",
                          "-Syu", "-Syyu",
                      }]
        if len(operations) != 1:
            raise ToolError(
                "portable pacman requires exactly one bounded query or sync "
                "operation"
            )
        operation = operations[0]
        allowed_flags = {
            operation, "--needed", "--noconfirm", "--noprogressbar",
            "--disable-download-timeout", "--downloadonly",
        }
        if any(token.startswith("-") and token not in allowed_flags
               for token in args):
            raise ToolError("portable pacman option is not allowed")
        mutating = operation in {"-S", "-Sy", "-Syy", "-Su", "-Syu", "-Syyu"}
        if mutating and "--noconfirm" not in args:
            raise ToolError(
                "portable pacman mutations require --noconfirm so setup "
                "cannot freeze on an invisible prompt"
            )
        packages = [token for token in args if not token.startswith("-")]
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.@-]*", package)
               for package in packages):
            raise ToolError(
                "portable pacman accepts repository package names only, not "
                "URLs or package files"
            )
        return

    # Permit the portable shell only as a script interpreter. Command strings
    # (bash -c/-lc), stdin scripts and script arguments stay blocked; they
    # would erase the path-token and executable policy enforced here.
    if command_key in {"bash", "sh"}:
        expected_name = f"{command_key}.exe"
        command_parts = tuple(part.lower() for part in resolved_command.parts)
        if (not in_workspace or len(command_parts) < 3 or
                command_parts[-3:] != ("usr", "bin", expected_name)):
            raise ToolError(
                "installation-only shell must be the portable workspace "
                f"MSYS2 usr/bin/{expected_name}"
            )
        shell_args = list(args)
        flags = []
        while shell_args and shell_args[0].startswith("-"):
            flags.append(shell_args.pop(0))
        if any(flag not in {"--noprofile", "--norc", "--login", "-l"}
               for flag in flags):
            raise ToolError(
                "portable shell command strings and stdin execution are "
                "blocked; invoke one explicit workspace .sh file"
            )
        if len(shell_args) != 1:
            raise ToolError(
                "portable shell requires exactly one workspace .sh file and "
                "does not accept script arguments"
            )
        script = Path(shell_args[0])
        script = (script.resolve() if script.is_absolute()
                  else (cwd / script).resolve())
        if (not _is_inside(script, workroot) or script.suffix.lower() != ".sh" or
                not script.is_file()):
            raise ToolError(
                "portable shell script must be an existing .sh file inside "
                "the setup workspace"
            )
        try:
            if script.stat().st_size > 250_000:
                raise ToolError("portable shell scripts are limited to 250 KB")
            source = script.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ToolError("portable shell script must be UTF-8 text") from error
        active_source = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ).lower()
        blocked_commands = (
            "sudo", "runas", "powershell", "pwsh", "cmd", "msiexec",
            "winget", "choco", "wsl", "docker", "reg", "sc", "schtasks",
            "setx", "curl", "wget", "pacman",
        )
        if any(re.search(
                rf"(?m)(?:^|[;&|()]\s*){re.escape(name)}(?:\.exe)?\b",
                active_source) for name in blocked_commands):
            raise ToolError(
                "portable shell script may not invoke host administration, "
                "network download, or package-manager commands"
            )
        if re.search(
                r"(?m)(?:^|[;&|($]\s*)find(?:\.exe)?\s+(?:\.|[\"']\.[\"'])"
                r"(?:\s|$)", active_source):
            raise ToolError(
                "portable shell script may not recursively scan or rewrite a "
                "whole checkout with `find .`; patch only the reported build "
                "files"
            )
        if (re.search(r"(?m)(?:^|[;&|()]\s*)(?:ba|z|k)?sh\s+-[^\n]*c\b",
                      active_source) or
                any(token in active_source
                    for token in _INSTALL_ONLY_LICENSE_ACCEPTANCE) or
                re.search(r"(?:^|[\s'\"])(?:~[/\\]|\.\.[/\\])",
                          active_source)):
            raise ToolError(
                "portable shell script contains a command-string, licence "
                "acceptance, or host/parent path escape"
            )
        # MSYS2 spells a Windows path such as D:\work as /d/work. Translate
        # those explicit drive mounts back before enforcing the same workspace
        # boundary; /mingw64 and /usr are private to the portable MSYS2 root.
        for match in re.finditer(
                r"(?i)(?<![A-Za-z0-9_])/(?:mnt/)?([A-Z])/([^\s'\"]+)",
                source):
            candidate = Path(
                f"{match.group(1)}:/{match.group(2)}").resolve()
            if not _is_inside(candidate, workroot):
                raise ToolError(
                    "portable shell script contains an MSYS drive path "
                    "outside the setup workspace"
                )
        for match in re.finditer(r"(?i)(?<![A-Za-z0-9])([A-Z]:[/\\][^\s'\"]+)",
                                 source):
            candidate = Path(match.group(1)).resolve()
            if not _is_inside(candidate, workroot):
                raise ToolError(
                    "portable shell script contains a Windows path outside "
                    "the setup workspace"
                )
        return

    # Build systems may compile, but their explicit test/run targets would
    # cross from installation into scientific execution.
    if command_key in {
            "make", "gmake", "mingw32-make", "ninja", "meson", "cmake",
            "cargo", "go"}:
        blocked_targets = {"test", "tests", "check", "run", "submit", "example", "examples"}
        if any(arg.lower().lstrip("-") in blocked_targets for arg in args):
            raise ToolError(
                "installation-only mode blocks build-system test/run targets; "
                "compile the software without executing its examples"
            )
        return

    # micromamba is a single-file, workspace-stageable package manager. Keep
    # both its cache/root and environment prefix inside this KI workspace, and
    # do not expose its generic model-execution facility in install-only mode.
    if command_key == "micromamba":
        operations = {arg.lower() for arg in args if not arg.startswith("-")}
        if len(args) == 1 and args[0] in _INSTALL_ONLY_PROBE_FLAGS:
            return
        if "run" in operations or not operations.intersection({
                "create", "install", "update", "list", "info", "search"}):
            raise ToolError(
                "installation-only micromamba may create/install/inspect an "
                "environment but may not run model commands"
            )

        def option_paths(names: set[str]) -> list[Path]:
            found: list[Path] = []
            for index, token in enumerate(args):
                value = ""
                if token in names and index + 1 < len(args):
                    value = args[index + 1]
                elif any(token.startswith(name + "=") for name in names):
                    value = token.split("=", 1)[1]
                if value:
                    candidate = Path(value)
                    found.append(
                        candidate.resolve() if candidate.is_absolute()
                        else (cwd / candidate).resolve())
            return found

        prefixes = option_paths({"-p", "--prefix"})
        roots = option_paths({"-r", "--root-prefix"})
        if operations.intersection({"create", "install", "update"}) and (
                not prefixes or not roots):
            raise ToolError(
                "micromamba create/install/update requires both a workspace "
                "--root-prefix and --prefix"
            )
        for candidate in [*prefixes, *roots]:
            if candidate != workroot and workroot not in candidate.parents:
                raise ToolError("micromamba prefix escapes the setup workspace")
        return

    # Package managers, compilers, source-control and read-only inspection
    # tools are installation operations rather than model invocations.
    if command_key in {
        "git", "pkg-config", "pip", "pip3", "uv", "rustc", "gcc", "g++",
        "clang", "clang++", "gfortran", "tar", "unzip", "curl", "wget",
        "7z", "7za", "7zr", "innoextract", "patch", "sed", "ls", "cp",
        "mv", "ln", "chmod", "ar", "ranlib", "dlltool", "gendef", "nm",
        "objdump", "strip",
        "file", "otool", "xcode-select", "brew",
    }:
        return

    # Source builds legitimately execute generators before compiling. They
    # are neither scientific runs nor example payloads; blocking a staged
    # flex/bison binary made an otherwise complete RHESSys build ask the user
    # for permission that the installation workflow had already granted.
    if command_key in _INSTALL_ONLY_CODEGEN_NAMES:
        return

    # Python is also used for small workspace inspection scripts and package
    # installation.  Do not let a generated script hide a model invocation.
    if command_key.startswith("python"):
        if len(args) == 1 and args[0] in _INSTALL_ONLY_PROBE_FLAGS:
            return
        if len(args) >= 2 and args[0] == "-m" and args[1] in {
                "pip", "ensurepip", "venv", "py_compile", "compileall"}:
            return
        if not args or args[0].startswith("-"):
            raise ToolError(
                "installation-only Python commands must install/compile a package "
                "or run a small workspace inspection script"
            )
        script = Path(args[0])
        script = script.resolve() if script.is_absolute() else (cwd / script).resolve()
        name = script.name.lower()
        try:
            source_text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ToolError(f"cannot inspect installation Python script: {e}") from e
        _guard_generated_dependency_shim(script, source_text)
        if name in _INSTALL_ONLY_PYTHON_CODEGEN:
            return
        if any(word in name for word in _INSTALL_ONLY_BUILD_NAMES):
            return
        if script.parent != workroot or not any(
                word in name for word in ("probe", "inspect", "check", "verify")):
            raise ToolError(
                "installation-only mode blocked this Python model/data command; "
                "only build helpers or root-level inspection probes may run"
            )
        source = source_text.lower()
        if any(token in source for token in (
                "subprocess", "os.system", "os.popen", "popen(", "runpy", "exec(", "eval(")):
            raise ToolError(
                "installation-only inspection probes cannot launch another process; "
                "invoke a permitted build command or use a --help/--version probe directly"
            )
        return

    if in_workspace:
        if any(word in command_key for word in _INSTALL_ONLY_BUILD_NAMES):
            return
        if len(args) == 1 and args[0] in _INSTALL_ONLY_PROBE_FLAGS:
            return
        raise ToolError(
            "installation-only mode blocked a model/example invocation. "
            "A built executable may only be probed with exactly one of "
            "--version, -v, --help, or -h"
        )


def _user_only_file(path: Path, project_root: Path) -> bool:
    """Request cards (current and archived) carry Baidu links and extraction codes for the
    user's eyes only; agents never read them."""
    return ((path.name.startswith("setup-request") and path.suffix == ".json") or
            (path.name == "manual-download-details.json" and path.parent.name == ".geoforge"))


_KI_INSPECTION_TOOLS = frozenset({
    "read_ki_file", "list_ki_files", "search_diagnostics", "list_skills", "read_skill",
    "list_project_files", "read_project_file", "list_work_files", "read_work_file",
})


def execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                 setup_context: dict | None = None,
                 project_mode: bool = False, flow=None) -> str:
    from . import ki_guard
    from contextlib import ExitStack
    roots = [Path(ki.root).absolute()]
    for value in (setup_context or {}).get("managed_ki_roots", []):
        roots.append(Path(value).absolute())
    for selected in getattr(getattr(flow, "ctx", None), "selected_kis", []) or []:
        _, selected_root = flow.ki_root_for(selected, Path(ki.root))
        roots.append(Path(selected_root).absolute())
    roots = list(dict.fromkeys(roots))
    with ExitStack() as workers:
        for root in roots:
            workers.enter_context(ki_guard.worker(root))
        if name in {"write_work_file", "replace_work_text", "write_project_file"}:
            base = Path((setup_context or {}).get("project_root") or cfg.root) if name == "write_project_file" else Path(cfg.root)
            for root in roots:
                try:
                    ki_guard.reject_write(root, base / str(args.get("path") or ""))
                except ki_guard.KIIntegrityError as exc:
                    raise ToolError(str(exc)) from None
        return _guarded_execute_tool(name, args, ki, cfg, setup_mode=setup_mode,
                                     setup_context=setup_context, project_mode=project_mode,
                                     flow=flow, managed_roots=roots)


def _guarded_execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                         setup_context: dict | None = None,
                         project_mode: bool = False, flow=None, managed_roots=None) -> str:
    """One host integrity boundary, shared by every API provider."""
    from . import ki_guard
    if name in _KI_INSPECTION_TOOLS:
        # Draft/blocked KIs must remain inspectable for repair. The underlying
        # tool still enforces flow state, path containment and private files.
        return _execute_tool(name, args, ki, cfg, setup_mode=setup_mode,
                             setup_context=setup_context, project_mode=project_mode, flow=flow)
    roots = managed_roots or [Path(ki.root).absolute()]
    try:
        for root in roots:
            ki_guard.require_intact(root, required=(root / "SKILL.md").is_file())
    except ki_guard.KIIntegrityError as exc:
        raise ToolError(str(exc)) from None
    try:
        return _execute_tool(name, args, ki, cfg, setup_mode=setup_mode,
                             setup_context=setup_context, project_mode=project_mode, flow=flow)
    except ki_guard.KIIntegrityError as exc:
        raise ToolError(str(exc)) from None
    finally:
        failures = []
        for root in roots:
            try:
                # A tool may have spawned untracked children: copy only.
                draft = ki_guard.preserve_drift(root)
                if draft is not None:
                    failures.append(f"KI edit was not accepted. Active KI is blocked; changed bytes retained at {draft}. "
                                    "Original baseline preserved; stop workers before recovery and verify "
                                    "the candidate through KDT before explicit adoption.")
            except ki_guard.KIIntegrityError as exc:
                failures.append(str(exc))
        if failures:
            raise ToolError("\n".join(failures))


def _execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                 setup_context: dict | None = None,
                 project_mode: bool = False, flow=None) -> str:
    """Run one tool. Every path argument is confined to the KI package.

    ``flow`` (flowgate.FlowSession, plan v3 B4): when present, every call is re-checked
    against the project's flow state before it runs (the schema filter is not trusted on
    its own), writes obey ``flow.write_allowed``, model/tool runs and downloads write
    signed receipts, and agent progress reports cannot move the stage."""
    if setup_mode and flow is not None:
        # Project setup has the same command limits as standalone installation.
        # The host runs preflight and starts a separate, receipted execution turn.
        setup_context = {**(setup_context or {}), "installation_only": True}
    if flow is not None:
        from .flowgate import FlowDenied
        try:
            flow.check_tool(name)
        except FlowDenied as e:
            raise ToolError(str(e)) from None
    root = Path(ki.root).resolve()
    workroot = Path(cfg.root).resolve()
    provider_id = str((setup_context or {}).get("provider_id") or "")
    # During a direct-API installation turn the model setup workspace and the
    # chat project are deliberately separate.  Keep both roots explicit so an
    # agent can finish installation and then run/publish into the chat project
    # without weakening the setup command sandbox.
    project_root = Path(
        (setup_context or {}).get("project_root") or workroot
    ).resolve()
    turn_handle = (setup_context or {}).get("_handle")
    stop = turn_handle.stopped.is_set if turn_handle is not None else None
    turn_id = (setup_context or {}).get("_turn_id")
    from . import execution
    if ((stop is not None and stop()) or
            execution.stop_requested(project_root, turn_id=turn_id)):
        raise ToolError("Stopped by the user; no further tool work may start in this turn.")
    progress_root = project_root
    if (bool((setup_context or {}).get("installation_only")) and name in {
            "run_preflight", "run_ki_tool", "run_calibration", "write_calibration_adapter",
            "write_project_data_tool", "run_project_data_tool",
            "create_project_plot", "publish_project_view", "fetch_data",
            "publish_setup_output"}):
        raise ToolError(
            f"{name} is unavailable during installation-only setup; use "
            "only a cheap executable startup or declared import probe"
        )

    # A chat owns its scenario files, but the scientific software is installed
    # once in the current KI's managed workspace.  That binary role is a narrow
    # capability granted by GeoForge's config; it is not an arbitrary external
    # filesystem permission.  KI tools may read/execute it directly without
    # making the user copy large model installs into every chat project.
    project_argument_roots = [project_root, workroot, root]
    binary_role = (getattr(cfg, "roles", {}) or {}).get("binaries")
    if binary_role:
        binary_root = Path(binary_role).expanduser().resolve()
        if binary_root not in project_argument_roots:
            project_argument_roots.append(binary_root)

    def _inside(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute paths are not accepted: {rel}")
        # Resolve then verify containment: a bare prefix check is defeated by
        # '..' and by symlinks, and this is the only place model-supplied paths
        # reach the filesystem.
        p = (root / rel).resolve()
        if p != root and root not in p.parents:
            raise ToolError(f"path escapes the KI package: {rel}")
        return p

    def _inside_work(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute workspace paths are not accepted: {rel}")
        p = (workroot / rel).resolve()
        if p != workroot and workroot not in p.parents:
            raise ToolError(f"path escapes the setup workspace: {rel}")
        return p

    def _inside_project(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute project paths are not accepted: {rel}")
        p = (project_root / rel).resolve()
        if p != project_root and project_root not in p.parents:
            raise ToolError(f"path escapes the chat project: {rel}")
        return p

    def _ki_scoped(rel: str) -> tuple[Path, Path]:
        """(path, ki_root) for read/list tools — another SELECTED KI may be named (kimi desktop
        review #1: multi-KI chats must reach every selected KI through the typed tools)."""
        ki_root = root
        if flow is not None and args.get("ki"):
            from .flowgate import FlowDenied
            try:
                _n, ki_root = flow.ki_root_for(args.get("ki"), root)
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            ki_root = Path(ki_root).resolve()
        if Path(rel).is_absolute():
            raise ToolError(f"absolute paths are not accepted: {rel}")
        p = (ki_root / rel).resolve()
        if p != ki_root and ki_root not in p.parents:
            raise ToolError(f"path escapes the KI package: {rel}")
        return p, ki_root

    if name == "read_ki_file":
        p, _r = _ki_scoped(args.get("path", ""))
        if not p.is_file():
            raise ToolError(f"no such file in this KI: {args.get('path')}")
        return _read_text_page(
            p, args.get("start_line", 1), args.get("line_count", 1000))

    if name == "list_ki_files":
        base, ki_root = _ki_scoped(args.get("subdir") or ".")
        names = _safe_relative_file_listing(base, ki_root, 400)
        return "\n".join(names) or "(empty)"

    if name == "run_preflight":
        if bool((setup_context or {}).get("installation_only")):
            raise ToolError("Full preflight is outside installation-only scope; use the declared import and executable startup checks.")
        from . import install as _install
        step = _install.run_preflight(ki, cfg.python, cfg, project=project_root,
                                      stop=stop, turn_id=turn_id)
        return f"{'PASS' if step.ok else 'FAIL'}\n{step.detail}"

    if name == "search_diagnostics":
        kw = (args.get("keyword") or "").lower()
        if not kw:
            raise ToolError("keyword required")
        hits: list[str] = []
        for f in root.rglob("*"):
            if not f.is_file() or "diagnostic" not in str(f.relative_to(root)):
                continue
            if root not in f.resolve().parents:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if kw in line.lower():
                    hits.append(
                        f"{f.relative_to(root).as_posix()}:{i}: {line.strip()[:200]}")
        return "\n".join(hits[:40]) or f"no diagnostics mention {kw!r}"

    if name in ("list_skills", "read_skill"):
        if name == "list_skills":
            q = (args.get("query") or "").lower()
            found = [item for item in skilllib.discover()
                     if not q or q in item["name"].lower()
                     or q in item["description"].lower()]
            return ("\n".join(f"{item['name']} — {item['description']}"
                              for item in found[:200]) or "no skills installed")
        try:
            return skilllib.read(args.get("name", ""))[:60000]
        except FileNotFoundError:
            raise ToolError(f"no skill named {args.get('name')!r}")

    if project_mode and name == "list_project_files":
        base = _inside_project(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such project directory: {args.get('subdir')}")
        names = []
        for f in sorted(base.rglob("*")):
            if not f.is_file() or "memory" in f.relative_to(project_root).parts or _user_only_file(f, project_root):
                continue
            try:
                names.append(
                    f"{f.relative_to(project_root).as_posix()} "
                    f"({f.stat().st_size} bytes)")
            except OSError:
                continue
        return "\n".join(names[:1000]) or "(no project files yet)"

    if project_mode and name == "read_project_file":
        p = _inside_project(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such project file: {args.get('path')}")
        if _user_only_file(p, project_root):
            raise ToolError("that file is a request card for the user (it may hold a private download "
                            "link or code); its answer reaches you through the conversation")
        preview_limit = 120000
        with p.open("r", encoding="utf-8", errors="replace") as stream:
            preview = stream.read(preview_limit + 1)
        if "\x00" in preview or preview.startswith("SQLite format 3"):
            raise ToolError("this is a binary project file, not a text preview; "
                            "use a format-aware KI reader, or author a reviewed project-local reader with "
                            "write_project_data_tool during planning/replan if no suitable reader exists")
        if len(preview) > preview_limit:
            return preview[:preview_limit] + (
                "\n\n[TRUNCATED PREVIEW: first 120000 characters only. This does not "
                "establish full-file coverage or record counts; use a format-aware KI "
                "reader for complete dataset analysis.]"
            )
        return preview

    if project_mode and name == "write_project_file":
        p = _inside_project(args.get("path") or "")
        from . import ki_guard
        ki_guard.reject_write(root, p)
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ToolError("write_project_file is limited to 1 MB; use a KI tool")
        rel = p.relative_to(project_root)
        writable = {"inputs", "runs", "outputs", "artifacts", "references"}
        calibration_write = (len(rel.parts) >= 2 and rel.parts[0] == "calibration"
                             and rel.parts[1] in {"cases", "kis"})
        if not rel.parts or (rel.parts[0] not in writable and not calibration_write):
            raise ToolError(
                "project writes must stay under inputs, runs, outputs, artifacts, "
                "references, calibration/cases, or calibration/kis")
        if flow is not None and not flow.write_allowed(p):
            # plan v3 B4: approval.json, flow-state.json, .geoforge/, the plan files outside
            # PLANNING, and anything under runs/ except logs/notes are never agent-writable
            raise ToolError(f"writing {rel.as_posix()} is not allowed in state "
                            f"{flow.state.value} (protected or outside the writable subtrees)")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        # Tool results are consumed by agents on every host. Keep project paths
        # in the API's portable slash form instead of leaking Windows `\\`
        # separators that are frequently copied into later JSON/tool calls.
        return f"wrote {rel.as_posix()} ({len(content.encode('utf-8'))} bytes)"

    if project_mode and name == "write_project_data_tool":
        from . import project_data_tools
        from .flowgate import FlowDenied
        if flow is None or flow.state.value not in {"PLANNING", "REPLAN_REQUIRED"}:
            raise ToolError("Project data source authoring is available only during planning or replan")
        if set(args) != {"ki", "name", "source", "purpose"}:
            raise ToolError("Provide only ki, name, source and purpose")
        if not isinstance(args["ki"], str) or not args["ki"]:
            raise ToolError("ki must explicitly name a selected model")
        try:
            selected_name, _ = flow.ki_root_for(args["ki"], root)
            return json.dumps(project_data_tools.write(project_root, selected_name, args["name"],
                                                       args["source"], args["purpose"]), ensure_ascii=False)
        except (FlowDenied, OSError, ValueError, TypeError, SyntaxError) as exc:
            raise ToolError(str(exc)) from None

    if project_mode and name in {"run_ki_tool", "run_project_data_tool"}:
        project_data = name == "run_project_data_tool"
        if project_data and flow is None:
            raise ToolError("Project data tools require a current approved Flow plan")
        if project_data and (set(args) - {"ki", "tool_path", "plan_step_id", "arguments", "cwd", "timeout_seconds"}
                             or any(not isinstance(args.get(k), str) or not args[k]
                                    for k in ("ki", "tool_path", "plan_step_id"))):
            raise ToolError("Provide selected ki, tool_path, plan_step_id and only the reviewed invocation fields")
        tool_ki_name, tool_root = getattr(ki, "name", root.name), root
        requested_tool_root = Path(ki.root)
        if flow is not None:
            from .flowgate import FlowDenied
            try:
                tool_ki_name, tool_root = flow.ki_root_for(args.get("ki"), root)
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            requested_tool_root = Path(tool_root)
            tool_root = requested_tool_root.resolve()
            if tool_root != root and tool_root not in project_argument_roots:
                project_argument_roots.append(tool_root)
        def _inside_tool_ki(rel: str, _root=tool_root) -> Path:
            # same containment rule as _inside, against the KI this call names (multi-KI runs)
            if Path(rel).is_absolute():
                hint = ""
                try:
                    candidate = Path(rel).resolve()
                    relative = candidate.relative_to(_root)
                    if candidate.suffix.casefold() == ".py" and is_ki_tool(_root, candidate):
                        hint = (f". For this shipped Python tool use tool_path={relative.as_posix()!r} "
                                "relative to the KI root (including tools/ when present). "
                                "Keep the approved plan and arguments unchanged.")
                except (OSError, ValueError, RuntimeError):
                    pass
                raise ToolError(f"absolute paths are not accepted: {rel}{hint}")
            p = (_root / rel).resolve()
            if p != _root and _root not in p.parents:
                raise ToolError(f"path escapes the KI package: {rel}")
            return p
        from ki_tools_common.flow.tools import is_declared_binary, is_ki_tool
        requested = str(args.get("tool_path") or "")
        binary = not project_data and is_declared_binary(tool_root, requested)
        if project_data:
            from . import project_data_tools
            from ki_tools_common.flow import project_tools
            try:
                script = project_tools.source_path(project_root, tool_ki_name, requested)
                _, approved_args, approved_cwd, approved_timeout = project_data_tools.invocation(
                    flow, tool_ki_name, script, args.get("plan_step_id"), args)
                args = {**args, "arguments": approved_args,
                        "cwd": approved_cwd.relative_to(project_root).as_posix(), "timeout_seconds": approved_timeout}
            except (FlowDenied, OSError, ValueError, TypeError) as exc:
                raise ToolError(str(exc)) from None
        elif binary:
            script = Path(requested).resolve()
            rel_script = script.name
        else:
            script = _inside_tool_ki(requested)
            try:
                rel_script = script.relative_to(tool_root)
            except ValueError:
                raise ToolError("tool escapes the selected KI")
            if script.suffix.casefold() != ".py" or not is_ki_tool(tool_root, script):
                raise ToolError("run_ki_tool accepts only shipped Python files below tools/ "
                                "or the model binary the KI declares")
        if flow is not None:
            try:
                flow.check_step_tool(args.get("plan_step_id"), tool_ki_name, script)
            except FlowDenied as exc:
                raise ToolError(str(exc)) from None
        from . import project_paths
        try:
            selected = getattr(getattr(flow, "ctx", None), "selected_kis", []) or []
            tool_cfg = project_paths.execution_config(
                project_root, tool_ki_name, requested_tool_root,
                fallback=cfg if len(selected) <= 1 else None)
        except (OSError, ValueError) as exc:
            raise ToolError(f"cannot resolve runtime for {tool_ki_name}: {exc}") from None
        # Only the requested KI's software capability applies to this call,
        # not the first model's installation that opened the conversation.
        project_argument_roots = [project_root, tool_root]
        binary_role = (getattr(tool_cfg, "roles", {}) or {}).get("binaries")
        if binary_role:
            project_argument_roots.append(Path(binary_role).expanduser().resolve())
        arguments = args.get("arguments") or []
        if (not isinstance(arguments, list) or len(arguments) > 100 or
                not all(isinstance(x, str) and len(x) <= 4000 for x in arguments)):
            raise ToolError("arguments must be a list of short strings")
        cwd = _inside_project(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"project directory does not exist: {args.get('cwd')}")
        for token in arguments:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if not (value.startswith(("/", "./", "../")) or
                    "/" in value or "\\" in value):
                continue
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            if not any(
                    resolved == base or base in resolved.parents
                    for base in project_argument_roots):
                raise ToolError(f"tool argument path escapes the project and KI: {value}")
        timeout = max(1, min(int(args.get("timeout_seconds") or 600), 3600))
        from .execution import execute_ki_tool
        from .flowgate import FlowDenied
        try:
            result = execute_ki_tool(
                flow=flow, cfg=tool_cfg, project=project_root, ki=tool_ki_name, ki_root=requested_tool_root,
                tool=script, arguments=arguments, cwd=cwd, plan_step_id=args.get("plan_step_id"),
                python_tool=not binary, timeout=timeout, provider_id=provider_id,
                stop=stop, turn_id=turn_id, project_data_tool=project_data)
        except FlowDenied as e:
            raise ToolError(str(e)) from None
        headline = (f"exit_code={result.exit_code}" if result.exit_code is not None
                    else result.detail)
        if result.receipt_error and result.status != "timed_out":
            raise ToolError(f"{headline}\n[receipt NOT written: {result.receipt_error}]\n{result.output}")
        receipt = (f"[RECEIPT] {json.dumps(result.receipt, ensure_ascii=False)}\n"
                   if result.receipt else "")
        error = f"\n[receipt not written: {result.receipt_error}]" if result.receipt_error else ""
        detail = f"\n{result.detail}" if result.exit_code is not None and result.detail else ""
        return f"{headline}\n{receipt}{result.output}{detail}{error}"

    if project_mode and name == "write_calibration_adapter":
        from . import calibration as _calibration
        from .flowgate import FlowDenied
        if flow is None or flow.state.value not in {"PLANNING", "REPLAN_REQUIRED"}:
            raise ToolError("Calibration adapter preparation is available only during project planning")
        if set(args) != {"ki", "contract", "runner_source"} or not isinstance(args.get("ki"), str) or not args["ki"]:
            raise ToolError("Provide only the selected ki, contract and runner_source")
        try:
            selected_name, _ = flow.ki_root_for(args["ki"], root)
            return json.dumps(_calibration.write_adapter(project_root, selected_name,
                args["contract"], args["runner_source"]), ensure_ascii=False)
        except (FlowDenied, OSError, RuntimeError, TypeError, ValueError, SyntaxError) as exc:
            raise ToolError(str(exc)) from None

    if project_mode and name == "run_calibration":
        from . import calibration as _calibration
        calib_before = None
        calib_started = time.time()
        # Materialize missing adapter copies before resolving the bytes the
        # reviewer authorized. Existing project-owned adapters are preserved.
        _calibration.ensure_project(project_root, [ki])
        try:
            binding, adapter_snapshot = _calibration.prepare_invocation(project_root, ki.name, args)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from None
        expected_approval = None
        approved_step = None
        if flow is not None:
            from . import flowgate as _fg
            from .flowgate import FlowDenied
            try:
                approved_step = flow.check_calibration_step(
                    args.get("plan_step_id"), ki.name, adapter_snapshot.runner_path, binding)
                expected_approval = flow.approval_id
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            calib_before = _fg._snapshot(project_root, subs=("inputs", "outputs", "artifacts", "runs/logs", "calibration/runs"))
        try:
            result = _calibration.run_project(
                project=project_root,
                ki_name=ki.name,
                ki_path=root,
                obs_shape_by_var=binding["obs_shape_by_var"],
                algorithm=binding["algorithm"], budget=binding["budget"], seed=binding["seed"],
                determining_metric=binding["determining_metric"],
                expected_case_id=binding["expected_case_id"],
                stop=stop, turn_id=turn_id, adapter_snapshot=adapter_snapshot,
                approved_binding=binding if flow is not None else None,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from None
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        summary = {
            "run_id": result.get("run_id"),
            "status": report.get("status"),
            "promotable": report.get("promotable"),
            "backend": report.get("backend"),
            "best_loss": report.get("best_loss"),
            "best_params": report.get("best_params"),
            "reason": report.get("reason"),
            "report_path": result.get("report_path"),
            "log_path": result.get("log_path"),
            "log_tail": result.get("log_tail"),
        }
        if flow is not None:
            from .flowgate import FlowDenied
            try:
                _kname = getattr(ki, "name", root.name)
                input_paths = [str(adapter_snapshot.contract_path), str(adapter_snapshot.runner_path)]
                for item in (flow.inventory or {}).get("items") or []:
                    if item.get("id") in (approved_step or {}).get("inputs", []):
                        input_paths.extend(str(p) for p in item.get("local_paths") or [])
                summary["receipt"] = flow.record_tool_run(
                    ki=_kname, ki_root=root,
                    command=["geoforge-calibration", _kname, binding["algorithm"],
                             "--budget", str(binding["budget"]), "--seed", str(binding["seed"]),
                             "--adapter", str(adapter_snapshot.runner_path)],
                    cwd=project_root, started_at=calib_started, finished_at=time.time(),
                    exit_code=0 if str(report.get("status") or "").lower() in ("ok", "success", "completed", "done") else 1,
                    before=calib_before, plan_step_id=args.get("plan_step_id"),
                    expected_approval_sha256=expected_approval,
                    input_arguments=input_paths,
                    calibration_result=result,
                    stdout_tail=str(result.get("log_tail") or ""),
                    execution_status=("stopped" if report.get("status") in {"stopped", "interrupted"} else None))
            except FlowDenied as e:
                raise ToolError(str(e)) from None
        return json.dumps(summary, indent=2, ensure_ascii=False, default=str)

    if project_mode and name == "request_replan":
        if flow is None:
            raise ToolError("request_replan is available only in a flow-managed project")
        from .flowgate import FlowDenied
        try:
            return flow.request_replan(str(args.get("reason") or ""))
        except FlowDenied as e:
            raise ToolError(str(e)) from None

    if project_mode and name == "write_plan":
        if flow is None:
            raise ToolError("write_plan is available only in a flow-managed project")
        if args.get("_vendor_argument_error"):
            raise ToolError(
                f"write_plan arguments were not delivered intact: {args['_vendor_argument_error']}. "
                "Call write_plan twice: once with only plan, once with only data_inventory; "
                "GeoForge merges the two before validating.")
        plan_doc, inv_doc = args.get("plan"), args.get("data_inventory")
        for key, value in (("plan", plan_doc), ("data_inventory", inv_doc)):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ToolError(f"{key} is not valid JSON: {e}") from None
            if value is not None and not isinstance(value, dict):
                raise ToolError(f"{key} must be a JSON object")
            if key == "plan":
                plan_doc = value
            else:
                inv_doc = value
        # Two-call submission: keep the half that arrived until the other one comes.
        parts = getattr(flow, "pending_plan_parts", None) or {}
        if plan_doc is not None:
            parts["plan"] = plan_doc
        if inv_doc is not None:
            parts["data_inventory"] = inv_doc
        flow.pending_plan_parts = parts
        if "plan" not in parts or "data_inventory" not in parts:
            have = "plan" if "plan" in parts else "data_inventory"
            missing = "data_inventory" if have == "plan" else "plan"
            return (f"Received {have}; now call write_plan again with only {missing}. "
                    "Nothing is validated or written until both halves are in.")
        plan_doc, inv_doc = parts["plan"], parts["data_inventory"]
        flow.pending_plan_parts = {}
        errs = flow.write_plan(plan_doc, inv_doc)
        if errs:
            return "PLAN NOT WRITTEN — fix these and call write_plan again:\n- " + "\n- ".join(errs[:30])
        return ("Plan files written: runs/plan.json, runs/data-inventory.json. Stop here: GeoForge "
                "shows the plan to the user; execution starts in a separate session after approval.")

    if project_mode and name == "estimate_preparation":
        from . import obs_access, obs_prepare
        if flow is None:
            raise ToolError("Preparation estimates require a project session")
        if getattr(flow, "state", None) is not None and flow.state.value == "RESOLVING_KIS":
            used = getattr(flow, "intake_estimates", 0)
            if used >= INTAKE_ESTIMATE_CAP:
                raise ToolError(f"at most {INTAKE_ESTIMATE_CAP} data estimates during task "
                                "understanding; finish the intake before estimating more")
            flow.intake_estimates = used + 1
        try:
            return json.dumps(obs_prepare.record_estimate(flow.project, args), ensure_ascii=False)
        except (obs_access.ObsAccessError, TypeError, ValueError, OSError) as error:
            raise ToolError(str(error)) from None

    if project_mode and name in ("search_catalogue", "describe_dataset", "estimate_clip"):
        # Thin adapters over the legacy multi-mode handler (removed in step 2).
        if name == "describe_dataset":
            args = {"describe_dataset_id": str(args.get("dataset_id") or "")}
        elif name == "estimate_clip":
            if flow is not None and getattr(flow, "state", None) is not None \
                    and flow.state.value == "RESOLVING_KIS":
                used = getattr(flow, "intake_estimates", 0)
                if used >= INTAKE_ESTIMATE_CAP:
                    raise ToolError(f"at most {INTAKE_ESTIMATE_CAP} clip estimates during task "
                                    "understanding; finish the intake, estimate the rest in planning")
                flow.intake_estimates = used + 1
            args = {"subset_request": {k: v for k, v in args.items()
                                       if k in ("dataset_id", "bbox", "variables", "start", "end")}}
        else:
            args = dict(args)
            if args.get("parent_id"):
                args["resolve_dataset_id"] = args.pop("parent_id")
        name = "search_observation_data"

    if project_mode and name == "search_observation_data":
        from . import obs_access
        try:
            if sum((bool(args.get('describe_dataset_id')), bool(args.get('resolve_dataset_id')),
                    args.get('subset_request') is not None)) > 1:
                raise ValueError('Choose one of describe, resolve or subset estimate per call')
            if args.get('subset_request') is not None:
                from . import obs_subset
                if flow is None:
                    raise ValueError('Subset estimates require a project session')
                return json.dumps(obs_subset.estimate(flow.project, args['subset_request']), ensure_ascii=False)
            result = obs_access.search_catalogue(
                q=str(args.get("query") or ""),
                offset=int(args.get("offset") or 0),
                limit=int(args.get("limit") or 25),
                bbox=args.get("bbox") or None, start=args.get("start") or None,
                end=args.get("end") or None, variable=str(args.get("variable") or ""),
                category=str(args.get("category") or ""),
                describe_dataset_id=str(args.get("describe_dataset_id") or ""),
                resolve_dataset_id=str(args.get("resolve_dataset_id") or ""),
                time_step=str(args.get("time_step") or ""),
                delivery=str(args.get("delivery") or ""))
        except (obs_access.ObsAccessError, TypeError, ValueError) as error:
            raise ToolError(str(error)) from None
        return json.dumps(result, indent=2, ensure_ascii=False)

    if project_mode and name == "fetch_data":
        if flow is None:
            raise ToolError("fetch_data is available only in a flow-managed project")
        from .flowgate import FlowDenied
        try:
            info = flow.fetch(str(args.get("url") or ""), str(args.get("item_id") or ""),
                              filename=args.get("filename"), plan_step_id=args.get("plan_step_id"))
        except FlowDenied as e:
            raise ToolError(str(e)) from None
        except (OSError, ValueError) as e:
            raise ToolError(f"download failed: {e}") from None
        return "[RECEIPT] " + json.dumps(info, ensure_ascii=False)

    if project_mode and name == "create_project_plot":
        from .plotting import PlotError, render_svg
        p = _inside_project(args.get("output_path") or "")
        rel = p.relative_to(project_root)
        if not rel.parts or rel.parts[0] != "artifacts" or p.suffix.lower() != ".svg":
            raise ToolError("plot output_path must be a .svg file below artifacts/")
        plot_args = dict(args)
        if args.get("source_path"):
            source = _inside_project(args.get("source_path") or "")
            if not source.is_file() or source.suffix.lower() != ".csv":
                raise ToolError("plot source_path must be a project CSV file")
            if source.stat().st_size > 20_000_000:
                raise ToolError("plot CSV is larger than 20 MB")
            x_column = str(args.get("x_column") or "")
            requested = args.get("series") or []
            if not x_column or not requested or not all(
                    isinstance(item, dict) and item.get("y_column")
                    for item in requested):
                raise ToolError("CSV plots require x_column and y_column for every series")
            with source.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                raise ToolError("plot CSV has no data rows")
            columns = set(rows[0])
            y_columns = [str(item["y_column"]) for item in requested]
            missing = [column for column in [x_column, *y_columns]
                       if column not in columns]
            if missing:
                raise ToolError(f"plot CSV is missing columns: {', '.join(missing)}")
            # Keep the request and SVG bounded while preserving both endpoints.
            max_rows = max(2, 5000 // len(requested))
            if len(rows) > max_rows:
                indices = sorted({round(i * (len(rows) - 1) / (max_rows - 1))
                                  for i in range(max_rows)})
                rows = [rows[i] for i in indices]
            built_series = []
            for item, y_column in zip(requested, y_columns):
                built_series.append({
                    "name": item.get("name") or y_column,
                    "axis": item.get("axis") or "left",
                    "x": [row[x_column] for row in rows],
                    "y": [row[y_column] for row in rows],
                })
            plot_args["series"] = built_series
        try:
            summary = render_svg(plot_args, p)
        except (OSError, PlotError) as e:
            raise ToolError(str(e)) from None
        return (f"{summary}\nInclude it in the reply as: "
                f"![{args.get('title') or p.stem}]({rel.as_posix()})")

    if project_mode and name == "publish_project_view":
        from . import projectview as _projectview
        try:
            state = _projectview.publish(project_root, args, source="direct_api")
        except (OSError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from None
        return ("Project View published. GeoForge will render it for this chat.\n" +
                json.dumps({
                    "title": state["title"],
                    "panels": len(state["panels"]),
                    "path": "artifacts/project-view.json",
                }, indent=2, ensure_ascii=False))

    if project_mode and not setup_mode and name == "request_user_action":
        from . import projectrun as _projectrun, setup as _setup
        if (flow is not None
                and flow.state.value in {"RESOLVING_KIS", "PLANNING", "REPLAN_REQUIRED"}):
            from .flowrun import request_planning_question
            try:
                doc = request_planning_question(project_root, args)
            except (OSError, ValueError) as exc:
                raise ToolError(str(exc)) from None
        else:
            doc = _setup.request_user(project_root, args)
        _projectrun.report(progress_root, {
            "status": "waiting_for_user", "summary": doc["title"],
            "blocker": doc,
        }, source="api_handoff")
        return "GeoForge will show this one request to the user:\n" + json.dumps(doc, indent=2)

    if (project_mode or setup_mode) and name == "report_project_progress":
        from . import projectrun as _projectrun
        payload = dict(args or {})
        if flow is not None and "stage" in payload:
            payload.pop("stage")        # plan v3 B5: the flow owns the stage; agents report status/summary
        state = _projectrun.report(progress_root, payload, source="api")
        note = "" if flow is None else "\n(the stage is tracked by GeoForge from the plan/approval/receipts; only status and summary were taken from your report)"
        return "Project status updated:\n" + json.dumps(state, indent=2) + note

    if setup_mode and name == "run_builtin_setup":
        callback = (setup_context or {}).get("run_builtin")
        if not callable(callback):
            raise ToolError("the built-in setup runner is unavailable")
        from . import install as _install
        try:
            with _install.cancellation_context(project_root, stop=stop, turn_id=turn_id):
                return str(callback())[-60000:]
        except _install.InstallStopped as exc:
            return str(exc)

    if setup_mode and name == "list_work_files":
        base = _inside_work(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such workspace directory: {args.get('subdir')}")
        names = _safe_relative_file_listing(
            base, workroot, 800,
            exclude=lambda f: _user_only_file(f, project_root))
        return "\n".join(names) or "(empty)"

    if setup_mode and name == "read_work_file":
        p = _inside_work(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such workspace file: {args.get('path')}")
        if _user_only_file(p, project_root):
            raise ToolError("that file contains private user-only request details")
        return _read_text_page(
            p, args.get("start_line", 1), args.get("line_count", 1000))

    if setup_mode and name == "write_work_file":
        p = _inside_work(args.get("path") or "")
        from . import ki_guard
        ki_guard.reject_write(root, p)
        relative_parts = {part.lower() for part in p.relative_to(workroot).parts}
        if (bool((setup_context or {}).get("installation_only")) and
                p.parent == workroot and p.name in {
                    "status.json", "installation-test.json",
                    ".geoforge-install.json",
                }):
            raise ToolError(
                f"{p.name} is GeoForge-owned verification state and cannot "
                "be written by the installation agent"
            )
        if (bool((setup_context or {}).get("installation_only")) and
                relative_parts.intersection({"site-packages", "dist-packages"})):
            raise ToolError(
                "installation agents may not write directly into site-packages; "
                "patch the official workspace source and rebuild/install it"
            )
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if bool((setup_context or {}).get("installation_only")):
            _guard_generated_dependency_shim(p, content)
        if len(content.encode("utf-8")) > 250_000:
            raise ToolError("write_work_file is limited to 250 KB")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return (
            f"wrote {p.relative_to(workroot).as_posix()} "
            f"({len(content.encode('utf-8'))} bytes)"
        )

    if setup_mode and name == "replace_work_text":
        p = _inside_work(args.get("path") or "")
        from . import ki_guard
        ki_guard.reject_write(root, p)
        if not p.is_file():
            raise ToolError(f"no such workspace file: {args.get('path')}")
        relative_parts = {part.lower() for part in p.relative_to(workroot).parts}
        if (bool((setup_context or {}).get("installation_only")) and
                p.parent == workroot and p.name in {
                    "status.json", "installation-test.json",
                    ".geoforge-install.json",
                }):
            raise ToolError(
                f"{p.name} is GeoForge-owned verification state and cannot "
                "be written by the installation agent"
            )
        if (bool((setup_context or {}).get("installation_only")) and
                relative_parts.intersection({"site-packages", "dist-packages"})):
            raise ToolError(
                "installation agents may not patch site-packages in place; "
                "patch the official workspace source and rebuild/install it"
            )
        old, new = args.get("old"), args.get("new")
        if (not isinstance(old, str) or not old or
                not isinstance(new, str)):
            raise ToolError("old must be non-empty text and new must be text")
        try:
            expected = int(args.get("expected_count", 1))
        except (TypeError, ValueError) as error:
            raise ToolError("expected_count must be an integer") from error
        if expected < 1 or expected > 20:
            raise ToolError("expected_count must be 1..20")
        if len(old.encode("utf-8")) > 100_000 or len(new.encode("utf-8")) > 100_000:
            raise ToolError("replacement text is limited to 100 KB")
        raw = p.read_bytes()
        if len(raw) > 5_000_000:
            raise ToolError("replace_work_text is limited to files under 5 MB")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ToolError("replace_work_text requires a UTF-8 text file") from error
        updated = _replace_workspace_text(text, old, new, expected)
        p.write_text(updated, encoding="utf-8", newline="")
        return (
            f"replaced {expected} exact match(es) in "
            f"{p.relative_to(workroot).as_posix()}"
        )

    if setup_mode and name == "run_setup_command":
        argv = args.get("argv")
        if (not isinstance(argv, list) or not argv or len(argv) > 100 or
                not all(isinstance(x, str) and x and len(x) <= 4000 for x in argv)):
            raise ToolError("argv must be a non-empty list of short strings")
        executable = argv[0]
        allowed = {
            "git", "cmake", "make", "gmake", "mingw32-make", "ninja",
            "meson", "pkg-config", "micromamba",
            "python", "python3", "pip", "pip3", "uv", "cargo", "rustc", "go",
            "gcc", "g++", "clang", "clang++", "gfortran", "tar", "unzip",
            "7z", "7za", "7zr", "innoextract", "curl", "wget", "patch",
            "sed", "awk", "find", "ls", "cp", "mv", "ln", "ar", "ranlib",
            "dlltool", "gendef", "nm", "objdump", "strip",
            "chmod", "file", "otool", "xcode-select", "brew", "bison", "flex",
            "win_bison", "win_flex", "m4", "swig", "protoc", "cython", "f2py",
            "gcc", "g++", "cc", "c++", "clang", "clang++", "gfortran", "tar", "unzip", "mkdir",
            "curl", "wget", "patch", "sed", "awk", "find", "ls", "cp", "mv", "ln",
            "chmod", "file", "otool", "xcode-select", "brew", "which",
            "cat", "grep", "head", "tail", "uname", "sw_vers",
            "autoreconf", "autoconf", "automake", "aclocal", "libtoolize", "glibtoolize",
            "ar", "ranlib", "nm", "nf-config", "nc-config", "gdal-config",
            "mpicc", "mpicxx", "mpif90", "mpifort", "flex", "bison", "R", "Rscript", "julia", "octave", "octave-cli",
        }
        exe_path = Path(executable)
        executable_name = exe_path.name.lower()
        executable_key = (
            Path(executable_name).stem
            if Path(executable_name).suffix.lower() in {".exe", ".cmd", ".bat"}
            else executable_name
        )
        external_roots = []
        for raw in (setup_context or {}).get("existing_roots") or []:
            try:
                candidate = Path(str(raw)).expanduser().resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            external_roots.append(candidate.parent if candidate.is_file() else candidate)
        # ``Path.is_absolute`` alone does not distinguish a Windows relative
        # executable (``binaries\\tools\\python.exe``) from a bare command.
        # Treat both native separators as paths before consulting the command
        # allowlist; otherwise a real workspace-local toolchain is rejected as
        # an unknown command exactly when the setup agent tries to use it.
        if exe_path.is_absolute() or "/" in executable or "\\" in executable:
            resolved = (workroot / exe_path).resolve() if not exe_path.is_absolute() else exe_path.resolve()
            cfg_python = Path(cfg.python).resolve()
            permitted_roots = [workroot, root,
                               Path(cfg.roles.get("binaries", workroot)).resolve(),
                               *external_roots]
            if resolved != cfg_python and not any(
                    resolved == base or base in resolved.parents for base in permitted_roots):
                # A workspace venv may use a different installed Python than cfg.python.
                # Validate its actual prefix, without dereferencing the launcher we execute.
                launcher = (workroot / exe_path) if not exe_path.is_absolute() else exe_path
                launcher = launcher.parent.resolve() / launcher.name
                workspace_venv = False
                if (workroot in launcher.parents and
                        re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", launcher.name)):
                    probe_env = {key: value for key, value in os.environ.items()
                                 if not any(secret in key.upper() for secret in
                                            ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
                    try:
                        probe = subprocess.run(
                            [str(launcher), "-c", "import sys; print(sys.prefix)"],
                            capture_output=True, text=True, timeout=10, env=probe_env)
                        prefix = Path(probe.stdout.strip()).resolve()
                        workspace_venv = (probe.returncode == 0 and
                                          (prefix == workroot or workroot in prefix.parents))
                    except (OSError, subprocess.TimeoutExpired, ValueError):
                        pass
                if not workspace_venv:
                    hint = (f" Use the allowlisted tool name {exe_path.name!r} without an absolute path."
                            if exe_path.name in allowed else "")
                    raise ToolError(f"executable is outside the setup workspace: {executable}.{hint}")
            if (os.name == "nt" and resolved.suffix.lower() == ".exe" and
                    resolved.is_file()):
                try:
                    with resolved.open("rb") as executable_file:
                        pe_header = executable_file.read(2)
                except OSError as error:
                    raise ToolError(
                        f"cannot inspect Windows executable: {error}") from error
                if pe_header != b"MZ":
                    raise ToolError(
                        f"{resolved.name} is not a Windows PE executable (missing "
                        "MZ header); if the download endpoint returned an archive, "
                        "extract the real executable before running it"
                    )
            # Validate the resolved target, but execute the original venv path.
            # Dereferencing venv/bin/python here launches the base interpreter
            # without pyvenv.cfg and can send pip installs outside the workspace.
            argv[0] = str((workroot / exe_path).absolute()
                          if not exe_path.is_absolute() else exe_path)
        elif executable_key not in {item.lower() for item in allowed}:
            raise ToolError(f"command is not in the setup allowlist: {executable}")
        if executable_key == "brew" and len(argv) > 1 and argv[1] not in (
                "--prefix", "--version", "list", "info", "config"):
            raise ToolError("Homebrew changes require the user; create a permission request")

        cwd = _inside_work(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"command directory does not exist: {args.get('cwd')}")
        if (bool((setup_context or {}).get("installation_only"))
                or Path(argv[0]).name.lower() in {"r", "rscript", "julia", "octave", "octave-cli"}):
            _guard_installation_only_command(argv, cwd, workroot)
            _guard_local_dependency_shim_wheels(argv, cwd, workroot)
        # Reject path arguments that escape the workspace. This is not a
        # shell, but programs such as cp, curl and git still accept output
        # paths of their own. Compiler/system include flags are allowed only
        # for the conventional read-only roots they genuinely need.
        readable_system_roots = tuple(Path(p) for p in (
            "/usr", "/opt/homebrew", "/Library/Frameworks",
        ))

        def check_path_token(token: str) -> None:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if value.startswith(("http://", "https://", "git@")):
                return
            if not (value.startswith(("/", "./", "../")) or
                    "/" in value or "\\" in value):
                return
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            allowed_workspace = any(
                resolved == base or base in resolved.parents
                for base in (workroot, root,
                             Path(cfg.roles.get("binaries", workroot)).resolve(),
                             *external_roots)
            )
            allowed_system = any(
                resolved == base or base in resolved.parents for base in readable_system_roots)
            if not allowed_workspace and not allowed_system:
                raise ToolError(f"command path escapes the setup workspace: {value}")

        for token in argv[1:]:
            check_path_token(token)
        if Path(argv[0]).name in ("python", "python3") or Path(argv[0]).resolve() == Path(cfg.python).resolve():
            if "-c" in argv:
                raise ToolError("inline Python is unavailable; write a workspace script and run it")
        timeout = max(1, min(int(args.get("timeout_seconds") or 300), 3600))
        # Some scientific executables ignore conventional --help/--version
        # flags and immediately enter their normal blocking input loop.  A
        # startup probe is only a load/response check, so never let one make
        # the Setup UI appear frozen for the normal five-minute command limit.
        if (bool((setup_context or {}).get("installation_only")) and
                len(argv) == 2 and argv[1] in _INSTALL_ONLY_PROBE_FLAGS):
            timeout = min(timeout, 20)
        extra_env = args.get("env") or {}
        if not isinstance(extra_env, dict):
            raise ToolError("env must be an object")
        safe_env = {}
        path_prefix: list[str] = []
        banned = {"HOME", "SHELL", "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "PIP_REQUIRE_VIRTUALENV"}
        workspace_path_env = {
            "CONDA_PKGS_DIRS", "CONDA_ENVS_DIRS", "MAMBA_ROOT_PREFIX",
            "CONDA_PREFIX", "CONDARC", "MAMBARC", "MSYS2_ROOT",
            "PETSC_DIR", "TMP", "TEMP", "TMPDIR",
        }
        for key, value in extra_env.items():
            if (not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", str(key)) or
                    key in banned or not isinstance(value, str) or len(value) > 8000):
                raise ToolError(f"unsafe environment override: {key}")
            if key == "PATH":
                for entry in value.split(os.pathsep):
                    if not entry:
                        continue
                    candidate = Path(entry)
                    resolved = (candidate.resolve() if candidate.is_absolute()
                                else (cwd / candidate).resolve())
                    if not any(
                            resolved == base or base in resolved.parents
                            for base in (workroot, root,
                                         Path(cfg.roles.get(
                                             "binaries", workroot)).resolve(),
                                         *external_roots)):
                        raise ToolError(
                            f"PATH entry escapes the setup workspace: {entry}")
                    path_prefix.append(str(resolved))
                continue
            if key in workspace_path_env:
                for entry in value.split(os.pathsep):
                    if not entry:
                        continue
                    candidate = Path(entry)
                    resolved = (candidate.resolve() if candidate.is_absolute()
                                else (cwd / candidate).resolve())
                    if resolved != workroot and workroot not in resolved.parents:
                        raise ToolError(
                            f"environment path escapes the setup workspace: "
                            f"{key}={entry}")
            safe_env[key] = value
        if Path(argv[0]).name.lower() == "julia" and len(argv) > 2:
            from . import jpackage
            jpackage.guard(argv[1:], cwd, workroot)
            safe_env.update(jpackage.startup_env(jpackage.scoped(argv[8], cwd, workroot)))
        # A tool or build script must never inherit the API key that is driving
        # the agent. Keep the normal build environment, remove credentials.
        child_env = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        from .paths import with_ki_tools_common
        child_env = with_ki_tools_common(cfg, child_env)
        if provider_id:
            from .settings import with_provider_proxy
            child_env = with_provider_proxy(provider_id, child_env)
        command_path = Path(argv[0]).resolve()
        if (os.name == "nt" and command_path.name.lower() == "pacman.exe"
                and workroot in command_path.parents
                and tuple(part.lower() for part in command_path.parts[-3:])
                    == ("usr", "bin", "pacman.exe")):
            # Portable pacman's post-install hooks need its own sh/coreutils.
            # A GUI-launched parent need not have any MSYS2 tools on PATH.
            path_prefix.insert(0, str(command_path.parent))
        if path_prefix:
            safe_env["PATH"] = os.pathsep.join(
                [*path_prefix, child_env.get("PATH", "")])
        pip_guard = "true"
        # Conda prefixes are isolated too, although pip does not call them venvs.
        # Permit that interpreter's pip only after checking its actual prefix.
        if len(argv) > 2 and argv[1:3] == ["-m", "pip"]:
            try:
                prefix_probe = subprocess.run(
                    [argv[0], "-c", "import sys; print(sys.prefix)"],
                    cwd=str(cwd), env=child_env, capture_output=True,
                    text=True, timeout=10)
                prefix = Path(prefix_probe.stdout.strip()).resolve()
                if prefix_probe.returncode == 0 and (prefix == workroot or workroot in prefix.parents):
                    pip_guard = "false"
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass
        from contextlib import nullcontext
        isolate_probe = (bool((setup_context or {}).get("installation_only"))
                         and Path(argv[0]).is_absolute() and len(argv) == 2
                         and argv[1] in _INSTALL_ONLY_PROBE_FLAGS)
        if isolate_probe:
            timeout = min(timeout, 25)
        from . import execution
        from .install import scratch_directory
        proc = None
        try:
            directory = (scratch_directory("startup-probe-", str(workroot))
                         if isolate_probe else nullcontext(str(cwd)))
            with directory as execution_cwd:
                # Its own session, tree-killed on timeout, ended by the chat's Stop.
                # (On Windows, run_process also closes stdin for every launch.)
                proc = execution.run_process(
                    argv, cwd=execution_cwd, env={**child_env, **safe_env, "PIP_REQUIRE_VIRTUALENV": pip_guard,
                                                "PYTHONDONTWRITEBYTECODE": "1"},
                    timeout=timeout, project=project_root,
                    stop=stop, turn_id=turn_id,
                    stdin=subprocess.DEVNULL if isolate_probe else None,
                )
        except OSError as e:
            # Only a failure before the launch is FAILED_TO_START; a probe that
            # ran keeps its collected result whatever its directory cleanup did.
            if proc is None:
                proc = execution.ProcessRun("not_launched", None, error=e)
        tail = (proc.stdout + proc.stderr)[-12000:]
        if proc.status == "not_launched":
            # A non-executable script, missing command, or platform launch
            # error is normal repair-loop evidence.  Let the model see it and
            # choose another invocation (usually ``python3 script.py``)
            # instead of aborting the entire API turn.
            return f"FAILED_TO_START: {type(proc.error).__name__}: {proc.error}"
        if proc.status == "timed_out":
            return f"TIMEOUT after {timeout}s\n{tail}"
        if proc.status == "stopped":
            return ("STOPPED by the user before the command started" if proc.process_started is False
                    else f"STOPPED by the user; the command and everything it started were signalled.\n{tail}")
        output = proc.stdout[-25000:] + "\n" + proc.stderr[-25000:]
        if isolate_probe:
            output = "Startup probe used an empty workspace directory (no bundled case inputs).\n" + output
        return f"exit_code={proc.returncode}\n{output}"

    if setup_mode and project_mode and name == "publish_setup_output":
        source = _inside_work(args.get("source") or "")
        destination = _inside_project(args.get("destination") or "")
        if not source.exists():
            raise ToolError(f"no such generated setup output: {args.get('source')}")
        source_rel = source.relative_to(workroot)
        destination_rel = destination.relative_to(project_root)
        if not source_rel.parts or source_rel.parts[0] not in {"outputs", "runs", "data"}:
            raise ToolError("published setup files must come from outputs, runs, or data")
        writable = {"inputs", "runs", "outputs", "artifacts", "references"}
        if not destination_rel.parts or destination_rel.parts[0] not in writable:
            raise ToolError("published files must stay in a project data folder")

        candidates = [source] if source.is_file() else list(source.rglob("*"))
        # A scientific run directory commonly links its executable and shared
        # model tables back into the same setup workspace.  Those links are
        # safe to publish as normal files when their targets remain inside the
        # workspace.  Keeping the links themselves would make the chat project
        # non-portable, while rejecting them prevented an otherwise successful
        # run from being archived at all.
        files: list[tuple[Path, Path]] = []
        link_count = 0
        for item in candidates:
            if item.is_symlink():
                try:
                    resolved = item.resolve(strict=True)
                except OSError as e:
                    raise ToolError(f"generated output contains a broken symbolic link: {item.name}") from e
                if resolved != workroot and workroot not in resolved.parents:
                    raise ToolError(
                        f"generated output link escapes the setup workspace: {item.name}")
                if not resolved.is_file():
                    raise ToolError(
                        f"generated output contains a symbolic directory: {item.name}")
                files.append((item, resolved))
                link_count += 1
            elif item.is_file():
                files.append((item, item))
        if len(files) > 2000:
            raise ToolError("generated output contains more than 2,000 files")
        total = sum(copy_source.stat().st_size for _, copy_source in files)
        if total > 512 * 1024 * 1024:
            raise ToolError("generated output is larger than the 512 MB publish limit")
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(files[0][1], destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            for item, copy_source in files:
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy_source, target)
        link_note = (f", {link_count} internal links copied as files"
                     if link_count else "")
        return (
            f"published {source_rel.as_posix()} to {destination_rel.as_posix()} "
            f"({len(files)} files, {total} bytes{link_note})"
        )

    if setup_mode and name == "request_user_action":
        from . import projectrun as _projectrun, setup as _setup
        doc = _setup.request_user(workroot, args)
        _projectrun.report(progress_root, {
            "stage": "software", "status": "waiting_for_user",
            "summary": doc["title"], "blocker": doc,
        }, source="api_handoff")
        return "GeoForge is now waiting for the user:\n" + json.dumps(doc, indent=2)

    raise ToolError(f"unknown tool {name}")


# --- wire formats -----------------------------------------------------------

def _open(url: str, headers: dict, payload: dict, *, provider: str):
    """Open the provider request with the connection-level retries only."""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    from .settings import proxy_url_for
    proxy = proxy_url_for(provider)
    # Only retry the provider response, before any returned tool is executed.
    # A transient disconnect must not discard a whole installation repair loop.
    for attempt in range(3):
        try:
            handlers = [
                urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy} if proxy else {}),
                urllib.request.HTTPSHandler(context=tls.context()),
            ]
            return urllib.request.build_opener(*handlers).open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:800]
            if e.code not in {429, 502, 503, 504} or attempt == 2:
                raise ToolError(f"HTTP {e.code} from {url}: {body}") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise ToolError(
                    f"no response from {url} within {TIMEOUT}s; the model was still generating "
                    "(not retried: a retry restarts the generation)") from None
            if isinstance(e.reason, ssl.SSLCertVerificationError) or attempt == 2:
                raise ToolError(f"cannot reach {url}: {e.reason}") from None
        except (http.client.RemoteDisconnected, http.client.IncompleteRead,
                ConnectionError) as e:
            if attempt == 2:
                raise ToolError(f"provider connection interrupted: {type(e).__name__}") from None
        time.sleep(2 ** attempt)
    raise ToolError(f"cannot reach {url}")  # unreachable; keeps the type checker honest


def _post(url: str, headers: dict, payload: dict, *, provider: str,
          wire: str | None = None, handle: TurnHandle | None = None) -> dict:
    """POST to a provider and return the complete response document.

    With ``wire`` set the request streams and the chunks are reassembled into
    the same document shape the non-streaming API returns.  Streaming keeps
    the socket busy during a long generation (the read timeout then bounds
    silence between chunks, not the whole answer) and gives ``handle`` a
    response it can close to stop the turn.
    """
    if wire is None:
        try:
            with _open(url, headers, payload, provider=provider) as r:
                return json.loads(r.read())
        except TimeoutError:
            raise ToolError(
                f"no response from {url} within {TIMEOUT}s; the model was still generating "
                "(not retried: a retry restarts the generation)") from None
    response = _open(url, headers, {**payload, "stream": True}, provider=provider)
    if handle is not None:
        handle.attach(response)
    try:
        events = _sse_events(response, handle)
        return (_assemble_anthropic(events) if wire == "anthropic"
                else _assemble_openai(events))
    except AttributeError:
        # Stop closes HTTPResponse from another thread. urllib/http.client can
        # then dereference its cleared stream (for example None.peek) while
        # iterating. Only normalize this when Stop was actually requested.
        if handle is not None and handle.stopped.is_set():
            raise ToolError("stopped by the user") from None
        raise
    except (TimeoutError, http.client.IncompleteRead, ConnectionError,
            ValueError, OSError) as e:
        if handle is not None and handle.stopped.is_set():
            raise ToolError("stopped by the user") from None
        raise ToolError(f"provider stream interrupted: {type(e).__name__}: {e}") from None
    finally:
        if handle is not None:
            handle.detach()
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass


def _sse_events(response, handle: TurnHandle | None) -> Iterator[dict]:
    """Yield the JSON ``data:`` payloads of a server-sent-event stream."""
    started = time.time()
    for raw in response:
        if time.time() - started > STREAM_MAX_SECONDS:
            raise ToolError(
                f"provider response exceeded {STREAM_MAX_SECONDS}s without completing; "
                "the generation was stopped")
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue          # comments / keep-alives are not progress
        if handle is not None:
            handle.last_chunk_at = time.time()
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if obj.get("error"):
                err = obj["error"]
                raise ToolError(f"provider error: {err.get('message', err) if isinstance(err, dict) else err}")
            yield obj


def _assemble_openai(events: Iterator[dict]) -> dict:
    """Rebuild ``{"choices":[{"message": …}]}`` from OpenAI-style deltas."""
    text: list[str] = []
    calls: dict[int, dict] = {}
    finish = None
    for obj in events:
        choice = (obj.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            text.append(str(delta["content"]))
        for tc in delta.get("tool_calls") or []:
            slot = calls.setdefault(int(tc.get("index") or 0), {
                "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
        finish = choice.get("finish_reason") or finish
    # reasoning_content (DeepSeek) is deliberately dropped: the vendor rejects
    # it when echoed back in the next request.
    message: dict = {"role": "assistant", "content": "".join(text)}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"choices": [{"message": message, "finish_reason": finish}]}


def _assemble_anthropic(events: Iterator[dict]) -> dict:
    """Rebuild ``{"content": [...]}`` from Anthropic content-block events."""
    blocks: dict[int, dict] = {}
    partial: dict[int, list[str]] = {}
    for obj in events:
        kind = obj.get("type")
        if kind == "content_block_start":
            index = int(obj.get("index") or 0)
            block = dict(obj.get("content_block") or {})
            if block.get("type") == "text":
                block["text"] = block.get("text") or ""
            blocks[index] = block
            partial[index] = []
        elif kind == "content_block_delta":
            index = int(obj.get("index") or 0)
            delta = obj.get("delta") or {}
            block = blocks.setdefault(index, {"type": "text", "text": ""})
            if delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + str(delta.get("text") or "")
            elif delta.get("type") == "input_json_delta":
                partial.setdefault(index, []).append(str(delta.get("partial_json") or ""))
        elif kind == "error":
            err = obj.get("error") or {}
            raise ToolError(f"provider error: {err.get('message', err)}")
    for index, block in blocks.items():
        if block.get("type") == "tool_use":
            raw = "".join(partial.get(index) or [])
            try:
                block["input"] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                block["input"] = {"_vendor_argument_error": "invalid JSON arguments",
                                  "_raw_arguments": raw[:2000]}
    return {"content": [blocks[i] for i in sorted(blocks)]}


def _cacheable_system(system: str) -> list[dict]:
    """The instruction block as one cacheable prefix.

    Tools and system render ahead of messages, so a single breakpoint here
    covers both. It matters more than one call per turn suggests: the agent
    loop below runs up to ``max_steps`` times for a single user message, and
    without this the same ~20KB KI catalogue was re-sent, and re-billed at full
    price, on every one of them.
    """
    return [{"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}}]


def _cached_messages(messages: list[dict]) -> list[dict]:
    """Messages with a rolling cache breakpoint on the newest turn.

    Each loop step resends the entire conversation. Marking the tail lets the
    next step read everything up to here from cache rather than paying for it
    again. Copied rather than mutated — ``messages`` is reused across steps and
    a breakpoint left behind on an old turn would pin the cache to stale text.
    """
    if not messages:
        return messages
    content = messages[-1].get("content")
    if isinstance(content, str):
        blocks: list = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = [dict(b) if isinstance(b, dict) else b for b in content]
    else:
        return messages
    if not isinstance(blocks[-1], dict):
        return messages
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return [*messages[:-1], {**messages[-1], "content": blocks}]


def _anthropic_turn(prov, model, system, messages, tools, key, handle=None):
    data = _post(prov.base_url,
                 {"x-api-key": key, "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": MAX_OUTPUT_TOKENS,
                  "system": _cacheable_system(system),
                  "messages": _cached_messages(messages), "tools": tools},
                 provider=f"api:{getattr(prov, 'name', 'anthropic')}",
                 wire="anthropic", handle=handle)
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    calls = [(b["id"], b["name"], b.get("input") or {})
             for b in data.get("content", []) if b.get("type") == "tool_use"]
    return text, calls, data.get("content", [])


def _openai_turn(prov, model, system, messages, tools, key, handle=None):
    oai_tools = [{"type": "function",
                  "function": {"name": t["name"], "description": t["description"],
                               "parameters": t["input_schema"]}} for t in tools]
    msgs = [{"role": "system", "content": system}, *messages]
    data = _post(prov.base_url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": msgs, "tools": oai_tools,
                  "max_tokens": MAX_OUTPUT_TOKENS},
                 provider=f"api:{getattr(prov, 'name', 'openai')}",
                 wire="openai", handle=handle)
    choice = (data.get("choices") or [{}])[0].get("message", {})
    text = choice.get("content") or ""
    calls = []
    for c in (choice.get("tool_calls") or []):
        # Preserve a valid call id/name even when the vendor truncates only
        # the JSON arguments.  Feeding a normal tool error back under that id
        # lets the model retry on the next step instead of dropping the whole
        # turn.  Missing structural fields still fail closed below.
        try:
            call_id = c["id"]
            function = c["function"]
            name = function["name"]
            raw_args = function.get("arguments") or "{}"
        except (KeyError, TypeError) as e:
            raise ToolError(f"vendor returned a malformed tool call: {e}") from None
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError as e:
            cut = (choice.get("finish_reason") == "length" or
                   (data.get("choices") or [{}])[0].get("finish_reason") == "length")
            args = {
                "_vendor_argument_error": (
                    f"the provider cut this tool call off at its output limit "
                    f"({len(str(raw_args))} characters received); send less in one call"
                    if cut else f"invalid JSON arguments: {e}"),
                "_raw_arguments": str(raw_args)[:2000],
            }
        calls.append((call_id, name, args))
    return text, calls, choice


_TEXT_TOOL_REQUEST = re.compile(
    r"\[\[GEOF_TOOL:[A-Za-z0-9_.-]+\]\]|"
    r"<invoke\s+name=[\"'][A-Za-z0-9_.-]+[\"'][^>]*>[\s\S]*?<parameter\b",
    re.I,
)


def _looks_like_text_tool_request(text: str) -> bool:
    """Detect providers printing tool syntax instead of making a tool call.

    Some OpenAI-compatible endpoints occasionally return an XML-like tool
    request in ``content`` with an empty structured ``tool_calls`` array. It
    must not be shown as if work happened: no tool was actually run.
    """
    return bool(_TEXT_TOOL_REQUEST.search(str(text or "")))


# States in which a turn must end with a handoff (a question card, an intake report or a
# plan), never with prose alone (FLOW-TARGET-2026-09-17 step 1).
_HANDOFF_STATES = {"RESOLVING_KIS", "PLANNING", "REPLAN_REQUIRED"}
_NUDGE = {
    "RESOLVING_KIS": (
        "Your turn ended without a handoff, so GeoForge cannot move on: a question written in "
        "prose shows the user no card and the project waits forever. Either call "
        "request_user_action now with that ONE question and its options, or call "
        "report_project_progress with selected_kis and an intake object with "
        "ready_for_planning=true and an empty missing list."),
    "PLANNING": (
        "Your turn ended without a planning handoff. If a decision is unresolved, call "
        "request_user_action with ONE question, its KI-supported default if known, and "
        "alternatives; then wait. Keep earlier answers. Only after all required decisions "
        "are settled, call write_plan with both final files for user review. Do not rush "
        "past unanswered questions or start downloading during planning."),
}
_NUDGE["REPLAN_REQUIRED"] = _NUDGE["PLANNING"]
_TRANSPORT_FAILURE = ("provider stream interrupted", "no response from", "cannot reach")


def _handoff_made(name: str, args: dict, out: str) -> bool:
    """Did this tool call end the agent's obligation for a handoff state?"""
    if out.startswith(("ERROR:", "DENIED", "PLAN NOT WRITTEN")):
        return False
    if name == "write_plan":
        return out.startswith("Plan files written")
    if name == "request_user_action":
        return True
    if name == "report_project_progress":
        intake = args.get("intake")
        # "Not ready, one question missing" is a handoff only when that question
        # was asked through request_user_action; a question in prose leaves the
        # project waiting with no card, which is the seam this rule closes.
        return (bool(args.get("selected_kis")) and isinstance(intake, dict)
                and intake.get("ready_for_planning") is True and not intake.get("missing"))
    return False


def run(prov: ApiProvider, ki, cfg, system: str, task: str,
        *, model: str | None = None, max_steps: int | None = None,
        history: list[dict] | None = None,
        approve: Callable[[str, dict], bool] | None = None,
        setup_mode: bool = False,
        setup_context: dict | None = None,
        project_mode: bool = False,
        presentation: str = "chat",
        flow=None, handle: TurnHandle | None = None) -> Iterator[str]:
    """Drive one task to completion, yielding text as it is produced.

    ``approve`` is the seam the CLI driver cannot offer: it is called before
    each tool runs and may refuse. Returning False denies that one call and
    tells the model why, rather than aborting the turn.
    """
    if flow is not None:
        flow.provider_succeeded = False
    key = prov.key()
    if not key:
        yield f"[{prov.label}: set {prov.env_key} — get one at {prov.signup}]"
        return

    want = model or prov.default_model
    if prov.models and want not in prov.models and want not in prov.models.values():
        yield (f"[{prov.label} does not offer {want!r}; choose from "
               f"{list(prov.models)}]")
        return
    model_id = prov.models.get(want, want)
    tool_context = dict(setup_context or {})
    if setup_mode and flow is not None:
        tool_context["installation_only"] = True
    tool_context.setdefault("provider_id", f"api:{prov.name}")
    tool_context["_handle"] = handle
    if "_turn_id" not in tool_context:
        from . import execution
        project = tool_context.get("project_root") or getattr(cfg, "root", None)
        if project is not None:
            tool_context["_turn_id"] = execution.current_turn_id(Path(project))
    tools = tool_schemas(
        ki, setup_mode=setup_mode, project_mode=project_mode, flow=flow,
        installation_only=bool(tool_context.get("installation_only")),
    )
    # Prior turns travel as REAL messages, not flattened into one user blob
    # with USER:/YOU: markers — the vendor's own multi-turn handling is the
    # thing that makes context work, and counterfeit markers cannot exist in a
    # role field.
    messages: list[dict] = []
    for m in history or []:
        role = "assistant" if m.get("role") == "assistant" else "user"
        body = str(m.get("text", ""))[:8000]
        if body:
            messages.append({"role": role, "content": body})
    messages.append({"role": "user", "content": task})
    text_tool_retries = 0
    transport_retries = 0
    nudged = False
    handoff = False
    step = 0

    # A scientific setup or model run is complete when the provider returns a
    # final response, asks the user for an external action, or reports a real
    # error.  Its length is not knowable in advance: compiling one model may
    # take five calls and another may legitimately take fifty.  A fixed turn
    # budget previously stopped DeepSeek halfway through a healthy Alpine3D
    # build.  ``None`` is therefore the normal contract.  ``max_steps`` remains
    # available only for small, explicitly bounded probes and unit tests.
    while max_steps is None or step < max_steps:
        if flow is not None and step:
            # A request_replan in the previous step changes what is allowed now.
            tools = tool_schemas(
                ki, setup_mode=setup_mode, project_mode=project_mode, flow=flow,
                installation_only=bool(tool_context.get("installation_only")))
        step += 1
        if handle is not None and handle.stopped.is_set():
            yield f"\n[{prov.label} stopped by the user]"
            return
        try:
            if prov.wire == "anthropic":
                text, calls, raw = _anthropic_turn(prov, model_id, system, messages, tools, key,
                                                   handle=handle)
            else:
                text, calls, raw = _openai_turn(prov, model_id, system, messages, tools, key,
                                                handle=handle)
        except ToolError as e:
            if handle is not None and handle.stopped.is_set():
                yield f"\n[{prov.label} stopped by the user]"
                return
            if str(e).startswith(_TRANSPORT_FAILURE) and not transport_retries:
                # One retry: the failed call appended nothing, so the same request is
                # simply sent again. A second failure is reported as before.
                transport_retries += 1
                yield f"\n[{prov.label}: connection dropped; retrying once]\n"
                continue
            yield f"\n[{prov.label} failed: {e}]"
            return

        if not calls and _looks_like_text_tool_request(text):
            # Do not leak provider-specific pseudo XML into chat, and do not
            # pretend it ran. Give the model one clean chance to use the typed
            # tools that were already sent with the request.
            if text_tool_retries:
                yield (f"\n[{prov.label} returned a tool request as plain text. "
                       "Nothing in that request was run. Retry this message or "
                       "switch the AI connection.]\n")
                return
            text_tool_retries += 1
            if prov.wire == "anthropic":
                messages.append({"role": "assistant", "content": raw})
            else:
                messages.append(raw)
            messages.append({
                "role": "user",
                "content": ("Your previous response printed internal tool-call "
                            "markup as ordinary text, so no action ran. Use the "
                            "provided structured function tools now. Do not print "
                            "XML, <invoke>, or GEOF_TOOL markers."),
            })
            continue

        # A response which also invokes tools is normally scratch narration
        # ("Let me inspect...", "Now I will..."). Keep it in the provider's
        # internal history, but reserve the visible answer for the final
        # no-tool response. Forensic setup pages can still request log mode.
        if text and (not calls or presentation == "log"):
            yield text
        if not calls:
            state_name = getattr(getattr(flow, "state", None), "value", "")
            if flow is not None and state_name in _HANDOFF_STATES and not handoff and not nudged:
                # Prose is not a handoff. One nudge, then the turn ends and flowrun.after
                # reports the missing submission as today.
                nudged = True
                if prov.wire == "anthropic":
                    messages.append({"role": "assistant", "content": raw})
                else:
                    messages.append(raw)
                messages.append({"role": "user", "content": _NUDGE[state_name]})
                yield f"\n\n[GeoForge: the turn ended without a plan or a question; asking {prov.label} to finish it]\n\n"
                continue
            if flow is not None:
                flow.provider_succeeded = True
            return

        results = []
        for call_id, name, args in calls:
            if handle is not None and handle.stopped.is_set():
                yield f"\n[{prov.label} stopped by the user before {name}]"
                return
            if presentation == "log":
                yield f"\n`> {name}({', '.join(f'{k}={v!r}' for k, v in args.items())[:80]})`\n"
            else:
                yield activity_marker(name)
            if approve is not None and not approve(name, args):
                out = "DENIED by the user. Do not retry; explain what you needed it for."
            else:
                try:
                    out = execute_tool(name, args, ki, cfg, setup_mode=setup_mode,
                                       setup_context=tool_context,
                                       project_mode=project_mode, flow=flow)
                except ToolError as e:
                    out = f"ERROR: {e}"
            handoff = handoff or _handoff_made(name, args, str(out))
            results.append((call_id, out))
            if (name == "request_user_action" and flow is not None
                    and getattr(getattr(flow, "state", None), "value", "") in _HANDOFF_STATES
                    and not str(out).startswith(("ERROR:", "DENIED"))):
                # A question to the user ends the turn: the answer arrives as the next
                # message. Writing a plan on top of an unanswered question is not allowed.
                yield f"\n[GeoForge: {prov.label} asked you a question; waiting for your answer]\n"
                flow.provider_succeeded = True
                return

        if prov.wire == "anthropic":
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": out}
                for cid, out in results]})
        else:
            messages.append(raw)
            for cid, out in results:
                messages.append({"role": "tool", "tool_call_id": cid, "content": out})

    if max_steps is not None:
        yield f"\n[stopped after {max_steps} steps without finishing]"
