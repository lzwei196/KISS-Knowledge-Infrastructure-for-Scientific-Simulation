# Test inputs for the 127 GeoForge KIs

Date: 2026-10-04. Development work; not a release certification.

Every shipped KI needs at least one named, reproducible example with its complete
input set available. Shipping the KI instructions, a converter or a successful
`--help` command does not meet this requirement. A test pack can be bundled with
the release or distributed separately through Baidu Netdisk, with a versioned
manifest and an authenticated catalogue entry.

The current [127-KI test matrix](audits/ki-test-inputs-2026-10-04/TEST-MATRIX.md)
and [machine-readable inventory](audits/ki-test-inputs-2026-10-04/inventory.json)
record local declarations and candidate files. They do **not** certify those
files as complete packs or turn historical reports into fresh test passes.
Regenerate the inventory with `python tools/audit_ki_test_inputs.py --help` for
the supported options. Run it against the exact library included in a release.

## Delivery for this test round

Use existing verified local files first. Otherwise prefer a versioned Baidu
Netdisk test pack or exact resolver-returned delivery files. Do not automatically
replace this choice with a server clip. Clipping remains a separately selected
route for a later request that needs it.

Desktop's development implementation records this preference as
`delivery_preference: "manual"` on `runs/data-inventory.json`, or on an individual
item. An explicit item preference overrides the inventory default; `"auto"`
retains the existing delivery behavior. This is a delivery choice, not a change
to the selected source, variables, period, spatial coverage or required cadence.

The agent must select real catalogue/resolver IDs. An unresolved national product
is not a downloadable test pack: resolve its actual variable/year files or select
a published regional/case pack. Show the total size, full delivery extent and
local extraction work. If the selected record has no manual route, report that
gap instead of inventing a Netdisk link or silently using a clip.

The existing manual workflow shows the link, extraction code, exact share member
and target directory privately to the user after plan approval. The user places
the files and chooses **Files are in place, continue**. Desktop hashes the placed
files; the KI then checks their contents and prepares the model inputs. Hashing
files that happen to be present does not prove that all required files arrived.
The pack's expected file manifest supplies that separate check.

## Minimum test list for each KI

| Test | Required evidence |
|---|---|
| Install | Exact KI and shared-tools revision; selected implementation, mode and engine version; clean installation/preflight log. `--help` is only a probe. |
| Obtain inputs | Versioned pack ID; expected member names, sizes and SHA-256; clean extraction with every required member present. Netdisk download and cached/local import are separate recorded routes. |
| Inspect inputs | Actual variables, units, coordinates, calendar, native cadence, requested period and warm-up/padding; static, initial, boundary and parameter files appropriate to the selected case. |
| Prepare | Exact KI tool and arguments; raw-to-native file mapping; actual checks on prepared files. Prepared packs must not be converted a second time accidentally. |
| Run | Real selected engine in a fresh case directory; command, exit code, timeout, stdout/stderr and produced files. |
| Check outputs | Expected time/cell counts, finite values, reference results and model-specific tolerances or balance checks. A zero exit code alone is insufficient. |
| Reject bad input | At least one missing required member and one incompatible date/unit/cadence case fail clearly before a misleading result is reported. |
| New site | Repeat delivery, preparation and engine execution for a site/period outside the reference case. Keep this result separate from the supplied example. |
| Calibration, where supported | Observation provenance, units/time alignment, objective function, parameter bounds, an actual trial and independent validation period. A native example is not a calibration test. |

Record `NOT_RUN`, `BLOCKED`, `FAIL` or `PASS` with evidence for each executed case
and each stage. Use `NOT_APPLICABLE` only with a case-specific explanation. A
framework KI such as BMI, PyMT or ESMF must name the selected component and its
inputs; an empty forcing declaration is not evidence that a runnable case needs
no input.

## What must be in a pack

Use one small complete reference case per KI/mode, with relative paths. Several
KIs may share one immutable raw source pack, but each needs its own preparation
recipe, native input mapping and expected outputs. Avoid duplicating a whole
national archive across 127 folders.

Each pack manifest must include:

- A stable pack ID and version, KI name, selected mode, KI/shared-tools revisions
  and engine identity. Scientific version labels alone do not identify the code.
- Source provenance, citation, licence/redistribution terms and retrieval date.
- Site/grid, simulation and spin-up dates, padding, calendar/time zone, variables,
  units and native cadence. Any resampling or time disaggregation is explicit.
- Every required member's relative path, byte size, SHA-256 and role; dependencies
  on other packs by immutable ID/hash. Do not include local secrets or share codes.
- Raw versus prepared status, a portable staging recipe, preparation/run commands
  and expected output checks with defensible tolerances.
- A public metadata/catalogue ID. Resolve private Netdisk URLs and codes through
  the existing authenticated delivery route, not a public README.

Not every KI uses weather. Routing KIs need runoff and network mappings; EPANET
needs a network and demands; PHREEQC needs chemistry and a thermodynamic database;
WRF needs atmospheric initial/boundary fields; geophysical KIs need surveys and
meshes. The consuming KI tool/mode decides the input contract.

## First three cases and new-site work

| KI | Reference pack target | Separate new-site test |
|---|---|---|
| SHAW | Vendor Trial weather, site, control, moisture and temperature files | Hailun daily CMFD or explicitly selected genuine hourly source; check timestep flags, padding and profile coverage. |
| CRHM | Bad Lake project, authentic observations and parameter/module configuration | Nenjiang hourly source, HRUs and model configuration; verify cadence, headers and full simulation coverage. |
| VIC | Official Stehekin 10-day case, 16-cell forcing, soil, vegetation, snowbands and control | Requested Huaihe grid, spin-up and simulation forcing, complete soil parameters and vegetation mapping. |

Local reference-pack creation and native replay evidence is recorded separately
in [the reference-pack results](audits/ki-test-inputs-2026-10-04/REFERENCE-PACK-RESULTS.md)
from the declaration inventory. A successful supplied example does not resolve
the known new-site preparation issues or verify live Netdisk delivery.

For the current new-site cases, keep these issues visible: the reported CMFD
source is genuinely three-hourly; returned full-year weather must not be mistaken
for exact requested-period output; VIC still needs the complete soil prerequisite;
and authenticated preparation/delivery must be replayed from Desktop. Netdisk can
bypass server clipping, but cannot repair incompatible source data or missing
scientific inputs.

## Server/library handoff

Build a catalogue of input packs covering the 127 inventory rows. Start with the
three named reference cases, then prepare a complete example for each remaining
KI. Return pack IDs, immutable manifests and actual preparation/run evidence;
leave unresolved cases explicit. Register actual Netdisk delivery members through
the existing authenticated service. Preserve native filenames or supply a tested
mapping that the KI loader consumes. A link to a general archive is not a
per-case delivery contract.

Release acceptance requires matching the release library to the inventory, a
complete input pack for every promised example, and fresh recorded stage results
on each advertised operating system. The current inventory is the work list;
it is not evidence that these acceptance conditions have been met.

## Local implementation checks

The combined Desktop regression run passed **356 tests**, with one existing
POSIX-permissions test skipped on Windows. It covers the manual preference,
rejection of unexpected binary delivery before payload reading, raw acquisition,
preparation estimates, Database gating, approval/recovery, UI rendering and the
pack manifest verifier. HTTP fixtures are simulated; these are separate from
the three real native reference replays above.

The inventory was checked against the actual production catalogue: exactly 127
unique names, all present once in the readable matrix, with ten required stages
and conditional calibration. Its heuristic found 42 candidate files across eight
KIs in this checkout; it cannot certify completeness or conclude that other KIs
lack examples available elsewhere. The three newly staged packs are outside the
shipped library and therefore remain separate evidence.

Code and documentation remain local development changes. The installed Desktop
and the published Windows release have not been replaced by this work.

## 中文简述

每个随 GeoForge 发布的 KI，至少应有一个可复现的完整示例：不仅有工具和说明，
还要有驱动数据、参数、初始/边界条件、配置、运行命令和结果检查。
本轮优先使用已有的已核验文件或百度网盘数据包，不自动改成服务器裁剪。
网盘解决的是文件交付；下载后仍要核对文件清单、校验值、日期、变量、单位和时间步长，
再由对应 KI 的工具处理和运行。

127 项清单中的“发现候选文件”不等于“数据齐全”，“安装成功”不等于“模型跑通”。
SHAW、CRHM、VIC 先整理标准示例数据包，再分别完成新地点测试。
每项保留未运行、阻塞、失败或通过的证据，不把标准示例通过当作新地点通过。
