# Shared KI draft enforcement — 2026-10-06

GeoForge owns the acceptance policy for every CLI and direct API provider:
draft edits do not acquire authority from the provider's final response.

## Implemented boundary

- KI Studio, ZIP import and changed/new library KIs use the actual installed KDT
  structural verifier and the Desktop package checker. Candidate preflight code
  is statically checked; structural verification runs only a host-generated
  deferred preflight, never the candidate's untrusted native model commands.
- Host signatures bind the full candidate content, gate policy and actual KDT
  verifier source. Acceptance records live outside authoring workspaces. A changed
  file, forged report or altered verifier cannot retain acceptance.
- Activation checks the copied candidate again. Studio exports the exact verified
  projection. Missing or modified KDT installations produce an actionable refusal;
  the current active library remains available.
- Active source and working KI baselines are stored by the host. A single signed
  host inventory records existing installed versions as legacy baselines, not
  newly KDT-verified or scientifically verified versions. A new `--models` folder
  cannot restart migration: its contents need exact recorded legacy provenance
  or current KDT acceptance. Ordinary setup writes cannot edit an active KI.
- The shared CLI runner, direct API tools, native tool dispatcher and software
  preflight check active KI integrity. Changed files cannot be counted as current
  software-ready evidence. Installation metadata stays beside the KI rather than
  rewriting its contents on every status update.
- Library readiness rechecks canonical and installed KI integrity. Old successful
  reports without exact revision evidence remain history and request a recheck;
  status reads never enroll files or modify those reports. Installation-recipe
  agents use the same protected roots for both CLI and API providers.

## What the gate proves

`Verified` here means the exact package passed structural checks. Native software
verification and reference-case/scientific acceptance remain separate evidence.
Reports explicitly record native regression as not run by the structural gate.
No SHAW, CRHM or VIC scientific result is changed or newly certified by this work.

This is a host integrity and acceptance boundary. Vendor CLI processes running
with the user's operating-system permissions are not an OS sandbox. File drift
is detected and blocked; arbitrary same-user filesystem writes cannot honestly
be described as impossible. Preservation does not imply that an unknown
background child process has stopped.

The project investigation workflow now uses this gate. Open **Investigate KI**
in any project and describe the issue. Three independent conversations inspect
the same frozen evidence packet, covering runtime contracts, scientific data,
and reproducibility. Complete transcripts and selected KI/helper text are
available in that packet; credentials are redacted and binary or oversized
files are explicitly inventoried rather than silently treated as read evidence.
The three reports and combined findings remain analysis, not scientific proof.

After all three reviewers finish, choose **Create repair draft**, **Build repair
with agent**, and **Verify with KDT**. Edits target a separate candidate seeded
with the exact materialized project KI. **Apply repair and continue** requires
the current host verification ID, unchanged evidence and an idle project. It
adopts only the project-local KI, preserves prior revisions, revokes the old
approval, and returns to plan review. The revised project's actual preflight
and declared dependencies must pass before execution. No global library update
or scientific-criteria relaxation is implicit.
If that preflight fails, the agent receives the actual diagnostic in an
installation-only setup turn using the existing project bindings. The host
checks again afterwards; a provider's success claim cannot clear the gate.

中文：在项目中打开 **排查 KI**，描述问题，启动三方独立审查。三位审查者使用同一份冻结的
项目证据，分别检查 KI 与运行环境、数据与科学解释、可复现性与修复风险。三份报告完成后，
依次选择 **创建修复草稿 → 让 Agent 编写修复 → 用 KDT 验证 → 应用修复并继续**。
应用后必须重新审核计划，并检查修复后的项目 KI 及其依赖。历史失败和旧结果保留在记录中，
不会作为新版本的执行许可。结构验证通过并不代表模型或科学验证通过。

All configured API connections use host-owned evidence read tools. Claude Code
and Codex use checked CLI profiles; unsupported CLI versions/providers report
the limitation and require an explicit connection choice. No provider is
silently substituted. The common edit/adoption gate still applies to every
provider. Codex CLI read-only mode does not restrict all reads or arbitrary shell
commands to the evidence folder; its limitation is recorded with each report.

Repair adoption starts fresh provider memory while retaining the full transcript
and reports. A signed repair generation recovers that handoff after a crash.
Interrupted authoring preserves its draft; interrupted adoption requires
recovery and is never automatically retried. Reviewer citations are checked
against files actually read by API reviewers, with two bounded opportunities
to correct an invalid report before it is marked incomplete.

## Validation

The focused suites exercise authentic host hashing/signatures with controlled
KDT test engines, failed/missing gates, post-check changes, forged reports,
Windows preflight handling, every configured CLI provider and setup/API paths.
Those controlled engines are test doubles; they do not prove that a scientific
model or a live provider has run.

GUI checks used the real reviewed KDT engine at commit
`631e5c50cb0cd812447f67358dd9c162658155ea`:

- The existing SWAT+ Studio candidate passed KDT and Desktop structure checks.
  Report `fe141a5f6d4b4cc2` enabled Import for that exact revision. No import or
  native SWAT+ run was performed.
- Reopening the candidate for editing invalidated its previous report and
  disabled Import. The stale state survived a GeoForge restart; another real
  verification was required to enable Import again.
- A validate-only ZIP of the shipped HYDAT data KI was refused for three KDT
  format requirements: the opening execution policy, at least three stage
  documents and `diagnostics/triplets.yaml`. The library stayed at 129 entries.
  This is a package-format gap for a future import/update, not evidence that the
  existing HYDAT reader or database fails. Legacy baselines remain available.
- The previously modified KDT checkout was replaced through Studio's Repair
  control, with the old checkout preserved in a `.replaced-*` directory.
- The final build restarted with all 129 catalogue entries. The CRHM Library view
  retained the successful check from 15:27 and displayed `Recheck KI revision`,
  with its original preflight steps still visible. The SWAT+ structural report
  remained current after restart. No scientific model was rerun for these checks.

Final full Desktop regression (`python -m pytest kiss/tests -q`) passed:
**2,341 passed, 35 skipped, 352 subtests passed**, exit code 0, in 472.63 seconds.
The skips cover platform-specific fixtures and unavailable server-copy parity;
they are not claimed as tested. All 339 fingerprinted Desktop source, test and
shared-helper files were unchanged during the run. `git diff --check` passed.

Local evidence is retained in `D:/GeoForge-Release-Checks-20261006/`:
`ki-gate-final-desktop.log`, `ki-gate-final-desktop.xml` and
`ki-gate-final-source-stability.json`. This is a tested source change, not a new
Windows installer release.

## Investigation validation

The new tests cover independent API conversations, supported CLI arguments,
missing/unread citations, cancellation, protected KI drift, signed records,
exact verification IDs, changed-file accounting, adoption and recovery,
approval revocation, preserved transcripts and fresh provider memory. API and
CLI setup fixtures check a failing repaired-KI preflight reaching one bounded
dependency-repair turn, with execution allowed only after the host recheck.
These provider/native fixtures are test doubles, not live scientific runs.

Live GUI testing used the completed CRHM BadLake project and DeepSeek API.
Investigation `e05757edbb314d93` retained a partial 1/3 report because two
reviewers supplied invalid evidence citations. After bounded citation correction
was added, `c68c88f8591d4065` completed all three independent reports from the
same frozen context. The context includes the project's complete transcript;
raw binary and oversized files remain explicitly inventoried omissions.

The first draft-authoring attempt reached its turn limit and was correctly kept
incomplete. It also exposed KDT's new-package source mapper overwriting parts
of an existing candidate. Repair probes now direct generated scaffolding into
a separate temporary output directory and check that the seeded candidate's
bytes remain unchanged. Normal new-package probing keeps its existing behavior.
Budget warnings and an explicit final-report turn let an author finish a bounded
repair without an endless rereading loop; incomplete reports still cannot pass.

The author retry completed with a retained report. Real KDT verification rejected
the draft, and Apply stayed disabled. The first report exposed a Windows-only
path spelling mismatch in KDT's public tool index: the pinned helper returned
backslashes while the KI index used portable slashes. The host now gives the
loaded verifier a private helper view that normalizes those relative paths;
the unchanged exact-path comparison still rejects a genuinely missing tool.
Neither the pinned engine nor candidate files are rewritten. The new gate policy
requires fresh verification of older acceptance records.

The draft also has genuine package requirements to resolve: missing
`docs/gathered_papers.json` and an unclassified machine-specific binary path.
Those failures remain blocking. Verification can be retried directly from the
GUI without a paid authoring turn. An author retry receives the previous host
KDT failure report. The active project KI has not been replaced, and no new
scientific execution or calibration pass is claimed by this investigation.
After restarting the final build, GUI verification `d94b8a8af7ba4ffa` recognized
all 16 indexed tools and retained both real package failures, with the same
candidate digest as before the Windows fix. Apply remained disabled.

Final review also strengthened packet redaction for quoted, multiword secrets,
cookie headers and authorization values. After an accepted repair, the host
releases the project operation only after adoption and session memory are saved,
but before sending the response that starts the next chat turn.

Final investigation-build regression passed: **2,522 tests passed, 35 skipped,
356 subtests passed**, exit code 0, in 513.73 seconds. All 346 fingerprinted
Python, HTML, JavaScript and JSON source/test files stayed unchanged throughout
the run. The 35 skips cover POSIX-specific behavior and the absent server-copy
parity fixture. Evidence: `investigation-stable-desktop.log`,
`investigation-stable-desktop.xml`, and
`investigation-stable-desktop-source-stability.json` in the local evidence folder
above. `git diff --cached --check` passed. Apply/recovery and provider setup are
covered by controlled regression fixtures; the live CRHM GUI check stops at its
real rejected draft, without applying it. This build is a local source commit,
not an uploaded Windows installer release.
