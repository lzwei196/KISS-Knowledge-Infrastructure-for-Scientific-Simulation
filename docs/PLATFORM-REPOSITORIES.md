# GeoForge Desktop platform repositories

Migration date: 2026-10-01.

## Ownership

| Repository | Responsibility | Original source branch / commit |
|---|---|---|
| [GeoForge-Desktop-macOS](https://github.com/lzwei196/GeoForge-Desktop-macOS) | macOS application, dependencies, packaging, releases | `mac-version` / `ee1387abaac3b4a6c6d71499e2f4ed8fa188cfc8` |
| [GeoForge-Desktop-Windows](https://github.com/lzwei196/GeoForge-Desktop-Windows) | Windows application, dependencies, packaging, releases | `windows-version` / `96409ba3bcbf64322ca7a8eba4ba8e2bf32df535` |
| [GeoForge-Desktop-Linux](https://github.com/lzwei196/GeoForge-Desktop-Linux) | Linux application, dependencies, packaging, releases | `linux-version` / `5938dbc5ace75b133b4399744797d2eda716fcf0` |
| KISS (this repository), `main` | Canonical model KI packages, shared Harness, scientific knowledge | Unchanged ownership |

Each new platform repository has its own `main` branch. Its initial source retains
the corresponding platform branch's Git ancestry, followed by migration changes.
The three branches already differ in behavior as well as dependencies: this is
not a claim of feature parity. Do not replace Windows or Linux with a macOS copy.

The original platform branches and source tags in KISS are retained as historical
references, not deleted. Desktop release workflows in KISS have been removed;
future native builds and publication belong in the platform repository.

## KI and Harness updates

Keep the shared KI source pointed at KISS `main`. Platform packaging can pin a
tested shared-library revision, but independent OS repositories are not new
authoritative KI catalogues. Bundled snapshots and model install manifests remain
in the migrated source trees because current build specifications require them.
No automatic shared-code synchronization or cross-platform parity is implied.

## Historical releases

Historical installers are copied byte-for-byte to the applicable platform
repository with their original release notes, prerelease/draft state, and asset
SHA-256 checks. Mixed-platform releases are split by asset platform. Supporting
manuals, KI archives, and original manifests/checksum files are retained unchanged;
an original checksum list can therefore mention another platform's assets.

Each destination release receives a separate migration manifest identifying its
source release ID, source tag/commit, exact copied asset names, sizes, and hashes.
This manifest describes migration integrity, **not** renewed scientific or native
build validation. The GitHub publication date changes during migration; original
dates are retained in the release note and migration manifest.

An empty historical draft with a tag that also has a published release uses an
`-archived-draft-<source-id>` suffix to avoid a collision. A draft without an original
Git tag explicitly states that its archive tag is not verified binary provenance.
The KI-only `v0.6.50` archive contains no Desktop installer and remains labeled as
such in the macOS historical archive.

Old binaries hardcode KISS's `v0.2.0/kiss-ki-packages.tar.gz` for first-run fallback.
Retain that one **KI-only compatibility release**, with no Desktop installers,
unless intentionally retiring those clients. New platform locations cannot redirect
an old binary's hardcoded URL. All other Desktop release entries can be removed
from KISS only after every archive asset has been verified at its destination.

## Next releases

Prepare release metadata and run the platform's native build/tests in its own
repository. Publish only that platform's installers. A successful source migration
or SHA-256 comparison does not prove the latest source has been compiled or that
Windows/Linux builds pass on macOS. Never overwrite an archived release with a
new binary under the same tag.
