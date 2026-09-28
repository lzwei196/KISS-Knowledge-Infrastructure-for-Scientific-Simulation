# AquaCrop scope options and DB gating — investigation

Status: confirmed source/test findings; **not fixed** in the September 28 planner test build or branch checkpoint. The user asked to push the existing improved version while these issues remain open.

## User-visible symptom

A DeepSeek/AquaCrop conversation about soybean near Harbin offered “2000–2018 multi-year, validated vs FAOSTAT China soybean” as one scope choice. The user asked why the period was restricted and requested that GeoForge-specific dataset options depend on database activation, while the conversation remains question-by-question.

Read-only inspection confirmed the recorded option/answer and `database_access_mode: direct` in current settings. The visible first assistant message contains KI reads but no catalogue-search marker before the scope question; later turns contain catalogue and describe tool markers. Markers alone do not establish successful tool results or historical activation status.

## Period and observation scope

- `models/AquaCrop/SKILL.md:493–501` presents 2000–2018 as an example for China **maize** at 34 N, 113 E, explicitly saying to use forcing/observation overlap. It is not an AquaCrop-wide date constraint.
- The validated 2000–2018 calibration at lines 581–591 is also mainland China maize, not Harbin soybean. The KI supports soybean, but that does not transfer example validation to a new crop/site.
- The model assembly interface accepts start/end dates. The separate national-yield tool uses a different default period and a bounded-length operational cap; neither establishes 2000–2018 as the only possible scope.
- FAOSTAT selection in the shared crop observation helper is by country/crop/year. China soybean statistics are national observations, not Harbin field measurements.

The evidence strongly points to an example being promoted into a project recommendation. It does not show that the model or database cannot serve other years. The UI wording also conflates a proposed future comparison with a previously validated setup.

## Database gate reproduction

An isolated synthetic case, through real plan submission and final review, sets DB access off:

- DB tools are omitted, direct `search_catalogue` calls are rejected, and the prompt says DB access is disabled.
- Nevertheless, `flowrun.after` stamps catalogue inputs and `plan_review._data_choices` loads matching cached catalogue records and renders DB alternatives.
- The setting defaults to `direct`; activation/token state is not what currently selects this mode.

Already run twice, no credentials/network/providers:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/geoforge-db-off-audit.q9EMGs/reproduce.py
```

The reproduction exits 1 on its expected DB-off invariant. This establishes a **final-review gate gap**, not that it caused the user's earlier generic scope question. FAOSTAT is also mentioned in the KI as a public-source method, so merely naming FAOSTAT does not prove GeoForge DB access.

## Expected follow-up

1. Ask for the simulation period as its own decision, allowing user dates and explaining any proposed range using actual coverage—not copying an example as a hard limit.
2. Ask separately whether/how the user wants validation, distinguishing field observations, gridded/regional products, national statistics and no observational comparison yet.
3. Offer GeoForge DB records only through the effective enabled/authorized database path. Preserve public-source and user-file alternatives without portraying them as authenticated GeoForge access.
4. Apply the same gate to prompts, tools, finalization and rendered review; an old local cache must not reactivate a disabled integration.
5. Preserve explicit approval: answering one planning question must not authorize a simulation or replace final plan review.

The deterministic answer/approval tests passed (57 cases in the targeted run), but they do not certify scientific recommendations or all questions in the user's live conversation. No running user session was changed or restarted during this inspection.
