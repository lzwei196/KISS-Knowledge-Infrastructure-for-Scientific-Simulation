"""Origin diagnostics use fake apt metadata; no package operations or probes."""
from types import SimpleNamespace as NS

import pytest

from .test_dependency_capabilities import driver_namespace


def origin(*, trusted=True, source="Ubuntu", archive="noble-updates", site="archive.ubuntu.com"):
    return NS(trusted=trusted, origin=source, archive=archive, site=site)


def blocked(tmp_path, candidate, *, installed="2.7.7ubuntu5", name="python3-apt"):
    ns = driver_namespace(tmp_path)
    entry = NS(is_installed=True, installed=NS(version=installed,
        origins=[origin(trusted=False, source="", archive="now", site="")]), candidate=candidate)
    ns["package_cache"] = {name: entry}
    ns["run"] = lambda *_a, **_kw: pytest.fail("untrusted installed version must remain blocked before package commands")
    with pytest.raises(ValueError) as exc:
        ns["package"](name)
    assert ns["package_records"] == {}
    return str(exc.value)


def test_retired_installed_version_names_trusted_candidate_without_accepting_it(tmp_path):
    message = blocked(tmp_path, NS(version="2.7.7ubuntu5.3", origins=[origin()]))
    assert "python3-apt version 2.7.7ubuntu5 in current repository metadata" in message
    assert "Repository candidate version: 2.7.7ubuntu5.3" in message
    assert "Candidate trusted Ubuntu origin: noble-updates at archive.ubuntu.com" in message
    assert "normal package management, then re-run verification" in message
    assert "does not authenticate the installed version" in message
    assert "verification remains blocked" in message
    assert "Other installed dependencies may require the same repository refresh/update" in message
    assert "updating this package alone does not establish readiness" in message


@pytest.mark.parametrize("candidate", [None, NS(), NS(version="2.0", origins=[]),
    NS(version="2.0", origins=[origin(trusted=False)]),
    NS(version="2.0", origins=[origin(source="ThirdParty")])])
def test_untrusted_or_unknown_candidate_is_not_presented_as_update_authority(tmp_path, candidate):
    message = blocked(tmp_path, candidate)
    assert "No trusted Ubuntu candidate origin is currently identified" in message
    assert "Candidate trusted Ubuntu origin:" not in message
    assert "when available, then re-run verification" in message
    assert "no package was changed" in message


@pytest.mark.parametrize("bad", ["https://user:secret@host/", "2.0\nTOKEN=secret", "2.0\x1bsecret", "x" * 10000,
                                 {"secret": "value"}, 123, None])
def test_diagnostic_metadata_is_bounded_and_does_not_echo_unsafe_fields(tmp_path, bad):
    candidate = NS(version=bad, origins=[origin(archive=bad, site=bad)])
    message = blocked(tmp_path, candidate, installed=bad)
    assert "<unknown>" in message
    assert "secret" not in message and "https" not in message
    assert "\n" not in message and "\x1b" not in message
    assert len(message) < 1000


def test_only_bounded_trusted_ubuntu_origin_metadata_is_reported(tmp_path):
    candidate = NS(version="1:2.0~rc1-1ubuntu1", origins=[origin(), origin(),
        origin(archive="noble-security", site="security.ubuntu.com"),
        origin(archive="noble", site="archive.ubuntu.com"),
        origin(archive="unprinted", site="fourth.example"),
        origin(trusted=False, archive="secret", site="token.example")])
    message = blocked(tmp_path, candidate)
    assert message.count("noble-updates at archive.ubuntu.com") == 1
    assert "noble-security at security.ubuntu.com" in message
    assert "unprinted" not in message and "secret" not in message
    assert "1:2.0~rc1-1ubuntu1" in message and len(message) < 1100


def test_installed_trusted_package_retains_existing_verification_and_record(tmp_path):
    ns = driver_namespace(tmp_path)
    ns["package_cache"] = {"python3-apt": NS(is_installed=True,
        installed=NS(version="2.7.7ubuntu5.3", origins=[origin()]), candidate=None)}
    calls = []
    def run(argv):
        calls.append(argv)
        return "" if "--verify" in argv else "ii \t2.7.7ubuntu5.3\tamd64"
    ns["run"] = run
    assert ns["package"]("python3-apt") == {"status": "ii \t2.7.7ubuntu5.3\tamd64",
        "origins": [["Ubuntu", "noble-updates", "archive.ubuntu.com"]]}
    assert len(calls) == 2 and calls[-1] == ["/usr/bin/dpkg", "--verify", "python3-apt"]
