# KI library pre-evaluation: connecting planning to existing KIs

Date: 2026-09-27. Source checkpoint: `bdf2522e`, with the existing uncommitted Desktop activity work preserved. Scope: read-only content/parser evaluation and diagnostic artifacts. **No scientific models, provider turns, downloads or live projects were run or changed.**

## 1. Answer in brief

The five-link relationship is appropriate:

**requirement → selected source/value → actual input(s) → preparation → consuming KI step**.

The existing KIs generally already explain these relationships through SKILL instructions, stage documents, format contracts, examples and tool interfaces. Desktop should enable the agent to assemble an explicit project-specific mapping from that knowledge. It should not require all KIs to be rewritten into a rigid universal schema, and should not confuse machine-parser limitations with failed scientific validation.

The most consequential present limitation is the draft planner's vocabulary filter: many valid local parameters, user files, geometries and configuration choices become a general `ki_internal` group rather than first-class input rows. The information is still available to an agent reading the KI; it is not adequately represented in the initial inventory/table.

Recommendation: **KI owns scientific knowledge; agent proposes the case-specific mapping; user chooses or accepts significant decisions; Desktop records the mapping and checks its paths, consistency and evidence.**

## 2. Exact audit scope

- All **127 repository KI packages**, covering all 14 current Observatory domain groups. Every package received a breadth-first reading of its workflow/input descriptions and declarations. Twelve representative tool routines were inspected in more detail across three parallel slices.
- The last-activated local update snapshot also contains **127 packages**. The same parser census was run against every package. Eleven packages differ from the repository in one or more inspected description files; the summary counts below happen to match. This is not an assertion that their entire tool trees or installed environments are identical.
- The one locally imported **ArchDam_RDC** KI was also parsed, and its SKILL, configuration/path resolver and pipeline were inspected. This makes **128 distinct KI names**, not 255 distinct models; the census has 255 package-version rows.
- Repository descriptions are the primary qualitative review. The local snapshot comparison is declaration/parser-level, not another line-by-line scientific audit. The running app's in-memory selection and every materialized project copy were not inspected.

Evidence artifacts:

- [Per-package numerical matrix, CSV](audits/ki-planning-2026-09-27/matrix.csv)
- [Full parser/declaration evidence, JSON](audits/ki-planning-2026-09-27/census.json)
- [Slice A: 43 KIs, all names and workflow patterns](issues/KI-PLANNING-SLICE-A-2026-09-27.md)
- [Slice B: 42 KIs, all names and workflow patterns](issues/KI-PLANNING-SLICE-B-2026-09-27.md)
- [Slice C: 42 KIs, all names and workflow patterns](issues/KI-PLANNING-SLICE-C-2026-09-27.md)

Coverage was checked: the three slice tables contain exactly the 127 unique repository catalogue names without omissions or overlaps. The automated audit calls current production readers, not a replacement extraction algorithm. It imports no model tools.

Reproduce the census:

```sh
python3 scripts/audit_ki_planning_compatibility.py --output docs/audits/ki-planning-2026-09-27 --include-local-library
```

The script reads local KI descriptions and the saved update-root pointer, not credentials. It writes only audit outputs. Counts describe representations, not missing datasets, required downloads, scientific completeness or successful model runs.

## 3. What current planning extracts

| Measurement on the 127 repository KIs | Result | Meaning |
|---|---:|---|
| KIs with input rows returned by Desktop's DAG/format reader | 127 | A list can be assembled; semantic correctness still matters |
| Readable DAG mappings | 123 | BMI, EF5, ESMF and PyMT have no active DAG in this checkout |
| Readable format specifications | 127 | These can supplement DAGs, but conflicts cannot be accepted blindly |
| Rows returned by Desktop preparation reader | 3,384 | Includes format-spec details; not directly equivalent to shared-reader rows |
| Shared planner input entries after its own normalization | 3,309 | Includes deduplication and excludes the four DAG-less KIs |
| Entries emitted into initial ordinary inventory rows | 359 | Matches the draft's canonical-variable filter, not full scientific input coverage |
| Entries put in `ki_internal` instead | 2,950 | Preserved in a separate group; includes genuine user inputs and parameters |
| KIs with no ordinary starter inventory rows | 23 | Not evidence of unusability; agents may reconstruct a plan from their KI |
| KIs where the current SKILL stage parser extracts stages | 118 | Nine use descriptions the parser does not recognize; not nine missing workflows |
| KIs with a `default` field in Desktop-normalized rows | 2 | Defaults in prose, source, templates and libraries are not counted here |

The counts use a no-case static draft, before the agent edits it. A final agent-reviewed plan can contain more and different rows. The starter's tools and step input bindings remain unfilled by design; scientific process modules in a DAG are not automatically executable preparation steps.

Examples of this representational difference:

| KI | Desktop input rows | Ordinary starter inventory | Separate KI-internal entries |
|---|---:|---:|---:|
| APEX | 21 | 5 | 16 |
| VIC | 48 | 9 | 38 |
| CaMa-Flood | 21 | 2 | 19 |
| DSSAT | 75 | 7 | 68 |
| OpenFOAM | 14 | 0 | 14 |
| Imported ArchDam RDC | 13 | 0 | 13 |

VIC's shared reader merges one declaration, hence its 47 shared entries versus 48 Desktop rows. These counts are not a common denominator for a scientific coverage percentage.

Root cause is explicit in `ki_tools_common/ki_tools_common/flow/plan.py:549`: inputs without a canonical ID enter `ki_internal` before ownership/default/user-file handling. `to_artifacts` at line692 builds ordinary inventory from the canonical-input list. A database vocabulary match should assist search and coupling, not determine whether a legitimate project requirement deserves a row.

## 4. Compatibility across the library

The dominant workflow forms are already represented in existing KI knowledge. They overlap; this is not a new exclusive classification or scoring system.

| Workflow form | Examples | What the project plan must retain |
|---|---|---|
| Weather/spatial data converted into model files | VIC, APEX, DSSAT, SHAW, APSIM, WOFOST | Variable meanings, scope, units, conversion and concrete consumer format |
| Multi-file deck or case directory | OpenFOAM, MODFLOW6, SWAT+, EPIC, WRF, ROMS | One case can contain many data/parameter/state files and nested references |
| Upstream model output consumed downstream | VIC→CaMa, VIC→mizuRoute, RAPID, Lohmann, MOSART | Producer output, units/grid/order/time transformation and separate consumer binding |
| User observations, geometry or network | ArchDam RDC, GemPy, SimPEG, pyGIMLi, EPANET, Pywr | Own files and site-specific values are first-class; weather/DB retrieval may be irrelevant |
| Defaults, parameter sets or model objects | SUMMA, CRHM, GEOPHIRES, PyDeltaRCM, SuperflexPy, Landlab | Values may come from tables/code/overrides or arrays; no dummy download/file required |
| Runtime-selected framework or component | BMI, PyMT, ESMF, DART | Discover requirements for the selected plugin/process/mode; do not invent one universal input list |

The application should use a common record of the five links, while letting the agent resolve model-specific details from these existing workflows. No universal one-file-per-row or weather-first process fits all 128 KIs.

### Small content exceptions to handle explicitly

- **EF5:** its wrong HYPE DAG was already quarantined, as its adjacent README explains. The surviving format specification still contains HYPE metadata. The actual EF5 protocol/tools remain available. This is a conflicting planning source, not a newly demonstrated model execution failure.
- **Generic boilerplate:** some geophysical/framework KIs include generic meteorological guidance unrelated to their specific workflow. Model-specific inputs and the selected consumer interface must determine relevance.
- **Tool/default descriptions can differ:** for example, PHREEQC documentation calls pH/temperature required while a converter supplies fallback values. The plan must distinguish a measurement from a proposed fallback and resolve conflicts instead of silently treating them as equivalent.
- **Implementation and mode matter:** where a KI explicitly describes a particular reimplementation, diagnostic workflow, benchmark or restricted mode, the plan must name that implementation. A familiar model label is not permission to imply a different engine.

These are targeted clarification/metadata items. They do not justify rejecting the whole library or rerunning its entire scientific validation suite.

## 5. The five links, made explicit

Keep the user's five stages. Add detail within them rather than creating five mandatory forms or files.

| Link | Questions the plan must answer | Who supplies/checks it |
|---|---|---|
| **1. Requirement** | What is needed and why? Data, parameter, initial state, geometry or setting? Which KI/mode/step needs it? Required or conditional? Units, dimensions, area, period and relevant quality constraints? | Agent derives from selected KI and task; app preserves the KI-local identity and references |
| **2. Selected source/value** | Own file, DB record, supported public source, KI default/library, derived method or upstream result? Which exact source, value/profile/member and version? Who selected it? What remains undecided? | Agent proposes evidence-backed alternatives; user selects/accepts consequential choices |
| **3. Actual inputs** | Which file(s), directory members, variables/columns/profile IDs or typed values are present? Where exactly? Do the files match the selected source/scope? | Host import/download records exact paths; agent/KI inspects scientific contents; proposed paths stay labeled proposed |
| **4. Preparation** | Which existing KI tool/method converts or assembles them? Inputs/arguments, project working directory, applicable units/grid/time transformations, expected output(s), and KI checks? If already prepared, which inspection is sufficient? | Agent constructs the case-specific recipe from KI; execution records actual outputs and validation evidence |
| **5. Consuming KI step** | Which selected KI/tool reads the prepared result? Through which argument, config key, namelist or file slot? Which exact prepared path/value? What evidence is needed before this consumer starts? | Agent supplies the mapping; app resolves the actual step KI and paths; KI checks scientific suitability |

One clarification is essential: stage4 produces **prepared/model-ready artifacts**, which may differ from stage3's acquired/raw files. Carry both paths and their relation. A scalar parameter can pass directly as a value; an already valid input deck can skip conversion after the required checks. Do not force a download or invented preparation step where the KI does not need one.

### Example: existing APSIM knowledge

1. Requirement: model-compatible weather for the requested site/period.
2. Selection: user weather CSV or an actually compatible approved source; no source is assumed suitable just from its name.
3. Actual input: the selected project's bound weather file, with columns/units/scope inspected.
4. Preparation: `tools/convert_met.py` writes `.met`; `tools/build_apsimx.py` builds the case and resolves that file's absolute path.
5. Consumer: the Weather object's `FileName` in the generated `.apsimx` references the prepared `.met`.

This chain exists in the KI. Desktop's job is to preserve the selected files and consumer reference. Merely showing that a CSV was uploaded is insufficient; forcing the user to hand-author the `.apsimx` is unnecessary.

### Example: imported ArchDam RDC, with no DB dependency

The imported KI explicitly requires `profile_points.csv`, `measurements.csv`, `comparison_pairs.csv`, and `regions.csv`; exact columns are in `docs/input_file_contracts.yaml`. Its `archdam_rdc/config.py` merges supplied configuration with `DEFAULT_CONFIG` and resolves relative input paths against the configuration directory. Its pipeline validates these files and records their hashes.

The project table can therefore record:

- Requirement: radial displacement and associated geometry, uncertainty and pair design.
- Selection: the user's project measurements/geometry, plus selected configuration defaults/overrides.
- Actual inputs: the four bound CSVs and their relevant columns/IDs; not a weather database query.
- Preparation: import/validate against the KI contract; use the legacy converter only if the user's data actually has that legacy form.
- Consumer: `tools/run_diagnosis.py --config <project config> --output <project output>`, with `config.input.*` resolving the exact files the user selected.

The current canonical filter yields zero starter inventory rows for this package, even though those relationships are explicitly documented. This is a particularly clear reason to retain KI-local requirements and let the agent author the bindings.

### Controls carried across all five links

- **Applicability:** a selected process/mode changes which requirements are relevant.
- **Ownership:** user-supplied, model-default, database, upstream-generated or still unknown.
- **Evidence and status:** proposed source, actual files present, inspected, prepared and validated are distinct facts.
- **Revision:** a changed selection/scope/file identifies the affected downstream preparation/consumer; it does not silently reuse stale results.
- **Provenance:** cite the KI document/tool and source/default origin used to make the mapping. Unknown information is not filled with invented facts.
- **Consent:** keep the existing plan review. Explanation is not selection or approval; calibration trials inside approved bounds do not need a new approval each time.

## 6. How the agent should interact with the table

The table should not be a screenshot or a disconnected frontend checklist. It is a view of the same structured project record available to the agent and used for execution.

1. Desktop gathers available KI declarations, existing project files and saved user choices without discarding noncanonical inputs.
2. The agent reads the KI's relevant instructions/tools and refines that starter into the five-link project mapping. It can group parameter sets, add a missing requirement, identify conditional inputs and explain unresolved alternatives.
3. The user inspects the table, asks questions and selects sources/values/files. Each change updates the draft record and carries a revision.
4. Desktop supplies the current record to the next agent turn, including exact actual paths and preserved choices. A stale agent proposal cannot overwrite a newer user selection unnoticed.
5. After approval, acquisition/preparation results fill host-owned evidence against the approved intent; they do not silently edit the signed plan. The consumer resolves the current valid files through its own KI-specific configuration.

Existing KIs need not have a machine-readable schema for every coefficient. An agent can extract a supported default from a table or tool and record its provenance. Frameworks may require an explicitly allowed discovery step before later input details can be populated. The host's checks should be narrow and deterministic—valid references, permitted paths, matching revisions, real artifacts and consistent selections—not an attempted replacement for scientific interpretation.

The flow is a graph presented as rows: several requirements can share one input deck, several datasets can produce one prepared file, and one raw source can feed different model-specific files. Do not merge those consumer bindings merely because the scientific quantity has the same canonical name.

## 7. What regression tests mean here

They test changes to **Desktop's handoff**, not whether already-validated science should be trusted again.

Examples:

- A filename is sanitized during upload. Does the plan/agent receive the actual saved filename?
- Two KIs use different output directories. Does preparing KI B leave KI A's paths intact?
- The user chooses CMFD. Do the displayed choice, stored selection and preparation input agree?
- The user replaces a parameter file. Does the next permitted step consume that file rather than an old default?

These checks use disposable small files/fake KI fixtures and finish in seconds. They need neither a provider key nor a long scientific model run. The term “regression” simply means ensuring a later code change does not reintroduce an already-fixed handoff error.

This pre-evaluation itself used content reading and actual parser calls. It did not perform these scientific model runs, certify installation status, or prove end-to-end live agent behaviour.

## 8. Resulting implementation direction

Refine the earlier project-input plan in this order:

1. **Preserve every KI-local requirement.** Treat canonical IDs as optional search/coupling aids. Use stage docs/format specs/protocols with explicit source-conflict handling; allow runtime-discovered requirements.
2. **Let the agent produce the five-link mapping.** Reuse scientific knowledge and tools already present, with editable values and source citations. Do not demand a library-wide rewrite before it can work.
3. **Make actual bindings reliable.** Fix the already reproduced upload-to-inventory and per-KI config ownership issues; preserve exact source/prepared/consumer references.
4. **Present one clear table.** Data candidates appear under relevant rows; parameter defaults/overrides and mixed-file fields expand in place; full lists remain accessible. No DB token is required for local/user-input workflows.
5. **Verify the handoff on representative shapes.** Own-file ArchDam; default/override SUMMA or CRHM; mixed-deck APEX; multi-model VIC→CaMa; framework PyMT; a deliberate metadata-conflict case. This tests generality without rerunning every model's science.

The codebase-design skill informed the decision to align existing readers and expose one input interface, rather than adding another independent planner or path registry.

## 9. Snapshot differences and reproducibility limits

The last-activated snapshot differs in inspected description files for BIOME_BGC, CLM5___CTSM, ELM, FATES, GIFMod, LDNDC, MONICA, OpenHydroQual, TOPMODEL, dfnWorks and icepack. Identical parser totals do not establish semantic equivalence. Per-package description hashes and roots are retained in the JSON. Local audit artifacts contain local filesystem paths; review/redact them before publishing externally.

No server source, hosted scientific validation records or installed runtime health was independently verified. The imported ArchDam KI's own domain is structural monitoring; the numerical census includes the current Observatory's heuristic classification only, which is not an authoritative scientific taxonomy. Stage-parser absence, no typed defaults, or no ordinary starter inventory is not a scientific fail verdict.
