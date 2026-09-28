# Web harness comparison for Desktop project inputs

Date: 2026-09-27. Status: **historical source comparison; current deployed web version not yet supplied**.

## Source and limits

- Downloaded repository: `lzwei196/ki-harness-snapshot-20260829`, branch `main`.
- Exact fetched commit: `fc33a44831b411ce66a536bcf10da71b59d5f9cf` (commit dated August 31).
- Its README identifies the web source as an **August 29 working-tree snapshot**, not a September deployment export.
- Separate local checkout: `/private/tmp/geoforge-web-harness.Of6I7n/source`.
- Desktop comparison: local `mac-version` at `bdf2522e`, including existing uncommitted activity-display changes. Those changes were preserved.
- The snapshot includes the backend, server prompts/skills, ATA planner and shared harness. It deliberately excludes the frontend source, live database, model sources and run outputs.
- No server, provider, model or downloaded source code was executed. No live project, approval, download or installation was changed. This review does not reproduce or invalidate the user's successful web runs.
- The private snapshot contains deployment-sensitive configuration; do not publish it or copy it wholesale into the Desktop repository.

The current web source location has been requested. These findings are useful historical evidence, not a claim that this is today's working server.

## Main finding

The shared scientific harness and the web host's orchestration are different layers. Copying the harness alone cannot copy the web's complete project/data workflow.

Historical `web/ki_tools_common/ki_tools_common/harness/ki_harness.py:188` and current `ki_tools_common/ki_tools_common/harness/ki_harness.py:188` expose essentially the same scientific contract. Their source differences concern interpreter portability and inspect-mode authorization, not a new universal parameter/path planner. The function does not accept a project input table or user decisions.

The historical web backend injects its own execution instructions (`web/hydrocraft-web/backend/services/cli_process_manager.py:1268`); no shared `ki_harness.contract()` call was found in its backend services. It does use related shared path/digest utilities. Current Desktop explicitly loads the shared contract through `kiss/kiss_cli/harness_runtime.py:110` and `ki_tools_common/ki_tools_common/flow/contracts.py:33`.

This narrows where to investigate, but does not prove the cause of any particular live failure.

## The user's five links, compared

Here `WEB` means `web/` inside the downloaded snapshot. Paths and line numbers describe that pinned version.

| Link | Historical web evidence | Desktop implication |
|---|---|---|
| Requirement | ATA cards retain canonical ID, local name, category and unit (`WEB/ata-kdt/planner/derive_plan.py:399`) | Retain the richer real KI declarations and unknown/local names; do not reduce inputs to the ATA card |
| Select source/value | Per-input primary obtain strategy plus fallbacks (`derive_plan.py:414`) | Let the agent recommend a method/source/default, then retain the user's effective choice and rationale |
| Actual files | Server-local inspection; data mode checks file evidence and registry/rediscovery (`WEB/hydrocraft-web/backend/services/data_mode.py:128`) | A catalogue entry or remote result is not a local binding; preserve remote inspection and verified local acquisition separately |
| Preparation | Abstract graph leaves commands, working directory and expected outputs for the agent to fill (`derive_plan.py:438`) | Link raw files/values to explicit preparation steps and prepared artifacts; do not label a proposed method ready |
| Consuming KI step | Coupling links plus typed stage handoffs and `must_consume` artifacts (`WEB/hydrocraft-web/backend/services/worker_protocol.py:252`) | Pass exact producer outputs into the correct consumer, not a loose directory suggestion |

This is a many-to-many relationship: a parameter can remain a scalar, several variables can share a file, and one source file can feed several prepared files. The input table should display this relationship without forcing everything into one-file-per-row storage.

## Mechanisms worth reusing

### Project ownership, explicit references and stage handoffs

- `WEB/hydrocraft-web/backend/services/projects.py:807` gives each conversation a workspace under its owning project. Sibling conversations can share the project without sharing the same leaf workspace.
- `projects.py:734` supports `project:<relative-path>` references; `:754` resolves them against the current root. External input references remain absolute. This is a useful mechanism, not proof that every web reference is portable or that the helper alone is a confinement check.
- `worker_protocol.py:252` validates declared artifact paths, confinement to the project and `must_consume` membership. Selected producer types also require byte-level manifests.
- `worker_protocol.py:449` derives downstream packets from recorded producer evidence.
- `mode_contract.py:139` avoids substituting an older run's output when the newest run has none, and rejects output evidence predating the plan revision.

The valuable pattern is: **which run produced this file, under which plan, and which next step must read it?**

### Data status backed by evidence

`data_mode.acquire_and_register()` checks a real file, a registry write and rediscovery. For observation datasets, rediscovery must succeed; genuinely non-observation files can have no applicable family sweep (`data_mode.py:128–179`). These checks are not full scientific suitability validation.

`data_mode.py:199` represents unavailable data as a blocking human resource request, including the target, reason and suggested location. Desktop can expose the equivalent action on the relevant input row without conflating it with plan approval.

## Important differences and limits

1. **There is no single web chat flow in this snapshot.** `mode_router.py:25` runs the pre-planner for `run_model`, `legacy`, `model_planning` and `ata_planning`; other modes have separate paths. The call site is `cli_process_manager.py:874`. Do not infer general chat behavior from an ATA-only path.
2. **A derived plan is not user approval.** `pre_planner.py:215` writes `PLAN_OK` after derivation. Its later prompt asks for user confirmation. Orchestrated dispatch also has real prerequisite checks (`research_orchestrator.py:6256`), so the entire web system must not be described as prompt-only. Its execution-plan event check is not the same mechanism as Desktop's signed artifact approval.
3. **An obtain strategy is not a prepared input.** `derive_plan.py:420–434` calculates `auto_resolved` as total inputs minus `from_user` inputs. It does not prove files exist or are suitable.
4. **ATA cards are not exhaustive KI specifications.** The snapshot APEX card (`WEB/ata-kdt/cards/APEX_ata_card.yaml:14`) has one input, `temp`, with unknown units. Current Desktop parses 21 APEX requirement rows. Do not replace the full KI knowledge with that simplified card.
5. **Direct local file access is a material difference.** Server agents can inspect local dataset files. Desktop must obtain corresponding evidence through describe/subset/download or user-supplied files. A server path such as `/mnt/...` is not usable as a Desktop file path.
6. **Web uploads are not a finished input-binding solution.** `WEB/hydrocraft-web/backend/api/files.py:153` stores uploads under a shared server upload root and returns a path; it does not itself bind a model requirement. Frontend attachment behavior cannot be verified from this export. Desktop already stores uploads inside the project, but still needs explicit requirement bindings.
7. **Normal web CLI chat does not always launch inside its leaf workspace.** `cli_process_manager.py:1361` injects project paths and instructions, while `:1601` uses the shared server root as process cwd. Autopilot uses its project directory at `:2368`. Do not claim universally enforced filesystem isolation.
8. **Do not transplant old dataset recommendations.** `derive_plan.py:328` contains fixed geographic/year forcing rules. Desktop should preserve its current native-schema discovery, project-scoped estimates and subset transport rather than importing historical CMFD coverage assumptions.

## Consequence for the Desktop improvement plan

Keep the proposed central input table and the existing shared approval/evidence authority. Use the codebase-design skill's module/interface distinction to keep project input resolution in one module, with host-specific adapters for local imports and remote data acquisition. Do not introduce a second independently editable plan or path registry.

The agent authors and explains the project-specific mapping using the real KI. The host preserves choices and establishes file/path evidence. The KI's own tools perform scientific preparation and write model-specific configuration.

Recommended order, pending confirmation against the current web source:

1. Repair per-KI output/config isolation and bind supplied files to the intended requirement.
2. Present the same requirement/selection/artifact/preparation/consumer relationship to both user and agent.
3. Preserve distinction between proposed acquisition, acquired raw data, prepared model input and validated readiness.
4. Carry producer/run/plan revision evidence into the consuming step; changing an input invalidates dependent preparation evidence.
5. Exercise one simple existing KI, a multi-file parameter deck, a coupled VIC–CaMa case and a user-files-only case. Small deterministic tests check the Desktop handoff; provider-driven trials separately check the agent's scientific interpretation.

No production implementation, merge, build or push was performed for this comparison.
