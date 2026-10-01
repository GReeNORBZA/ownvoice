"""Synthetic publish-boundary checks; private content is created only at runtime."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ownvoice.guard import scan
from ownvoice.io import PRIVATE_KEY, PRIVATE_LINE, write_marked_toml
from tests.test_config import CONFIG

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    "mail.pst",
    "mail.ost",
    "mail.mbox",
    "mbox",
    "mail.eml",
    "mail.msg",
    "records-one.jsonl",
    "rejects-one.jsonl",
    "ingest-report-one.json",
    "checkpoint.json",
    "profile-stats-one.json",
    "stats-llm-one.json",
    "exemplars-one.json",
    "edit-delta-one.json",
    "findings-set-one.json",
    "profiled-articles.jsonl",
    "profiled-articles-one.jsonl",
    "cross-register.json",
    "cross-register-one.json",
    "unmapped-domains-one.json",
    "raw/result.jsonl",
    "domain-map-one.toml",
    "chains-one.toml",
    "voice-profile-one.md",
    "names-one.txt",
    "config.toml",
    "Recipients.txt",
    "OutlookHeaders.txt",
    "InternetHeaders.txt",
    "mail.export/ordinary.txt",
    "extract/.done",
    "extract/ordinary.txt",
)


def environment(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(PYTHONPATH=str(ROOT), OWNVOICE_CONFIG=str(tmp_path / "absent.toml"))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    return env


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=environment(repo),
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Fixture Owner")
    git(path, "config", "user.email", "owner@example.com")
    return path


def put(root, name, content="synthetic content"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def guard(repo, *args):
    return subprocess.run(
        [sys.executable, "-m", "ownvoice", "guard", *args],
        cwd=repo,
        env=environment(repo),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("name", ["ordinary.toml", "renamed", "renamed.data"])
@pytest.mark.parametrize("kind", ["marked", "clean", "nested"])
def test_toml_marker_scans_ignore_filename(repo, staged, name, kind):
    source = repo.parent / "synthetic.toml"
    if kind == "marked":
        write_marked_toml(source, 'schema_version = 1\n[settings]\nlabel = "synthetic"\n')
    elif kind == "nested":
        source.write_text(f'[settings]\n{PRIVATE_KEY} = "private"\n')
    else:
        source.write_text('schema_version = 1\n[settings]\nlabel = "synthetic"\n')
    source.rename(repo / name)
    git(repo, "add", ".")
    assert scan(repo, staged=staged) == ([(name, 2)] if kind == "marked" else [])


@pytest.mark.parametrize("prefix", ["", "tests/fixtures/"])
def test_all_artifacts_and_content_rules_in_index(repo, prefix):
    for name in ARTIFACTS:
        put(repo, prefix + name)
    names = put(repo.parent, "private-list", "Zelphira\n")
    bad = {
        "renamed.json": json.dumps({PRIVATE_KEY: "private"}),
        "renamed.md": PRIVATE_LINE + "\nprose",
        "address.txt": "person@" + "real-domain.invalid",
        "identity.txt": "Hello Zelphira!",
    }
    for name, content in bad.items():
        put(repo, prefix + name, content)
    git(repo, "add", ".")
    result = guard(repo, "--staged", "--names-file", str(names))
    assert result.returncode == 5, result.stderr
    for name in ARTIFACTS:
        line = f"[{prefix}{name}]: rule 1 violation"
        assert (line in result.stderr) == (not prefix)
    for name, rule in zip(bad, (2, 2, 3, 4), strict=True):
        assert f"[{prefix}{name}]: rule {rule} violation" in result.stderr
    assert "expected publishable content" in result.stderr
    assert "next step:" in result.stderr


def test_clean_content_and_fixture_exemption(repo):
    for name in ARTIFACTS:
        put(repo, "tests/fixtures/" + name)
    names = put(repo.parent, "private-list", "Zelphira\n")
    put(
        repo,
        "safe.txt",
        "Zelphiran owner@example.com owner@example.org owner@example.net a@corp.example",
    )
    put(repo, "safe.json", json.dumps({"nested": {PRIVATE_KEY: "private"}}))
    put(repo, "safe.md", "Documentation\n" + PRIVATE_LINE)
    put(repo, "extract-without-stamp/data.txt")
    git(repo, "add", ".")
    result = guard(repo, "--staged", "--names-file", str(names))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "text",
    [
        "ownvoice" + ":" + "private-begin",
        "#" + "123",
        "FIX" + "-2026-1234",
        "10" + ".1.2.3",
        "172" + ".16.1.1",
        "192" + ".168.0.1",
        "internal-host" + ":8443",
        "/" + "home/person/file",
        "/" + "Users/person/file",
        "C:" + "\\Users\\person\\file",
    ],
)
def test_release_patterns(repo, text):
    put(repo, "text.md", text)
    names = put(repo.parent, "private-list", "Zelphira\n")
    git(repo, "add", ".")
    assert guard(repo, "--tree", ".").returncode == 0
    result = guard(repo, "--tree", ".", "--release", "--names-file", str(names))
    assert result.returncode == 5
    assert "[text.md]: rule 5 violation" in result.stderr


def test_release_negative_and_docs_directory(repo):
    names = put(repo.parent, "private-list", "Zelphira\n")
    put(repo, "safe.md", "Public prose, 8.8.8.8, 172.32.0.1, 192.169.0.1 and 10.999.1.1")
    git(repo, "add", ".")
    args = ("--tree", ".", "--release", "--names-file", str(names))
    assert guard(repo, *args).returncode == 0
    (repo / "docs" / "frd").mkdir(parents=True)
    result = guard(repo, *args)
    assert result.returncode == 5
    assert "[docs/frd/]: rule 5 violation" in result.stderr
    result = guard(repo, "--release")
    assert result.returncode == 2
    for part in (
        "check release boundary",
        "guard --names-file",
        "no names file",
        "expected",
        "next step:",
    ):
        assert part in result.stderr


def test_staged_bytes_not_worktree_and_deletions(repo):
    path = put(repo, "content.txt", PRIVATE_LINE)
    git(repo, "add", ".")
    path.write_text("safe")
    assert guard(repo, "--staged").returncode == 5
    assert guard(repo, "--tree", ".").returncode == 0
    git(repo, "add", ".")
    path.write_text(PRIVATE_LINE)
    assert guard(repo, "--staged").returncode == 0
    assert guard(repo, "--tree", ".").returncode == 5
    path.write_text("safe")
    git(repo, "rm", "--cached", "content.txt")
    assert guard(repo, "--staged").returncode == 0


def test_names_case_and_whole_word_and_jsonl(repo):
    names = put(repo.parent, "private-list", "Zelphira\n")
    put(repo, "one.txt", "zelphira")
    put(repo, "two.txt", "Zelphiran")
    put(repo, "three.data", "{}\n" + json.dumps({PRIVATE_KEY: None}))
    git(repo, "add", ".")
    result = guard(repo, "--staged", "--names-file", str(names))
    assert result.returncode == 5
    assert "[one.txt]: rule 4" in result.stderr
    assert "[two.txt]" not in result.stderr
    assert "[three.data]: rule 2" in result.stderr


def test_hook_blocks_real_commit_and_preserves_existing_hook(repo):
    env = environment(repo)
    installer = ["bash", str(ROOT / "scripts" / "install-hooks.sh")]
    installed = subprocess.run(
        installer, cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert installed.returncode == 0, installed.stderr
    put(repo, "ordinary.txt", PRIVATE_LINE)
    git(repo, "add", ".")
    result = git(repo, "commit", "-m", "must be rejected", check=False)
    assert result.returncode != 0
    assert "[ordinary.txt]: rule 2 violation" in result.stderr
    assert git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode != 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho existing\n")
    result = subprocess.run(
        installer, cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "install pre-commit hook" in result.stderr
    assert str(hook) in result.stderr and "next step:" in result.stderr
    assert hook.read_text() == "#!/bin/sh\necho existing\n"


def test_plain_export_tree_and_bad_inputs(tmp_path):
    put(tmp_path, "data.txt", PRIVATE_LINE)
    assert guard(tmp_path, "--tree", str(tmp_path)).returncode == 5
    result = guard(tmp_path, "--tree", str(tmp_path / "absent"))
    assert result.returncode == 2
    assert "select guard tree" in result.stderr and "absent" in result.stderr
    result = guard(tmp_path, "--staged")
    assert result.returncode == 3
    assert "read git publish boundary" in result.stderr and "not a git repository" in result.stderr
    result = guard(tmp_path, "--names-file", str(tmp_path / "absent"))
    assert result.returncode == 3
    assert "read guard input" in result.stderr and "No such file" in result.stderr
    invalid = tmp_path / "invalid"
    invalid.write_bytes(b"\xff")
    result = guard(tmp_path, "--names-file", str(invalid))
    assert result.returncode == 2
    assert "read guard names" in result.stderr and "next step:" in result.stderr


def test_hook_discovers_configured_names_at_commit_time(repo):
    env = environment(repo)
    config = put(repo.parent, "owner.toml", CONFIG)
    put(repo.parent, "domain-map.toml", "schema_version = 1\n")
    env["OWNVOICE_CONFIG"] = str(config)
    installed = subprocess.run(
        ["bash", str(ROOT / "scripts" / "install-hooks.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    put(repo.parent, "work/names.txt", "Zelphira\n")
    put(repo, "ordinary.txt", "Zelphira")
    git(repo, "add", ".")
    result = subprocess.run(
        ["git", "commit", "-m", "must be rejected"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "[ordinary.txt]: rule 4 violation" in result.stderr


def test_repo_self_scan_and_ci_wiring():
    result = guard(ROOT, "--tree", str(ROOT))
    assert result.returncode == 0, result.stderr
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for fragment in (
        "ownvoice guard --tree .",
        "bash scripts/install-hooks.sh",
        "needs: [test, guard]",
    ):
        assert fragment in workflow
    assert "guard: not yet installed" not in workflow
