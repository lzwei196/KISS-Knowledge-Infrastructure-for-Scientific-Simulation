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
import http.client
import ssl
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
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
                 project_mode: bool = False, flow=None) -> list[dict]:
    """``flow`` (a flowgate.FlowSession) filters the list by the project's flow state
    (plan v3 B4): the agent never sees a tool it may not call in this state."""
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
                "description": "Read a text file from this chat's local project.",
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
                    "Do not replace a KI tool with improvised calculations. Required "
                    "environment values are taken automatically from this approved plan step; "
                    "do not try to install startup hooks or mutate the system environment."
                ),
                "input_schema": {"type": "object", "properties": {
                    "tool_path": {"type": "string", "description": "path below tools/ of the KI, "
                                  "or the absolute path of the model binary the KI declares",
                                  "description": "Python file relative to the KI root and below a tools/ directory"},
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
                "name": "run_calibration",
                "description": (
                    "Run this KI's project calibration adapter through GeoForge's "
                    "bundled calibration engine. numpy, SPOTPY, and pymoo run "
                    "inside the app, not the user's system Python. Use only after "
                    "the real model, observations, adapter, and holdout definition "
                    "are ready. The full report and engine log are saved in the "
                    "chat project's calibration/runs directory."
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
                    "seed": {"type": "integer"},
                    "determining_metric": {"type": "string"},
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
                    "user. Use only for a protected download, licence/login, private "
                    "data, system permission, or high-impact scientific choice that "
                    "the KI cannot resolve. Never use it for ordinary KI defaults."
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
                "description": "Read a text file from the writable setup workspace.",
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
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
                "name": "run_setup_command",
                "description": (
                    "Run one non-shell command inside the model workspace and return "
                    "stdout, stderr, and its exit code. The executable, working "
                    "directory, and explicit path arguments are checked against a "
                    "build-tool/workspace allowlist; sudo, inline Python, credentials, "
                    "and system package installation are intentionally unavailable."
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
                "name": "request_replan",
                "description": (
                    "EXECUTING only. Use when the approved plan cannot be carried out as written "
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
                    "PLANNING only. Write runs/plan.json and runs/data-inventory.json (the "
                    "schemas are in your instructions). GeoForge validates them; errors come "
                    "back and nothing is written until they pass. No downloads, no inputs, no "
                    "model runs happen in planning — the user approves the plan first. If the "
                    "two documents together are large, send them in two calls: first only "
                    "plan, then only data_inventory; GeoForge merges them."
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


_INSTALL_ONLY_PROBE_FLAGS = {"--version", "-version", "-V", "-v", "--help", "-h"}
_INSTALL_ONLY_BUILD_NAMES = (
    "build", "compile", "configure", "setup", "install", "bootstrap",
    "quickbuild", "mkmf", "checkout", "external",
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

    if command in {"awk", "find"}:
        raise ToolError(
            f"installation-only mode blocks {command}; it can launch arbitrary "
            "child processes. Use a bounded Python inspection probe instead"
        )
    if command == "git" and any(arg in {"-c", "--config-env"}
                                 or arg.startswith("--config-env=")
                                 for arg in args):
        raise ToolError(
            "installation-only mode blocks per-command Git configuration "
            "because aliases, pagers, filters and hooks can launch programs"
        )

    # Build systems may compile, but their explicit test/run targets would
    # cross from installation into scientific execution.
    if command in {"make", "gmake", "ninja", "meson", "cmake", "cargo", "go"}:
        blocked_targets = {"test", "tests", "check", "run", "submit", "example", "examples"}
        if any(arg.lower().lstrip("-") in blocked_targets for arg in args):
            raise ToolError(
                "installation-only mode blocks build-system test/run targets; "
                "compile the software without executing its examples"
            )
        return

    # Package managers, compilers, source-control and read-only inspection
    # tools are installation operations rather than model invocations.
    if command in {
        "git", "pkg-config", "pip", "pip3", "uv", "rustc", "gcc", "g++",
        "clang", "clang++", "gfortran", "tar", "unzip", "curl", "wget",
        "patch", "sed", "ls", "cp", "mv", "ln", "chmod",
        "file", "otool", "xcode-select", "brew",
    }:
        return

    # Python is also used for small workspace inspection scripts and package
    # installation.  Do not let a generated script hide a model invocation.
    if command.startswith("python"):
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
        if any(word in name for word in _INSTALL_ONLY_BUILD_NAMES):
            return
        if script.parent != workroot or not any(
                word in name for word in ("probe", "inspect", "check", "verify")):
            raise ToolError(
                "installation-only mode blocked this Python model/data command; "
                "only build helpers or root-level inspection probes may run"
            )
        try:
            source = script.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as e:
            raise ToolError(f"cannot inspect installation probe: {e}") from e
        if any(token in source for token in (
                "subprocess", "os.system", "os.popen", "popen(", "runpy", "exec(", "eval(")):
            raise ToolError(
                "installation-only inspection probes cannot launch another process; "
                "invoke a permitted build command or use a --help/--version probe directly"
            )
        return

    resolved = Path(argv[0]).resolve()
    in_workspace = resolved == workroot or workroot in resolved.parents
    if in_workspace:
        if any(word in command for word in _INSTALL_ONLY_BUILD_NAMES):
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
    return path.name.startswith("setup-request") and path.suffix == ".json"


def execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                 setup_context: dict | None = None,
                 project_mode: bool = False, flow=None) -> str:
    """Run one tool. Every path argument is confined to the KI package.

    ``flow`` (flowgate.FlowSession, plan v3 B4): when present, every call is re-checked
    against the project's flow state before it runs (the schema filter is not trusted on
    its own), writes obey ``flow.write_allowed``, model/tool runs and downloads write
    signed receipts, and agent progress reports cannot move the stage."""
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
    progress_root = project_root

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
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:60000]

    if name == "list_ki_files":
        base, ki_root = _ki_scoped(args.get("subdir") or ".")
        names = sorted(str(f.relative_to(ki_root)) for f in base.rglob("*") if f.is_file())
        return "\n".join(names[:400]) or "(empty)"

    if name == "run_preflight":
        if bool((setup_context or {}).get("installation_only")):
            raise ToolError("Full preflight is outside installation-only scope; use the declared import and executable startup checks.")
        from . import install as _install
        step = _install.run_preflight(ki, cfg.python, cfg)
        return f"{'PASS' if step.ok else 'FAIL'}\n{step.detail}"

    if name == "search_diagnostics":
        kw = (args.get("keyword") or "").lower()
        if not kw:
            raise ToolError("keyword required")
        hits: list[str] = []
        for f in root.rglob("*"):
            if not f.is_file() or "diagnostic" not in str(f.relative_to(root)):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if kw in line.lower():
                    hits.append(f"{f.relative_to(root)}:{i}: {line.strip()[:200]}")
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
                names.append(f"{f.relative_to(project_root)} ({f.stat().st_size} bytes)")
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
        if p.stat().st_size > 5_000_000:
            raise ToolError("project file is too large for the text reader; use a KI tool")
        return p.read_text(encoding="utf-8", errors="replace")[:120000]

    if project_mode and name == "write_project_file":
        p = _inside_project(args.get("path") or "")
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
        return f"wrote {rel} ({len(content.encode('utf-8'))} bytes)"

    if project_mode and name == "run_ki_tool":
        tool_ki_name, tool_root = getattr(ki, "name", root.name), root
        if flow is not None:
            from .flowgate import FlowDenied
            try:
                tool_ki_name, tool_root = flow.ki_root_for(args.get("ki"), root)
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            tool_root = Path(tool_root).resolve()
            if tool_root != root and tool_root not in project_argument_roots:
                project_argument_roots.append(tool_root)
        def _inside_tool_ki(rel: str, _root=tool_root) -> Path:
            # same containment rule as _inside, against the KI this call names (multi-KI runs)
            if Path(rel).is_absolute():
                raise ToolError(f"absolute paths are not accepted: {rel}")
            p = (_root / rel).resolve()
            if p != _root and _root not in p.parents:
                raise ToolError(f"path escapes the KI package: {rel}")
            return p
        from ki_tools_common.flow.tools import is_declared_binary, is_ki_tool
        requested = str(args.get("tool_path") or "")
        binary = is_declared_binary(tool_root, requested)
        if binary:
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
        arguments = args.get("arguments") or []
        if (not isinstance(arguments, list) or len(arguments) > 100 or
                not all(isinstance(x, str) and len(x) <= 4000 for x in arguments)):
            raise ToolError("arguments must be a list of short strings")
        cwd = _inside_project(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"project directory does not exist: {args.get('cwd')}")
        for token in arguments:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if not (value.startswith(("/", "./", "../")) or "/" in value):
                continue
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            if not any(
                    resolved == base or base in resolved.parents
                    for base in project_argument_roots):
                raise ToolError(f"tool argument path escapes the project and KI: {value}")
        timeout = max(1, min(int(args.get("timeout_seconds") or 600), 3600))
        approved_env: dict[str, str] = {}
        before = None
        if flow is not None:
            from . import flowgate as _fg
            from .flowgate import FlowDenied
            # The step, KI, tool and its environment are all checked before
            # construction of the child process.
            try:
                step = flow.check_step_tool(args.get("plan_step_id"), tool_ki_name, script)
                approved_env = flow.approved_step_environment(step, tool_root)
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            before = _fg._snapshot(project_root)
        child_env = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        child_env["KISS_ROOT"] = str(project_root)
        from .paths import with_ki_tools_common
        child_env = with_ki_tools_common(cfg, child_env)
        from .calibration import with_framework_env
        child_env = with_framework_env(child_env)
        if provider_id:
            from .settings import with_provider_proxy
            child_env = with_provider_proxy(provider_id, child_env)
        child_env.update(approved_env)
        command = ([str(script)] if binary else [str(cfg.python), str(script)]) + list(arguments)
        started = time.time()
        try:
            proc = subprocess.run(
                command, cwd=str(cwd),
                env=child_env, capture_output=True, text=True, errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            tail = "".join(part.decode("utf-8", errors="replace") if isinstance(part, bytes) else (part or "")
                           for part in (e.stdout, e.stderr))[-12000:]
            if flow is not None:
                try:
                    flow.record_tool_run(ki=tool_ki_name, ki_root=tool_root, command=command, cwd=cwd,
                                         started_at=started, finished_at=time.time(), exit_code=None,
                                         before=before, plan_step_id=args.get("plan_step_id"),
                                         stdout_tail=tail)
                except Exception as exc:  # the timeout is the headline; the receipt failure is noted
                    tail += f"\n[receipt not written: {exc}]"
            return f"TIMEOUT after {timeout}s\n{tail}"
        finished = time.time()
        output = (proc.stdout + proc.stderr)[-80000:]
        if flow is None:
            return f"exit_code={proc.returncode}\n{output}"
        from .flowgate import FlowDenied
        try:
            summary = flow.record_tool_run(ki=tool_ki_name, ki_root=tool_root, command=command, cwd=cwd,
                                           started_at=started, finished_at=finished,
                                           exit_code=proc.returncode, before=before,
                                           plan_step_id=args.get("plan_step_id"),
                                           stdout_tail=output[-20000:])
        except FlowDenied as e:
            raise ToolError(str(e)) from None
        return (f"exit_code={proc.returncode}\n[RECEIPT] {json.dumps(summary, ensure_ascii=False)}\n"
                f"{output}")

    if project_mode and name == "run_calibration":
        from . import calibration as _calibration
        calib_before = None
        calib_started = time.time()
        if flow is not None:
            from . import flowgate as _fg
            from .flowgate import FlowDenied
            try:
                flow.check_step_tool(args.get("plan_step_id"), getattr(ki, "name", root.name), None)
            except FlowDenied as e:
                raise ToolError(str(e)) from None
            calib_before = _fg._snapshot(project_root, subs=("inputs", "outputs", "artifacts", "calibration"))
        # Ensure the adapter copy exists before building the generated runtime
        # KI. `ki` is already the session-materialised package in pinned chats.
        _calibration.ensure_project(project_root, [ki])
        try:
            result = _calibration.run_project(
                project=project_root,
                ki_name=ki.name,
                ki_path=root,
                obs_shape_by_var=args.get("obs_shape_by_var") or {},
                algorithm=args.get("algorithm") or None,
                budget=args.get("budget"),
                seed=int(args.get("seed") or 0),
                determining_metric=args.get("determining_metric") or None,
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
                summary["receipt"] = flow.record_tool_run(
                    ki=_kname, ki_root=root,
                    command=["geoforge-calibration", _kname, str(args.get("algorithm") or "default")],
                    cwd=project_root, started_at=calib_started, finished_at=time.time(),
                    exit_code=0 if str(report.get("status") or "").lower() in ("ok", "success", "completed", "done") else 1,
                    before=calib_before, plan_step_id=args.get("plan_step_id"),
                    stdout_tail=str(result.get("log_tail") or ""))
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
        return str(callback())[-60000:]

    if setup_mode and name == "list_work_files":
        base = _inside_work(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such workspace directory: {args.get('subdir')}")
        names = sorted(str(f.relative_to(workroot)) for f in base.rglob("*") if f.is_file())
        return "\n".join(names[:800]) or "(empty)"

    if setup_mode and name == "read_work_file":
        p = _inside_work(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such workspace file: {args.get('path')}")
        return p.read_text(encoding="utf-8", errors="replace")[:60000]

    if setup_mode and name == "write_work_file":
        p = _inside_work(args.get("path") or "")
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if len(content.encode("utf-8")) > 250_000:
            raise ToolError("write_work_file is limited to 250 KB")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {p.relative_to(workroot)} ({len(content.encode('utf-8'))} bytes)"

    if setup_mode and name == "run_setup_command":
        argv = args.get("argv")
        if (not isinstance(argv, list) or not argv or len(argv) > 100 or
                not all(isinstance(x, str) and x and len(x) <= 4000 for x in argv)):
            raise ToolError("argv must be a non-empty list of short strings")
        executable = argv[0]
        allowed = {
            "git", "cmake", "make", "gmake", "ninja", "meson", "pkg-config",
            "python", "python3", "pip", "pip3", "uv", "cargo", "rustc", "go",
            "gcc", "g++", "cc", "c++", "clang", "clang++", "gfortran", "tar", "unzip", "mkdir",
            "curl", "wget", "patch", "sed", "awk", "find", "ls", "cp", "mv", "ln",
            "chmod", "file", "otool", "xcode-select", "brew", "which",
            "cat", "grep", "head", "tail", "uname", "sw_vers",
            "autoreconf", "autoconf", "automake", "aclocal", "libtoolize", "glibtoolize",
            "ar", "ranlib", "nm", "nf-config", "nc-config", "gdal-config",
            "mpicc", "mpicxx", "mpif90", "mpifort", "flex", "bison", "R", "Rscript", "julia", "octave", "octave-cli",
        }
        exe_path = Path(executable)
        external_roots = []
        for raw in (setup_context or {}).get("existing_roots") or []:
            try:
                candidate = Path(str(raw)).expanduser().resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            external_roots.append(candidate.parent if candidate.is_file() else candidate)
        if exe_path.is_absolute() or "/" in executable:
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
            # Validate the resolved target, but execute the original venv path.
            # Dereferencing venv/bin/python here launches the base interpreter
            # without pyvenv.cfg and can send pip installs outside the workspace.
            argv[0] = str((workroot / exe_path).absolute()
                          if not exe_path.is_absolute() else exe_path)
        elif executable not in allowed:
            raise ToolError(f"command is not in the setup allowlist: {executable}")
        if Path(argv[0]).name == "brew" and len(argv) > 1 and argv[1] not in (
                "--prefix", "--version", "list", "info", "config"):
            raise ToolError("Homebrew changes require the user; create a permission request")

        cwd = _inside_work(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"command directory does not exist: {args.get('cwd')}")
        if (bool((setup_context or {}).get("installation_only"))
                or Path(argv[0]).name.lower() in {"r", "rscript", "julia", "octave", "octave-cli"}):
            _guard_installation_only_command(argv, cwd, workroot)
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
            if not (value.startswith(("/", "./", "../")) or "/" in value):
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
        extra_env = args.get("env") or {}
        if not isinstance(extra_env, dict):
            raise ToolError("env must be an object")
        safe_env = {}
        banned = {"HOME", "PATH", "SHELL", "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "PIP_REQUIRE_VIRTUALENV"}
        for key, value in extra_env.items():
            if (not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", str(key)) or
                    key in banned or not isinstance(value, str) or len(value) > 8000):
                raise ToolError(f"unsafe environment override: {key}")
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
        import tempfile
        isolate_probe = (bool((setup_context or {}).get("installation_only"))
                         and Path(argv[0]).is_absolute() and len(argv) == 2
                         and argv[1] in _INSTALL_ONLY_PROBE_FLAGS)
        if isolate_probe:
            timeout = min(timeout, 25)
        try:
            directory = (tempfile.TemporaryDirectory(prefix="startup-probe-", dir=str(workroot))
                         if isolate_probe else nullcontext(str(cwd)))
            with directory as execution_cwd:
                proc = subprocess.run(
                    argv, cwd=execution_cwd, env={**child_env, **safe_env, "PIP_REQUIRE_VIRTUALENV": pip_guard},
                    capture_output=True, text=True, errors="replace", timeout=timeout,
                    stdin=subprocess.DEVNULL if isolate_probe else None,
                )
        except subprocess.TimeoutExpired as e:
            tail = "".join(part.decode("utf-8", errors="replace") if isinstance(part, bytes) else (part or "")
                           for part in (e.stdout, e.stderr))[-12000:]
            return f"TIMEOUT after {timeout}s\n{tail}"
        except OSError as e:
            # A non-executable script, missing command, or platform launch
            # error is normal repair-loop evidence.  Let the model see it and
            # choose another invocation (usually ``python3 script.py``)
            # instead of aborting the entire API turn.
            return f"FAILED_TO_START: {type(e).__name__}: {e}"
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
            f"published {source_rel} to {destination_rel} "
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
        "Your turn ended without write_plan, so nothing was submitted. Do not describe what you "
        "will do; call write_plan now with both files. If one decision genuinely needs the user, "
        "call request_user_action with that single question instead."),
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
    tool_context.setdefault("provider_id", f"api:{prov.name}")
    tools = tool_schemas(ki, setup_mode=setup_mode, project_mode=project_mode, flow=flow)
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
            tools = tool_schemas(ki, setup_mode=setup_mode, project_mode=project_mode, flow=flow)
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
