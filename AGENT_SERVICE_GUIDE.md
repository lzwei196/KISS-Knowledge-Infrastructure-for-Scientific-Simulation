# Deploying Knowledge Infrastructure with AI Agent Services

**A practical guide to serving KI-powered model simulations through multiple AI coding agents.**

This document explains how to set up Knowledge Infrastructure (KI) so that any AI coding agent — Claude Code, OpenAI Codex, Gemini CLI, Kimi Code, or Qwen Code — can autonomously operate process-based models through a web interface.

> **Prerequisite**: Your models have been dissected using KDT and each has a `knowledge_infrastructure/` directory with SKILL.md, tools, and diagnostic triplets.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [The Instruction File Problem](#2-the-instruction-file-problem)
3. [Setting Up Provider Instructions](#3-setting-up-provider-instructions)
4. [Writing the Master Instruction File](#4-writing-the-master-instruction-file)
5. [Example: VIC + Lohmann Routing Workflow](#5-example-vic--lohmann-routing-workflow)
6. [Example: VIC + CaMa-Flood Workflow](#6-example-vic--cama-flood-workflow)
7. [Model-Specific Guardrails](#7-model-specific-guardrails)
8. [The System Prompt Layer](#8-the-system-prompt-layer)
9. [Process Monitoring](#9-process-monitoring)
10. [Testing Your Deployment](#10-testing-your-deployment)

---

## 1. Architecture Overview

A KI-powered agent service has three layers:

```
┌──────────────────────────────────────────────────────────┐
│  User (browser)                                          │
│  "Simulate river discharge for Bengbu, 2000-2010"        │
└───────────────────────────┬──────────────────────────────┘
                            │ WebSocket
┌───────────────────────────▼──────────────────────────────┐
│  Web Backend (FastAPI)                                    │
│  - Spawns CLI agent subprocess per conversation           │
│  - Injects system prompt with guardrails                  │
│  - Streams agent output back to browser                   │
│  - Monitors model processes (CPU, memory, elapsed time)   │
└───────────────────────────┬──────────────────────────────┘
                            │ subprocess
┌───────────────────────────▼──────────────────────────────┐
│  AI Coding Agent (Claude Code / Codex / Gemini / Kimi)   │
│  - Reads master instruction file (CLAUDE.md / AGENTS.md)  │
│  - Reads model SKILL.md before running each model         │
│  - Calls validated tools from KI                          │
│  - Executes model binaries                                │
│  - Generates visualizations                               │
└───────────────────────────┬──────────────────────────────┘
                            │ calls
┌───────────────────────────▼──────────────────────────────┐
│  Knowledge Infrastructure (per model)                     │
│  models/<Name>/knowledge_infrastructure/                   │
│  ├── SKILL.md          (operational manual)                │
│  ├── tools/            (validated data prep scripts)       │
│  ├── diagnostics/      (triplets: symptom→diagnosis→fix)   │
│  └── preflight_check.py (environment verification)        │
└──────────────────────────────────────────────────────────┘
```

**Key insight**: The agent is a bridge between natural language and KI. It reads SKILL.md to understand what to do, calls tools to prepare data, runs the model binary, and interprets results. The KI quality determines whether the agent succeeds or produces silent errors.

---

## 2. The Instruction File Problem

Each AI coding agent CLI has a different convention for loading project-level instructions:

| Provider | Convention | File | Loaded As |
|----------|-----------|------|-----------|
| Claude Code | `CLAUDE.md` in project root | Auto-loaded into **system prompt** — always in context | System-level |
| OpenAI Codex | `AGENTS.md` in project root | Read at session start | Session-level |
| Gemini CLI | `~/.gemini/GEMINI.md` (global) | Read once at start | Global |
| Kimi Code | `.kimi/skills/<name>/SKILL.md` | Loaded as a named "skill" | Skill-level |
| Qwen Code | `QWEN.md` in project root | Read at session start | Session-level |

### Why This Matters

Without the instruction file, the agent has no context about:
- Where model binaries are located
- What validated tools exist (it will write custom scripts that reintroduce known bugs)
- Unit conversion requirements (silent errors)
- The correct execution workflow

**An agent without instructions will produce scientifically wrong results with no error message.**

### The System-Level Distinction

Claude Code injects `CLAUDE.md` into the system prompt — it's always present for every response, like a system instruction. Other providers load their file once and it may drop from context during long conversations. This is why Claude Code follows complex multi-step workflows more reliably than other providers.

---

## 3. Setting Up Provider Instructions

### Step 1: Write one canonical instruction file

Create `CLAUDE.md` as the single source of truth. This file contains everything an agent needs: model paths, data paths, workflow steps, unit traps, and guardrails.

### Step 2: Symlink for each provider

```bash
# Codex reads AGENTS.md
ln -sf CLAUDE.md AGENTS.md

# Qwen reads QWEN.md
ln -sf CLAUDE.md QWEN.md

# Gemini reads from global config (symlink to absolute path)
ln -sf /path/to/project/CLAUDE.md ~/.gemini/GEMINI.md
```

### Step 3: Copy for skill-based providers (Kimi)

Kimi uses a skill system. The project-level skill needs to be a copy (not symlink) because Kimi requires YAML frontmatter:

```bash
# Create the skill directory structure
mkdir -p .kimi/skills/myproject/
mkdir -p .agents/skills/myproject/

# Copy the full instruction file
cp CLAUDE.md .agents/skills/myproject/SKILL.md

# Symlink Kimi and Codex skills to the same directory
ln -sf $(pwd)/.agents/skills/myproject .kimi/skills/myproject
ln -sf $(pwd)/.agents/skills/myproject .codex/skills/myproject
```

**Sync procedure**: When you update `CLAUDE.md`, symlinked files auto-update. For copied files (Kimi), re-copy manually:

```bash
cp CLAUDE.md .agents/skills/myproject/SKILL.md
```

### Verification

```bash
# Check all files exist and have identical content
wc -l CLAUDE.md AGENTS.md QWEN.md ~/.gemini/GEMINI.md .agents/skills/*/SKILL.md
```

---

## 4. Writing the Master Instruction File

The master instruction file (`CLAUDE.md`) must contain these sections:

### 4.1 Platform Introduction

Tell the agent what it is and what it can do. List all available models.

```markdown
## About
HydroCraft is an AI-driven multi-model simulation platform.
31 model packages, ~436 tools, 14 global databases.

## Supported Models
| Domain | Models |
|--------|--------|
| Hydrology | VIC 5.1.0, WRF-Hydro 5.2.0, Raven 4.1 |
| Routing | Lohmann, CaMa-Flood 4.20 |
| ... | ... |
```

### 4.2 Data Registry

Exact paths to every dataset. The agent must NOT guess paths.

```markdown
## Data Registry
| Dataset | Path | Coverage |
|---------|------|----------|
| CMFD forcing | data/forcing/Data_forcing_03hr_010deg/ | China, 1979-2018 |
| MSWX forcing | data/forcing/MSWX/ | Global, 1979-2026 |
| HWSD soil | data/soil/HWSD_RASTER/hwsd.bil | Global |
```

### 4.3 Model Selection Guide

Map user intents to models. Users say "simulate floods", not "run CaMa-Flood":

```markdown
## Model Selection Guide
| User wants... | Primary model | Alternative |
|--------------|--------------|-------------|
| River discharge | VIC + Lohmann | Raven |
| Flood inundation | VIC + CaMa-Flood | VIC + CaMa + SFINCS |
| Crop yield | DSSAT | AquaCrop, WOFOST |
```

### 4.4 Workflow Steps

The complete execution workflow with exact script paths and validation checks:

```markdown
## Workflow
Step 0: Basin delineation → delineate_basin.py
Step 1: Grid generation → make_basin_grid_nc.py
Step 2: Soil parameters → fill_parameters1.py + fill_parameters2.py
...
```

### 4.5 Unit Trap Warnings

The most critical section. List every known unit mismatch:

```markdown
## Critical Unit Traps (Silent Errors)
| Model | Trap | Wrong → Right | Impact |
|-------|------|---------------|--------|
| GLM | Rain must be m/day not mm/day | ÷1000 | 1000x too much rain |
| ParFlow | K must be m/hr not m/day | ÷24 | 24x wrong infiltration |
```

### 4.6 Agent Discipline Rules

Rules that override the agent's default behavior:

```markdown
## Agent Discipline
1. PLAN FIRST: Show numbered plan, wait for user confirmation
2. VERIFY EACH STEP: Check output exists and values are reasonable
3. NEVER write custom scripts when validated tools exist
4. READ the model's SKILL.md BEFORE running any model
```

### 4.7 KI Reference

Tell the agent where to find model-specific documentation:

```markdown
## Knowledge Infrastructure
Every model has KI at: models/<ModelName>/knowledge_infrastructure/
- SKILL.md: Operational manual (READ BEFORE RUNNING)
- tools/: Validated data preparation scripts (USE THESE, don't write custom)
- diagnostics/triplets.yaml: Known errors with fixes
- preflight_check.py: Run before model execution
```

---

## 5. Example: VIC + Lohmann Routing Workflow

This is the standard hydrological simulation workflow. The KI files are at:

```
models/VIC/knowledge_infrastructure/
├── SKILL.md                              # 505 lines, Chinese+English
├── SKILL_en.md                           # English version
├── config_paths.py                       # Path configuration
├── preflight_check.py                    # Environment check
├── s1_grid/make_basin_grid_nc.py         # Grid generation
├── s2_forcing/forcing_1d.py              # Forcing extraction (CMFD/MSWX)
├── s2_forcing/process_forcing.py         # NetCDF → ASCII conversion
├── s3_soil/fill_parameters1.py           # HWSD → VIC soil params
├── s3_soil/fill_parameters2.py           # Pedotransfer functions
├── s4_veg/process_vegetation_detailed.py # AVHRR → VIC veg classes
└── run_vic_pipeline_enhanced.py          # Full pipeline orchestration

models/Lohmann_Routing/knowledge_infrastructure/
├── SKILL.md                                        # 355 lines
├── SKILL_en.md
├── preflight_check.py
├── preprocess_vic_for_routing.py                   # VIC output 22→7 columns
└── s5_routing_param/run_build_routing_new.py       # DEM → flow direction → UH
```

### The Agent's Execution Flow

When a user says: *"Simulate river discharge for Bengbu, 2000-2010"*

The agent reads `CLAUDE.md` and follows these steps:

```
1. Read CLAUDE.md → selects VIC + Lohmann routing
2. Read models/VIC/knowledge_infrastructure/SKILL.md → learns workflow
3. Delineate basin (WhiteboxTools)
4. Run config_paths.py → set resolution, paths
5. Run s1_grid/make_basin_grid_nc.py → create grid
6. Run s3_soil/fill_parameters1.py + fill_parameters2.py → soil params
7. Run s4_veg/process_vegetation_detailed.py → vegetation params
8. Run s2_forcing/forcing_1d.py → extract CMFD/MSWX forcing
9. Run s2_forcing/process_forcing.py → convert to VIC ASCII format
10. Create global_param file → configure VIC
11. Run VIC binary → model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe
12. Read models/Lohmann_Routing/knowledge_infrastructure/SKILL.md
13. Run preprocess_vic_for_routing.py → 22 columns → 7 columns (CRITICAL)
14. Run s5_routing_param/run_build_routing_new.py → flow direction, UH
15. Run model/route_1.0/src/rout → Lohmann routing
16. Generate discharge plot → skills/plot/plot_discharge_comparison.py
```

### Critical Guardrails for This Workflow

These MUST be in `CLAUDE.md`:

```markdown
- VIC output MUST be preprocessed before routing (22→7 columns)
  Without this, routing reads wrong columns and produces garbage
- Fortran routing has ~72 char path limit — use symlinks for long paths
- Delete *.uh_s files before re-running routing
- Time range must sync across: forcing_1d.py, process_forcing.py,
  global_param, and rout_global.txt (4 locations!)
```

---

## 6. Example: VIC + CaMa-Flood Workflow

CaMa-Flood replaces Lohmann routing with hydrodynamic river routing + flood inundation. The KI is at:

```
models/CaMa_Flood/knowledge_infrastructure/
├── SKILL.md                                    # 859 lines
├── SKILL_en.md
├── preflight_check.py
├── vic_post/process_vic_for_cama.py            # VIC → NetCDF runoff
└── vic_post/process_data_windows_ymd.py        # Date processing
```

Plus a setup automation script referenced in `CLAUDE.md`:
```
skills/cama-flood-run/setup_cama_basin.py       # Automated: regionalize map +
                                                 # input matrix + channel params +
                                                 # run script generation
```

### The Agent's Execution Flow

When a user says: *"Simulate floods in the Huai River basin"*

```
1. Read CLAUDE.md → selects VIC + CaMa-Flood (user said "floods")
2. Steps 1-11: Same as VIC + Lohmann (basin → grid → soil → veg → forcing → VIC run)
3. ⚠️ STOP — DO NOT read workflow.md Steps 8-10 (those are Lohmann-only!)
4. Read models/CaMa_Flood/knowledge_infrastructure/SKILL.md
5. Run vic_post/process_vic_for_cama.py → convert VIC output to NetCDF
6. Run setup_cama_basin.py → automated map regionalization + input matrix
7. Run bash model/cmf_v420_pkg/gosh/run_<basin>_1d_nc.sh → CaMa-Flood
8. Generate flood map → skills/plot/plot_cama_results.py
```

### Critical Guardrails for CaMa-Flood

```markdown
- CaMa-Flood MUST use ABSOLUTE paths in namelist (relative paths → STOP 10 error)
- Maps MUST be regenerated for each new basin (cannot reuse another basin's map)
- Input matrix (inpmat) must match VIC grid extent exactly, NOT the CaMa domain extent
- After VIC Steps 1-7, DO NOT follow workflow.md Steps 8-10 — those are Lohmann only
```

### Why Both Workflows Need to Be in CLAUDE.md

The agent must know WHICH workflow to follow based on user intent:

| User says... | Agent selects... |
|-------------|-----------------|
| "river discharge", "streamflow", "hydrograph" | VIC + Lohmann (Steps 1-10) |
| "flood", "inundation", "flood depth", "CaMa" | VIC + CaMa-Flood (Steps 1-7 → CaMa) |
| "high-res flood map", "100m flood" | VIC + CaMa-Flood + SFINCS downscaling |

If the wrong workflow is followed, the agent will either:
- Try to run Lohmann routing after CaMa-Flood setup (conflict)
- Run CaMa-Flood Steps on Lohmann-preprocessed output (wrong format)

---

## 7. Model-Specific Guardrails

Every model has unit traps and operational pitfalls. These MUST be in the master instruction file because the agent may not read every model's SKILL.md proactively.

### Format

```markdown
## Critical Model-Specific Warnings (Silent Errors)

| Model | Trap | Wrong → Right | Impact if wrong |
|-------|------|---------------|-----------------|
| GLM | Rain must be m/day not mm/day | ÷1000 | 1000x too much rain |
| DSSAT | Must use dssat_workdir_setup.py | — | FileX format errors, wrong weather |
| VIC | Forcing column order matters | Check global_param | Wrong variables mapped |
```

### The "Validated Tool" Rule

The single most important guardrail:

> **NEVER write custom scripts when a validated tool exists in the KI.**
>
> Every `tools/` directory contains scripts that handle known edge cases, unit conversions,
> and format quirks. Custom scripts reintroduce the exact bugs these tools were built to prevent.

This rule prevents the #1 agent failure mode: the agent writes a Python script to prepare model input, misses a unit conversion, and the model runs successfully with wrong results.

---

## 8. The System Prompt Layer

For web services where the backend spawns CLI agents, there are three layers of instruction:

### Layer 1: Master Instruction File (loaded at session start)
- `CLAUDE.md` / `AGENTS.md` / etc.
- Full context: all models, data paths, workflows, guardrails
- ~1000 lines, loaded once

### Layer 2: System Prompt (injected by backend per conversation)
- Condensed version for non-Claude providers
- Contains: model list, critical data paths, unit traps, discipline rules
- ~200 lines, injected with first message

### Layer 3: Follow-up Reminder (injected with every message)
- Ultra-short, most critical rules only
- Contains: "read SKILL.md first", "use validated tools", "verify each step"
- ~10 lines, always in context

```python
# Backend code example
if provider == "claude-code":
    # Claude auto-loads CLAUDE.md — only inject run_id
    prompt = f"[run_id={run_id}]\n{user_message}"
else:
    # Other CLIs: inject system prompt + reminder
    prompt = f"{SYSTEM_PROMPT}\n{REMINDER}\n{user_message}"
```

### Why Three Layers?

- **Claude Code**: Only needs Layer 1 (auto-loaded, always in system context)
- **Codex/Gemini**: Need Layers 1+2 (file may drop from context in long conversations)
- **Kimi/Qwen**: Need all 3 layers (skill may be deprioritized, need constant reminders)

---

## 9. Process Monitoring

When models run as background processes (`nohup ... &`), they get orphaned from the agent's process tree. The web frontend needs to detect these.

### The Orphan Problem

```
Agent (PID 1000)
  └── bash: nohup python forcing.py &    # bash exits
        └── python forcing.py (PID 1001)  # reparented to PID 1
                                           # psutil.children() can't find it
```

### The Fix: Conversation-ID Scanning

Since all output directories contain the conversation ID (e.g., `outputs/xixian_nutrients_8e48f7fa/`), scan all running processes for the conversation ID prefix:

```python
conv_short = conversation_id[:8]
for p in psutil.process_iter(["pid", "cmdline"]):
    cmd_str = " ".join(p.info.get("cmdline", []))
    if conv_short in cmd_str:
        # This process belongs to our conversation
        orphaned_children.append(p)
```

This catches `nohup`'d model runs, forcing scripts, and any other background process the agent started for this conversation.

---

## 10. Testing Your Deployment

Before opening to users, test each provider independently.

### Test Matrix

| Test | What to verify | Pass criteria |
|------|---------------|---------------|
| **Instruction loading** | Does the agent reference CLAUDE.md content? | Agent mentions model paths, data registry |
| **SKILL.md reading** | Ask to run VIC — does it read VIC's SKILL.md? | Agent reads the file before executing |
| **Validated tools** | Ask to run DSSAT — does it use dssat_workdir_setup.py? | Agent imports from KI tools, not custom code |
| **Unit traps** | Check forcing output — are units physically reasonable? | Temperature in °C, precip in mm/day, SRAD in W/m² |
| **Workflow routing** | Ask for "flood simulation" — does it use CaMa-Flood? | Agent follows CaMa steps, not Lohmann |
| **Process monitor** | Run a long model — does frontend show progress? | CPU%, memory, model label visible |
| **Error handling** | Give invalid coordinates — does agent report clearly? | Agent explains the error, suggests fix |

### Test Prompts

Use these across all providers:

1. **Basic hydrology**: "How much water flows through the river near Bengbu?"
2. **Flood mapping**: "Show me a flood map for the Huai River basin"
3. **Crop yield**: "What maize yield can I expect near Bengbu this year?"
4. **Climate projection**: "How will rainfall change in the next 30 years?"
5. **Model mismatch**: "Run GLM for Bengbu" (GLM is a lake model — agent should clarify)

### Red Flags

If any of these happen, the KI deployment needs fixing:

- Agent writes custom `matplotlib` code instead of using `skills/plot/` scripts
- Agent creates FileX files manually instead of using `dssat_workdir_setup.py`
- Agent reports "expected values from literature" instead of actual simulation results
- Agent runs VIC Steps 8-10 (Lohmann) when user asked for flood simulation (CaMa)
- Agent uses CMFD for a basin outside China (silent error — CMFD only covers China)
- Model runs successfully but yields/discharge are off by orders of magnitude (unit trap)

---

## Summary

| Component | Purpose | Where |
|-----------|---------|-------|
| `CLAUDE.md` | Master instruction file (source of truth) | Project root |
| `AGENTS.md`, `QWEN.md` | Symlinks to CLAUDE.md | Project root |
| `~/.gemini/GEMINI.md` | Symlink to CLAUDE.md | Home directory |
| `.agents/skills/*/SKILL.md` | Copy of CLAUDE.md (Kimi/Codex skills) | Project `.agents/` |
| `models/*/knowledge_infrastructure/SKILL.md` | Model-specific operational manual | Per model |
| `models/*/knowledge_infrastructure/tools/` | Validated data preparation scripts | Per model |
| `models/*/knowledge_infrastructure/diagnostics/` | Error knowledge (triplets) | Per model |
| System prompt (backend) | Condensed guardrails for non-Claude providers | Backend code |
| Follow-up reminder | Critical rules injected per message | Backend code |

**The golden rule**: If you update `CLAUDE.md`, all agents benefit immediately (via symlinks). If you update a model's `SKILL.md`, any agent that reads it benefits. The KI is the single source of truth — the agent is just the delivery mechanism.

---

*Part of the Knowledge Dissection Toolkit v4.0*
*Lessons from deploying HydroCraft (31 models, 5 providers) at app.hydrocraft.ai*
