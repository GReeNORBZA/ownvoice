"""Release guard: host:port false positives and internal-directory exclusions.

Synthetic text only. Literals that would trip the guard on this file are built from
parts, as in the guard source.
"""

import pytest

from ownvoice.guard import RELEASE_EXCLUDED_DIRS
from ownvoice.guard.rules import content_rules, host_port
from tests.test_guard import git, guard, put, repo  # noqa: F401 (pytest fixture)


@pytest.mark.parametrize(
    "text",
    [
        "internal-host" + ":8443",
        "build.example" + ":22",
        "localhost" + ":8080",
        "container" + ":8200",
        "see service" + ":443 for the proxy",
    ],
)
def test_host_port_flags_hosts(text):
    assert host_port(text)
    assert 5 in content_rules(text, (), release=True)


@pytest.mark.parametrize(
    "text",
    [
        "the job ran at 01" + ":30 and 12" + ":00",
        "generated 2026-09-25T00" + ":00Z",
        "f'{i" + ":03}' and f'{index" + ":05}' and f'{severity" + ":6}'",
        "image node" + ":22 and python" + ":3",
        "ratio 1" + ":8 and 10" + ":12",
    ],
)
def test_host_port_ignores_times_formats_and_tags(text):
    assert not host_port(text)
    assert 5 not in content_rules(text, (), release=True)


def test_host_port_only_applies_on_release():
    assert 5 not in content_rules("internal-host" + ":8443", (), release=False)


@pytest.mark.parametrize("internal", RELEASE_EXCLUDED_DIRS)
def test_internal_directories_fail_release(repo, internal):  # noqa: F811
    names = put(repo.parent, "private-list", "Zelphira\n")
    put(repo, internal + "note.md", "Public prose.")
    git(repo, "add", ".")
    args = ("--tree", ".", "--names-file", str(names))
    assert guard(repo, *args).returncode == 0
    result = guard(repo, *args, "--release")
    assert result.returncode == 5
    assert f"[{internal}]: rule 5 violation" in result.stderr
