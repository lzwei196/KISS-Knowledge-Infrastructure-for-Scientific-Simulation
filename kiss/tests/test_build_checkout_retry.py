"""Real local-Git checkout fixtures; no network, compilers or model processes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from kiss_cli import install
from kiss_cli.manifest import Acquire, Manifest


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="local Git is required")


def git(root, *args, input=None, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test"},
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip() if check else result


@pytest.fixture
def upstream(tmp_path):
    root = tmp_path / "upstream"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    (root / "source.f90").write_text("program fixture\nend program\n", encoding="utf-8")
    (root / "config.mk").write_text("COMPILER=fixture\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    git(root, "tag", "v1")
    return root


@pytest.fixture
def built(monkeypatch):
    calls = []
    original = install._run

    def run(command, **kwargs):
        if command == "fixture-build":
            calls.append(Path(kwargs["cwd"]))
            return 0, "fixture build boundary reached; no compiler launched"
        return original(command, **kwargs)

    monkeypatch.setattr(install, "_run", run)
    return calls


def manifest(upstream, ref="v1"):
    return Manifest(model="fixture", acquire=Acquire(
        strategy="build", repo=str(upstream), ref=ref, commands=["fixture-build"]))


def clone(upstream, tmp_path, ref="v1"):
    target = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", "--branch", ref, str(upstream), str(target))
    return target


def acquire(man, target):
    return install._acq_build(man, target, sys.executable)[0]


def test_fresh_clone_is_checked_before_build(upstream, tmp_path, built):
    target = tmp_path / "fresh"
    step = acquire(manifest(upstream), target)
    assert step.ok, step.detail
    assert built == [target]
    source = step.evidence["source_checkout"]
    assert source["resolved_commit"] == git(upstream, "rev-parse", "HEAD")
    assert source["tracked_files"] == 2
    assert source["tracked_changes"] == []


def test_unicode_and_space_tracked_source_paths_are_read_exactly(upstream, tmp_path, built):
    (upstream / "土壤 输入.f90").write_text("fixture\n", encoding="utf-8")
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "Unicode source filename")
    target = clone(upstream, tmp_path, ref="main")
    step = acquire(manifest(upstream, "main"), target)
    assert step.ok, step.detail
    assert step.evidence["source_checkout"]["tracked_files"] == 3


def test_existing_checkout_allows_generated_and_ignored_files(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    (target / "build").mkdir()
    artifact = target / "build" / "generated.o"
    artifact.write_bytes(b"generated artifact")
    (target / ".git" / "info" / "exclude").write_text("build/\n", encoding="utf-8")
    (target / "untracked.log").write_text("prior build log", encoding="utf-8")
    step = acquire(manifest(upstream), target)
    assert step.ok, step.detail
    assert built == [target]
    assert artifact.read_bytes() == b"generated artifact"
    assert step.evidence["source_checkout"]["tracked_changes"] == []


@pytest.mark.parametrize("staged", [False, True])
def test_local_portability_patch_is_preserved_and_reported(upstream, tmp_path, built, staged):
    target = clone(upstream, tmp_path)
    patch = "COMPILER=local-portability-patch\n"
    (target / "config.mk").write_text(patch, encoding="utf-8")
    if staged:
        git(target, "add", "config.mk")
    before_index = (target / ".git" / "index").read_bytes()
    step = acquire(manifest(upstream), target)
    assert step.ok, step.detail
    assert built == [target]
    assert (target / "config.mk").read_text(encoding="utf-8") == patch
    assert (target / ".git" / "index").read_bytes() == before_index
    assert "not a pristine-source build" in step.detail
    changes = step.evidence["source_checkout"]["tracked_changes"]
    assert changes == [{"status": "M " if staged else " M", "path": "config.mk"}]


@pytest.mark.parametrize("flag", [None, "--skip-worktree", "--assume-unchanged"])
def test_missing_head_source_never_hidden_by_index_flags(upstream, tmp_path, built, flag):
    target = clone(upstream, tmp_path)
    if flag:
        git(target, "update-index", flag, "source.f90")
    (target / "source.f90").unlink()
    step = acquire(manifest(upstream), target)
    assert not step.ok
    assert "checkout is incomplete" in step.detail
    assert "source.f90" in step.detail
    assert not built
    assert (target / ".git").is_dir()
    assert not (target / "source.f90").exists()


def test_failed_clone_with_surviving_git_is_rechecked_on_retry(upstream, tmp_path, built, monkeypatch):
    target = tmp_path / "partial"
    real = install._run
    interrupted = False

    def failed_checkout(command, **kwargs):
        nonlocal interrupted
        # A tag ref is fetched explicitly and populated by read-tree, not clone.
        if isinstance(command, list) and (command[:2] == ["git", "clone"] or "read-tree" in command):
            rc, out = real(command, **kwargs)
            assert rc == 0, out
            (target / "source.f90").unlink()
            interrupted = True
            return 1, "checkout interrupted after .git was created"
        return real(command, **kwargs)

    monkeypatch.setattr(install, "_run", failed_checkout)
    first = acquire(manifest(upstream), target)
    assert interrupted and not first.ok and (target / ".git").is_dir()
    second = acquire(manifest(upstream), target)
    assert not second.ok and "checkout is incomplete" in second.detail
    assert not built


@pytest.mark.skipif(os.name != "nt", reason="Windows invalid-name checkout regression")
def test_real_windows_invalid_filename_clone_failure_remains_blocked(upstream, tmp_path, built):
    blob = git(upstream, "hash-object", "-w", "--stdin", input="fixture\n")
    tree = git(upstream, "mktree", input=f"100644 blob {blob}\tinvalid:name.f90\n")
    commit = git(upstream, "commit-tree", tree, "-m", "Windows-invalid source filename")
    git(upstream, "tag", "invalid-windows", commit)
    target = tmp_path / "partial-windows"
    first = acquire(manifest(upstream, "invalid-windows"), target)
    assert not first.ok and "clone failed" in first.detail
    assert (target / ".git").is_dir()
    second = acquire(manifest(upstream, "invalid-windows"), target)
    assert not second.ok and "checkout is incomplete" in second.detail
    assert "invalid:name.f90" in second.detail
    assert not built


@pytest.mark.skipif(os.name != "nt", reason="Windows ordinary-file naming contract")
@pytest.mark.parametrize("invalid", ["source.f90:stream", "CON", "aux.f90", "COM¹.f90",
                                     "source.f90.", "source.f90 ", "source?.f90", "source\x01.f90"])
def test_windows_invalid_names_rejected_even_if_filesystem_reports_file(
        upstream, tmp_path, built, monkeypatch, invalid):
    target = clone(upstream, tmp_path)
    real = install._run

    def declared_name(command, **kwargs):
        rc, out = real(command, **kwargs)
        if isinstance(command, list) and "ls-tree" in command:
            out = out.replace("\tsource.f90\0", "\t" + invalid + "\0")
        return rc, out

    monkeypatch.setattr(install, "_run", declared_name)
    # In particular, NTFS ADS may answer is_file=True after protectNTFS was
    # disabled. A positive filesystem answer cannot admit that tracked name.
    monkeypatch.setattr(Path, "is_file", lambda _self: True)
    step = acquire(manifest(upstream), target)
    assert not step.ok and "ordinary Windows source file" in step.detail
    assert step.evidence["source_checkout"]["unrepresentable_tracked"] == [invalid]
    assert not built


def test_updated_recipe_ref_does_not_reuse_old_head(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    (upstream / "source.f90").write_text("new revision\n", encoding="utf-8")
    git(upstream, "commit", "-qam", "second")
    git(upstream, "tag", "v2")
    git(target, "fetch", "-q", "origin", "refs/tags/v2:refs/tags/v2")
    old = git(target, "rev-parse", "HEAD")
    step = acquire(manifest(upstream, "v2"), target)
    assert not step.ok and "does not match requested ref" in step.detail
    assert not built
    assert git(target, "rev-parse", "HEAD") == old
    assert (target / "source.f90").read_text(encoding="utf-8").startswith("program fixture")


def test_unavailable_ref_requires_deliberate_acquisition(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    step = acquire(manifest(upstream, "not-fetched-v2"), target)
    assert not step.ok and "unavailable" in step.detail
    assert not built
    assert not any(" fetch " in command for command in step.commands)


@pytest.mark.parametrize("ref_kind", ["full-sha", "short-sha", "annotated-tag", "branch", "unpinned"])
def test_valid_requested_ref_forms(upstream, tmp_path, built, ref_kind):
    sha = git(upstream, "rev-parse", "HEAD")
    git(upstream, "tag", "-a", "release", "-m", "annotated")
    target = clone(upstream, tmp_path, ref="main")
    ref = {"full-sha": sha, "short-sha": sha[:9], "annotated-tag": "release",
           "branch": "main", "unpinned": None}[ref_kind]
    step = acquire(manifest(upstream, ref), target)
    assert step.ok, step.detail
    assert built == [target]
    if ref is None:
        assert "does not pin" in step.evidence["source_checkout"]["ref_scope"]


def test_local_branch_commit_is_not_fetched_branch_identity(upstream, tmp_path, built):
    target = clone(upstream, tmp_path, ref="main")
    (target / "config.mk").write_text("local commit\n", encoding="utf-8")
    git(target, "commit", "-qam", "local")
    step = acquire(manifest(upstream, "main"), target)
    assert not step.ok and "does not match requested ref" in step.detail
    assert not built
    assert (target / "config.mk").read_text(encoding="utf-8") == "local commit\n"


def test_staged_deletion_with_file_still_present_blocks(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    git(target, "rm", "--cached", "source.f90")
    assert (target / "source.f90").is_file()
    step = acquire(manifest(upstream), target)
    assert not step.ok and "staged deletion" in step.detail
    assert not built
    assert (target / "source.f90").is_file()


def test_conflicted_source_blocks_before_build(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    git(target, "checkout", "-qb", "ours")
    (target / "source.f90").write_text("ours\n", encoding="utf-8")
    git(target, "commit", "-qam", "ours")
    git(target, "checkout", "-qb", "theirs", "v1")
    (target / "source.f90").write_text("theirs\n", encoding="utf-8")
    git(target, "commit", "-qam", "theirs")
    git(target, "checkout", "-q", "ours")
    assert git(target, "merge", "--no-commit", "theirs", check=False).returncode == 1
    assert git(target, "ls-files", "--unmerged")
    step = acquire(manifest(upstream, ref=None), target)
    assert not step.ok and "conflict" in step.detail
    assert not built


def test_wrong_origin_is_not_reused(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    git(target, "remote", "set-url", "origin", str(tmp_path / "other-repo"))
    step = acquire(manifest(upstream), target)
    assert not step.ok and "origin does not match" in step.detail
    assert not built


@pytest.mark.parametrize("actual,requested,accepted", [
    ("https://GITHUB.COM/NCAR/wrf_hydro_nwm_public.git",
     "https://github.com/NCAR/wrf_hydro_nwm_public", True),
    ("https://github.com/NCAR/wrf_hydro_nwm_public",
     "https://github.com/NCAR/wrf_hydro_nwm_public.git", True),
    ("http://github.com/NCAR/wrf_hydro_nwm_public.git",
     "https://github.com/NCAR/wrf_hydro_nwm_public", False),
    ("https://other.example/NCAR/model.git", "https://other.example/NCAR/model", False),
    ("https://github.com/other/model.git", "https://github.com/NCAR/model", False),
])
def test_known_github_clone_url_spelling_only(upstream, tmp_path, built,
                                           actual, requested, accepted):
    target = clone(upstream, tmp_path)
    git(target, "remote", "set-url", "origin", actual)
    step = acquire(manifest(requested), target)
    assert step.ok is accepted, step.detail
    assert bool(built) is accepted


def test_unborn_partial_repository_is_not_built(upstream, tmp_path, built):
    target = tmp_path / "unborn"
    target.mkdir()
    git(target, "init", "-q")
    git(target, "remote", "add", "origin", str(upstream))
    step = acquire(manifest(upstream), target)
    assert not step.ok and "HEAD" in step.detail
    assert not built


def test_visibility_flags_are_reported_without_discarding_local_files(upstream, tmp_path, built):
    target = clone(upstream, tmp_path)
    git(target, "update-index", "--assume-unchanged", "config.mk")
    (target / "config.mk").write_text("local hidden patch\n", encoding="utf-8")
    step = acquire(manifest(upstream), target)
    assert step.ok, step.detail
    assert step.evidence["source_checkout"]["index_visibility_limited"] == ["config.mk"]
    assert "not a pristine-source build" in step.detail
    assert (target / "config.mk").read_text(encoding="utf-8") == "local hidden patch\n"


def test_build_failure_retains_source_identity_and_dirty_evidence(upstream, tmp_path, built, monkeypatch):
    target = clone(upstream, tmp_path)
    (target / "config.mk").write_text("local patch\n", encoding="utf-8")
    real = install._run

    def fail(command, **kwargs):
        return (3, "fixture compiler failure") if command == "fixture-build" else real(command, **kwargs)

    monkeypatch.setattr(install, "_run", fail)
    step = acquire(manifest(upstream), target)
    assert not step.ok and "fixture compiler failure" in step.detail
    assert step.evidence["source_checkout"]["tracked_changes"]


def test_symlink_entry_with_windows_text_checkout_is_complete(upstream, tmp_path, built):
    blob = git(upstream, "hash-object", "-w", "--stdin", input="source.f90")
    git(upstream, "update-index", "--add", "--cacheinfo", f"120000,{blob},source-link")
    git(upstream, "commit", "-qm", "tracked symlink")
    git(upstream, "tag", "links")
    target = tmp_path / "checkout"
    git(tmp_path, "-c", "core.symlinks=false", "clone", "-q", "--branch", "links",
        str(upstream), str(target))
    assert (target / "source-link").is_file()
    step = acquire(manifest(upstream, "links"), target)
    assert step.ok, step.detail



@pytest.fixture
def shadowed(upstream):
    """NCAR layout: release tag v5 is newer than a stale same-named branch."""
    stale = git(upstream, "rev-parse", "HEAD")
    git(upstream, "branch", "v5", stale)
    (upstream / "source.f90").write_text("program release\nend program\n", encoding="utf-8")
    git(upstream, "commit", "-qam", "release")
    git(upstream, "tag", "v5")
    return stale, git(upstream, "rev-parse", "HEAD")


def test_fresh_clone_takes_release_tag_not_same_named_branch(upstream, tmp_path, built, shadowed):
    stale, release = shadowed
    target = tmp_path / "fresh-release"
    step = acquire(manifest(upstream, "v5"), target)
    assert step.ok, step.detail
    source = step.evidence["source_checkout"]
    assert source["resolved_commit"] == release
    assert source["requested_ref_kind"] == "tag"
    assert source["shadowed_branch_commit"] == stale
    assert not any("--branch" in command for command in step.commands)
    assert (target / "source.f90").read_text(encoding="utf-8").startswith("program release")


def test_existing_branch_checkout_is_not_reused_as_release_tag(upstream, tmp_path, built, shadowed):
    stale, release = shadowed
    target = clone(upstream, tmp_path, ref="v5")  # clone --branch picks the stale branch
    assert git(target, "rev-parse", "HEAD") == stale
    step = acquire(manifest(upstream, "v5"), target)
    assert not step.ok and "same-named branch" in step.detail
    assert "fetch --depth 1 origin refs/tags/v5:refs/tags/v5" in step.detail
    assert not built and git(target, "rev-parse", "HEAD") == stale
    # The suggested deliberate acquisition then passes, despite the stale branch ref.
    git(target, "fetch", "-q", "--depth", "1", "origin", "refs/tags/v5:refs/tags/v5")
    git(target, "checkout", "-q", "--detach", "refs/tags/v5")
    step = acquire(manifest(upstream, "v5"), target)
    assert step.ok, step.detail
    assert step.evidence["source_checkout"]["resolved_commit"] == release


def test_explicit_branch_ref_still_selects_the_branch(upstream, tmp_path, built, shadowed):
    stale, _release = shadowed
    step = acquire(manifest(upstream, "refs/heads/v5"), tmp_path / "branch")
    assert step.ok, step.detail
    source = step.evidence["source_checkout"]
    assert source["resolved_commit"] == stale and source["requested_ref_kind"] == "branch"
