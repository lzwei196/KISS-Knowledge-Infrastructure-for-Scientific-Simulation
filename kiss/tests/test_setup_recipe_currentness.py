"""Final Desktop checks cannot combine a preflight with another recipe.

The host-selected recipe is outside the enrolled KI in these fixtures; a KI
tree digest alone therefore cannot detect this change. No model is executed.
"""
from copy import deepcopy

import pytest

from kiss_cli import install, software_verification
from .test_setup_final_runtime import case, finish, saved_status, assert_cleared


def test_absent_active_library_uses_application_manifest_directory(case):
    case.handler.library_root = None
    assert case.handler._shipped_manifest("Demo") == case.library / "kiss/manifests/Demo.yaml"


@pytest.mark.parametrize("phase", ["preflight", "requirements"])
@pytest.mark.parametrize("change", ["new-path-convention", "changed-requirements"])
def test_changed_effective_recipe_cannot_receive_final_success(case, monkeypatch, phase, change):
    selected = deepcopy(case.handler._manifest(case.ki))
    monkeypatch.setattr(case.handler, "_manifest", lambda _ki: selected)
    calls = []

    def mutate():
        # Mutate even the same object: the verifier must keep a value snapshot,
        # not merely another reference to a host's cached Manifest instance.
        if change == "new-path-convention":
            selected.runtime_paths = {"version": 1, "mode": "role_tokens"}
        else:
            selected.python_deps = ["new-required-package==1.0"]

    def preflight(*args, **kwargs):
        calls.append("preflight")
        if phase == "preflight":
            mutate()
        return install.Step("preflight", True, "synthetic check of original recipe")

    def requirements(*args, **kwargs):
        calls.append("requirements")
        if phase == "requirements":
            mutate()
        return install.Step("manifest-requirements", True, "synthetic requirements")

    monkeypatch.setattr(install, "run_preflight", preflight)
    monkeypatch.setattr(software_verification, "requirements", requirements)

    assert not finish(case)
    assert calls == (["preflight"] if phase == "preflight" else ["preflight", "requirements"])
    assert_cleared(case)
    assert "recipe changed" in saved_status(case)["primary_error"]["detail"]
