# EF5's dag.yaml was HYPE's — quarantined, not repaired

The file now beside this note (`dag.yaml.WRONG-MODEL-HYPE`) is HYPE's model
descriptor, not EF5's. Evidence: its 14 process names are identical to HYPE's
(`NPC_SoilProcesses`, `MAINDOWN`, `ilake`/`olake`, glacier classes — HYPE
internals), and `identity` describes SMHI HYPE 5.35.0. EF5 is the Ensemble
Framework For Flash Flood Forecasting (NASA SPoRT / OU), built on CREST and
SAC-SMA with kinematic-wave routing; it has none of those processes.

EF5's own SKILL.md documented this before the app did, including that earlier
streamflow comparisons passed only because `cout` happens to name channel
discharge in HYPE too — "by luck", in its words.

It is quarantined rather than rewritten because a dag is a claim about what a
model computes. Writing a plausible EF5 dag by hand would be the substitution
the KI execution policy exists to forbid. A genuine one has to come from the
dissection pipeline, from EF5's own source and documentation.

Consequences while it is absent: EF5 has SKILL.md, tools and diagnostics, so it
remains usable by an agent reading its protocol; what it loses is the
machine-readable I/O contract, which nothing should have been trusting anyway.
