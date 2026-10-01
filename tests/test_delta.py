"""Synthetic C10 acceptance fixtures, no owner corpus content."""

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ownvoice.commands.edit_delta import compute, scrub_text, scrubber
from ownvoice.config import load_config
from ownvoice.delta.align import align
from ownvoice.delta.classify import classify
from ownvoice.delta.compare import compare
from ownvoice.delta.discover import discover
from ownvoice.delta.normalize import git, load, normalize, read_text
from ownvoice.errors import DiagnosticError
from ownvoice.io import PRIVATE_KEY, PRIVATE_LINE, has_private_marker
from ownvoice.schemas import edit_delta
from ownvoice.style.metrics import measure
from ownvoice.style.tokenize import lexicon
from tests import test_profile


@pytest.fixture
def profile():
    fixture = test_profile.ProfileTests()
    fixture.setUp()
    yield fixture
    fixture.doCleanups()


def chain(identity, before, after, origin="llm"):
    return {
        "id": identity,
        "texts": [before, after],
        "origin": origin,
        "versions": [{"sha256": hashlib.sha256(t.encode()).hexdigest()} for t in (before, after)],
    }


def clean(text):
    return scrub_text(text, {"Smith"})


def cli(profile, *args, env=None):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ownvoice",
            "--config",
            str(profile.config),
            "edit-delta",
            *map(str, args),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def manifest(profile, texts, origin="llm"):
    files = []
    for i, text in enumerate(texts):
        path = profile.root / f"version-{i}.md"
        path.write_text(text)
        files.append(path.name)
    path = profile.root / "chains.toml"
    path.write_text(
        'schema_version = 1\n[[chain]]\nid = "synthetic"\n'
        f'origin = "{origin}"\nversions = {json.dumps(files)}\n'
    )
    return path


def test_normalize_preserves_metric_dash_and_alignment_quotes():
    text = "---\ntitle: example\n---\n<!-- hidden -->\n- **one** [two](https://example.com) ![three](x) “four”—five"
    assert normalize(text) == "one two [image: three] “four”—five"
    assert normalize(text, alignment=True) == 'one two [image: three] "four"-five'
    assert list(align("one — two.", "one - two.")) == [("replace", ["one — two."], ["one - two."])]


def test_stale_deny_list_rejects_edit_delta_reuse(profile):
    from ownvoice.qual.dispatch import load_edit_delta

    terms = profile.root / "deny.txt"
    terms.write_text("unmatchedword\n")
    profile.config.write_text(
        profile.config.read_text() + f'\n[ingest]\ndeny_terms_file = "{terms}"\n'
    )
    profile.inputs([profile.row(1), profile.row(2, source="current")])
    chains = manifest(profile, ["We are ready to work.", "We're ready to work."])
    delta = profile.root / "delta.json"
    result = cli(profile, "--chains", chains, "--out", delta)
    assert result.returncode == 0, result.stderr
    result = profile.cli("--edit-delta", str(delta))
    assert result.returncode == 0, result.stderr
    directory = profile.work / "profile/ownvoice"
    stats = json.loads((directory / "profile-stats.json").read_text())
    terms.write_text("work\n")
    config, _ = load_config(profile.config)
    with pytest.raises(
        DiagnosticError, match="validate artefact policy.*edit.delta.*expected.*ownvoice edit-delta"
    ):
        load_edit_delta(directory, stats, config=config)
    # Refresh synthetic source reports so only the stale edit delta is under test.
    profile.inputs([profile.row(1), profile.row(2, source="current")])
    before = {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    result = profile.cli("--edit-delta", str(delta))
    assert result.returncode == 2
    assert "ownvoice edit-delta" in result.stderr
    assert before == {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def test_operations_and_e2_computed_tags():
    assert clean("O'Neill is ready.")[2]["residual_capitalised"] == ["Neill"]
    before = "We are ready to start the work. We will keep the plan simple. We do not need another meeting."
    after = (
        "We're ready to start the work, we'll keep the plan simple, we don't need another meeting."
    )
    result = compute([chain("e2", before, after)], clean)
    assert result["operations"]["join"] == 1
    assert {"contraction", "sentence_joined_comma", "join"} <= set(result["examples"][0]["tags"])
    assert classify("replace", [after], ["We are ready.", "We will work."])[0] == "split"
    assert classify("replace", ["The plan is simple."], ["The plan is clear."])[0] == "replace"
    assert classify("replace", ["one two three.", "four five six."], ["one two."])[0] == "replace"
    assert next(align("The plan is clear.", "The plan is clear. We can start."))[0] == "insert"
    assert next(align("The plan is clear. We can start.", "The plan is clear."))[0] == "delete"


def test_tags_and_scope_threshold():
    ism = lexicon("llm-isms.txt")[0]
    tags = classify(
        "replace",
        [f"We can {ism} the plan — it is simple."],
        ["We can use the plan - it's simple."],
    )[1]
    assert {"contraction", "em_dash_to_spaced_hyphen", "em_dash_removed", "llm_ism_removed"} <= set(
        tags
    )
    assert (
        "scope_broadened"
        in classify(
            "replace",
            ["one two three four five six seven"],
            ["one two three four five six seven eight nine ten"],
        )[1]
    )
    assert (
        "scope_broadened"
        not in classify(
            "replace",
            ["one two three four five six seven eight"],
            ["one two three four five six seven eight nine ten"],
        )[1]
    )
    hedge = lexicon("hedges.txt")[0]
    assert (
        "hedge_removed"
        in classify("replace", [f"we {hedge} need the simple plan"], ["we need the simple plan"])[1]
    )
    assert (
        "hedge_added"
        in classify("replace", ["we need the simple plan"], [f"we {hedge} need the simple plan"])[1]
    )
    assert {"first_person_added", "second_person_added"} <= set(
        classify(
            "replace",
            ["the plan is ready for the next meeting"],
            ["I think your plan is ready for the next meeting"],
        )[1]
    )


def test_masks_residual_drop_substitutions_and_ranking():
    before = "We are ready to send Smith the plan at person@example.com and https://example.com with 123456 and +1 555 123 4567."
    result = compute([chain("safe", before, before.replace("We are", "We're"))], clean)
    example = result["examples"][0]
    for mask in ("[NAME]", "[EMAIL]", "[URL]", "[NUM]", "[PHONE]"):
        assert mask in example["before"]
    dropped = compute(
        [
            chain(
                "drop",
                "We are ready to send ZzyqCorp the plan.",
                "We're ready to send ZzyqCorp the plan.",
            )
        ],
        clean,
    )
    assert dropped["examples"] == [] and dropped["substitutions"] == []
    repeated = compute(
        [
            chain(str(i), "We are ready to start the work.", "We're ready to start the work.")
            for i in range(25)
        ],
        clean,
    )
    assert len(repeated["examples"]) == 20
    assert [x["chain_id"] for x in repeated["examples"]] == sorted(map(str, range(25)))[:20]
    assert repeated["substitutions"] == [{"before": "We are", "after": "We're", "count": 25}]
    rich = chain("zz", "We are ready — the plan is simple.", "We're ready - the plan is simple.")
    ranked = compute([chain("aa", "We are ready.", "We're ready."), rich], clean)
    assert ranked["examples"][0]["chain_id"] == "zz"
    long = "we are ready " + "to work " * 70
    bounded = compute([chain("long", long, long.replace("we are", "we're"))], clean)
    assert all(len(e[k].split()) <= 60 for e in bounded["examples"] for k in ("before", "after"))


def test_aggregate_first_llm_final_only():
    llm = chain("llm", "We are ready to work.", "We're ready.")
    llm["texts"].insert(1, "The middle is much longer than the final version and not a target.")
    result = compute([llm, chain("owner", "one", "one two three four five", "owner")], clean)
    assert result["pairs"] == 3
    for metric in result["aggregate"]:
        assert result["aggregate"][metric]["before"] == measure(llm["texts"][0])[metric]
        assert result["aggregate"][metric]["after"] == measure(llm["texts"][-1])[metric]


def test_file_hashes_rerun_warning_and_mask_config(profile):
    path = manifest(profile, ["We are ready to work.", "We're ready to work."])
    out = profile.root / "delta.json"
    first = cli(profile, "--chains", path, "--out", out)
    assert first.returncode == 0, first.stderr
    data = edit_delta.validate(json.loads(out.read_text()))
    assert (
        data["chains"][0]["versions"][0]["sha256"]
        == hashlib.sha256(b"We are ready to work.").hexdigest()
    )
    assert out.stat().st_mode & 0o777 == 0o600
    assert cli(profile, "--chains", path, "--out", out).stderr == ""
    (profile.root / "version-1.md").write_text("We're ready to start work.")
    rerun = cli(profile, "--chains", path, "--out", out)
    assert rerun.returncode == 0
    assert "compare edit-delta version hashes" in rerun.stderr
    assert (
        str(out) in rerun.stderr
        and "hashes differ" in rerun.stderr
        and "next step:" in rerun.stderr
    )
    config, _ = load_config(profile.config)
    names = profile.work / "names.txt"
    names.parent.mkdir(exist_ok=True)
    names.write_text(PRIVATE_LINE + "\nSmith\n")
    deny = profile.root / "deny.txt"
    deny.write_text("Acme\n")
    config["ingest"]["deny_terms_file"] = str(deny)
    assert (
        scrubber(config)("We send Smith the Acme report.")[0] == "We send [NAME] the [NAME] report."
    )


def test_git_chain_three_commits_subprocess_and_rename(profile):
    repo = profile.root / "repo"
    repo.mkdir()
    git(repo, "fixture", "init", "-q")
    git(repo, "fixture", "config", "user.name", "Synthetic")
    git(repo, "fixture", "config", "user.email", "fixture@example.com")
    texts = ["We are ready to work.", "We're ready to work.", "We're ready to work."]
    for index, text in enumerate(texts):
        if index == 2:
            git(repo, "fixture", "mv", "old.md", "final.md")
        target = repo / ("final.md" if index == 2 else "old.md")
        target.write_text(text)
        git(repo, "fixture", "add", ".")
        git(repo, "fixture", "commit", "-qm", str(index))
    path = profile.root / "chains.toml"
    path.write_text(
        'schema_version=1\n[[chain]]\nid="git-chain"\norigin="llm"\n'
        'git={repo="repo",path="final.md",follow=true}\n'
    )
    out = profile.root / "delta.json"
    result = cli(profile, "--chains", path, "--out", out)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text())["chains"][0]["versions"] == [
        {"sha256": hashlib.sha256(t.encode()).hexdigest()} for t in texts
    ]
    missing = cli(profile, "--chains", path, "--out", out, env={**os.environ, "PATH": ""})
    assert missing.returncode == 3 and "git-chain" in missing.stderr
    assert "read git chain" in missing.stderr and "No such file" in missing.stderr
    assert "install git" in missing.stderr


def test_discover_grouping_order_and_proposal_is_private(profile):
    root = profile.root / "articles"
    root.mkdir()
    for filename, title, date in (
        ("z.md", "Same", "2026-01-01"),
        ("a.md", "Same", "2026-02-01"),
        ("other.md", "Other", "2026-01-01"),
    ):
        (root / filename).write_text(f'---\ntitle: "{title}"\ndate: {date}\n---\nbody')
    proposal = tomllib.loads(discover(root))
    assert len(proposal["chain"]) == 1
    assert [Path(p).name for p in proposal["chain"][0]["versions"]] == ["z.md", "a.md"]
    (root / "a.md").write_text("---\ntitle: Same\ndate: 2026-01-01\n---\nbody")
    with patch("ownvoice.delta.discover.git", side_effect=["20", "5", "10"]):
        assert [
            Path(p).name for p in tomllib.loads(discover(root, True))["chain"][0]["versions"]
        ] == ["z.md", "a.md"]
    out = profile.root / "chains.proposed.toml"
    result = cli(profile, "discover", "--dir", root, "--out", out)
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(out.read_text())[PRIVATE_KEY] == "private"
    assert has_private_marker(out)
    assert len(load(out)) == 1
    assert out.stat().st_mode & 0o777 == 0o600


def test_compare_hand_ratios_ties_masks_and_basenames(profile):
    pairs = profile.root / "ac14.toml"
    for name, text in {
        "old": "one two",
        "new": "one three",
        "final": "one three",
        "mask": "[NAME] we’re",
        "mask-final": "[EMAIL] we're",
    }.items():
        (profile.root / f"{name}.md").write_text(text)
    pairs.write_text(
        '[[brief]]\nid="win"\nold_draft="old.md"\nnew_draft="new.md"\nold_final="final.md"\nnew_final="final.md"\n'
        '[[brief]]\nid="tie"\nold_draft="mask.md"\nnew_draft="mask.md"\nold_final="mask-final.md"\nnew_final="mask-final.md"\n'
    )
    result = compare(pairs)
    assert result["wins"] == 1
    assert result["briefs"][0]["old_ratio"] == 0.5
    assert result["briefs"][0]["new_ratio"] == 1
    assert result["briefs"][1]["old_ratio"] == result["briefs"][1]["new_ratio"] == 1
    out = profile.root / "ac14.json"
    response = cli(profile, "compare", "--pairs", pairs, "--out", out)
    assert response.returncode == 0, response.stderr
    assert json.loads(out.read_text())[PRIVATE_KEY] == "private"
    assert str(profile.root) not in out.read_text()


def test_article_profile_measured_paragraphs_provenance_and_fallback(profile):
    profile.configure(eligible=True)
    profile.config.write_text(
        profile.config.read_text().replace("[profile]", "[profile]\narticles_llm_eligible = true")
    )
    profile.inputs([profile.row(1), profile.row(2, source="current")])
    path = manifest(
        profile,
        [
            "We are ready.",
            "We are ready to start the work with a simple plan.\n\nWe can send the report when the work is done.",
        ],
        "owner",
    )
    delta = profile.root / "delta.json"
    assert cli(profile, "--chains", path, "--out", delta).returncode == 0
    result = profile.cli("--articles", str(path), "--edit-delta", str(delta))
    assert result.returncode == 0, result.stderr
    output = profile.work / "profile" / "ownvoice"
    stats = json.loads((output / "profile-stats.json").read_text())
    article = stats["registers"]["article"]
    assert article["n"] == 1 and article["derived_from"] is None and article["low_confidence"]
    assert article["metrics"]["words"]["mean"] == 21
    assert all(s["registers"]["article"] == article for s in stats["by_source"].values())
    assert stats["edit_delta"] == {
        "file": "edit-deltas/delta.json",
        "sha256": hashlib.sha256(delta.read_bytes()).hexdigest(),
    }
    examples = json.loads((output / "exemplars.json").read_text())["registers"]["article"]
    assert len(examples["items"]) == 2
    assert {r["record_id"] for r in examples["items"]} == {
        hashlib.sha256(("synthetic" + str(i)).encode()).hexdigest()[:16] for i in range(2)
    }
    saved = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert profile.cli("--articles", str(path), "--edit-delta", str(delta)).returncode == 0
    assert saved == {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    assert profile.cli().returncode == 0
    assert (
        json.loads((output / "profile-stats.json").read_text())["registers"]["article"][
            "derived_from"
        ]
        == "professional-warm"
    )


def test_diagnostics_preserve_causes(profile):
    path = profile.root / "absent.md"
    with pytest.raises(
        DiagnosticError, match="read article version.*absent.md.*next step"
    ) as error:
        read_text(path)
    assert isinstance(error.value.__cause__, FileNotFoundError)
    with pytest.raises(DiagnosticError, match="discover article chains.*absent.md.*correct --dir"):
        discover(path)
    with patch(
        "ownvoice.delta.normalize.subprocess.run", side_effect=FileNotFoundError("git unavailable")
    ):
        with pytest.raises(
            DiagnosticError, match="read git chain.*test-chain.*git unavailable"
        ) as error:
            git(profile.root, "test-chain", "log")
        assert isinstance(error.value.__cause__, FileNotFoundError)
    repo = profile.root / "empty-repo"
    repo.mkdir()
    git(repo, "empty", "init", "-q")
    git(
        repo,
        "empty",
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=fixture@example.com",
        "commit",
        "--allow-empty",
        "-qm",
        "empty",
    )
    path = profile.root / "empty.toml"
    path.write_text(
        'schema_version=1\n[[chain]]\nid="empty"\norigin="owner"\ngit={repo="empty-repo",path="none.md",follow=true}'
    )
    with pytest.raises(
        DiagnosticError, match="expand article chain.*empty.*0 versions.*at least two"
    ):
        load(path)
    path = manifest(profile, ["We are ready.", "We're ready."])
    out = profile.root / "malformed.json"
    out.write_text("{")
    response = cli(profile, "--chains", path, "--out", out)
    assert response.returncode == 2
    assert "read previous edit-delta" in response.stderr and str(out) in response.stderr
    assert "caused by:" in response.stderr and "restore or move" in response.stderr
