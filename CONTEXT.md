# GeoForge project language

These terms distinguish project consent, execution, acquired data and scientific evidence.

## Language

### Data acquisition

**Data request**:
A project's stated need for a particular data source and scope, including the relevant area, period and variables.
_Avoid_: Dataset name alone, download folder

**Acquired input**:
Data files obtained for a project, whether downloaded automatically or supplied manually. Acquisition alone does not establish suitability for a model.
_Avoid_: Scientifically validated input, ready-to-run input

**Acquisition receipt**:
A record associating acquired files with their source and request, including evidence for detecting subsequent file changes.
_Avoid_: Scientific validation report

**Acquired-input evidence**:
The records and file checks supporting a conclusion about an acquired input's integrity and relationship to the current data request. It does not by itself establish scientific suitability or source freshness.
_Avoid_: Files present, scientific proof

**Reusable input**:
A previously acquired input whose evidence supports using it for the current data request without obtaining the same data again. Reusability does not imply that model preparation or scientific validation is complete.
_Avoid_: Any existing dataset folder

**Scientific validation**:
An assessment of whether prepared inputs or results meet the project's stated scientific checks, informed by the relevant KI. It is distinct from evidence that files were acquired and remain unchanged.
_Avoid_: Download complete, checksum match

**Source freshness**:
Whether the acquired data corresponds to the version currently offered by its source. Intact local files do not establish that the source is unchanged.
_Avoid_: File integrity

### Plan and execution

**Plan approval**:
Consent to a particular project plan and its selected data, given through the application's review process. It is not a scientific validation result or a separate consent interaction for every tool invocation.
_Avoid_: KI usage instructions, scientific acceptance

**Approved step**:
A step covered by a currently valid plan approval. Approval does not establish that the step has run or that its outputs meet scientific checks.
_Avoid_: Completed step, validated result

**Issued review**:
The host's persisted record of the plan, inventory and display presented for approval, including the offered choices and preselected recommendations. A later click is checked against this record, not a rebuilt catalogue view.
_Avoid_: Current plan alone, agent-written review marker

**Saved user answer**:
A host-recorded choice the user made from an issued review, bound to its choice and, where relevant, input item. Returning an unchanged preselected recommendation is acceptance of that recommendation, not evidence of a deliberate changed choice.
_Avoid_: Agent-supplied provenance, every submitted radio value

**Execution attempt**:
One invocation of a KI tool for a project step, which may succeed, fail or be interrupted. An agent's conversational reply is not an execution attempt.
_Avoid_: Agent reply, successful simulation

**Execution receipt**:
A record of an execution attempt and its observed outcome and evidence. Having a receipt does not by itself mean the attempt passed scientific validation.
_Avoid_: Success certificate

### Status observations

**Project status projection**:
A read-only interpretation of current Flow, request, acquisition and execution evidence for display. It may identify the next actor but does not grant permissions, move Flow or start work.
_Avoid_: Another state machine, execution authority

**Activity observation**:
An observed provider event, process signal, output or file change with its source and age. An active provider connection alone does not prove that a scientific model is progressing.
_Avoid_: Model progress, completed scientific work

**Present but unverified**:
Files exist locally, but their presence alone does not establish a correctly bound acquisition or scientific suitability.
_Avoid_: Ready-to-use data, validated input
