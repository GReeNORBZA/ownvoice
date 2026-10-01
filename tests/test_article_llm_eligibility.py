"""Article and draft text reaches a model only with profile.articles_llm_eligible."""

import json
from types import SimpleNamespace

import pytest

from ownvoice.config import load_config
from ownvoice.errors import ValidationErrors
from ownvoice.qual import dispatch
from tests import test_delta, test_profile, test_qual
from tests.test_dispatch_contract import PROMPT, corpus  # noqa: F401  (shared fixture)
from tests.test_qual import corpus as qual_corpus  # noqa: F401

MARKER = "marmalade"
OPT_IN = "[profile]\narticles_llm_eligible = true"


@pytest.fixture
def profile():
    fixture = test_profile.ProfileTests()
    fixture.setUp()
    yield fixture
    fixture.doCleanups()


def test_setting_must_be_boolean(profile):
    profile.configure()
    profile.config.write_text(
        profile.config.read_text().replace("[profile]", '[profile]\narticles_llm_eligible = "yes"')
    )
    with pytest.raises(ValidationErrors, match="profile.articles_llm_eligible"):
        load_config(profile.config)


def test_setting_requires_complete_llm_table(profile):
    profile.configure()
    text = profile.config.read_text()
    profile.config.write_text(text[: text.index("[llm]")].replace("[profile]", OPT_IN))
    with pytest.raises(ValidationErrors, match="incomplete \\[llm\\]"):
        load_config(profile.config)


def test_absent_setting_keeps_config_digest(profile):
    from ownvoice import provenance

    profile.configure()
    before = provenance.config_digest(load_config(profile.config)[0])
    profile.config.write_text(profile.config.read_text().replace("[profile]", OPT_IN))
    assert provenance.config_digest(load_config(profile.config)[0]) != before


def test_qual_chunk_refuses_articles_without_opt_in(qual_corpus):  # noqa: F811
    root, config, _ = qual_corpus
    articles = root / "articles.jsonl"
    articles.write_text("")
    result = test_qual.cli(
        config,
        "qual",
        "chunk",
        "--records",
        root / "work" / "records.jsonl",
        "--articles",
        articles,
        "--pass",
        "A",
        "--out",
        root / "refused" / "manifest.json",
    )
    assert result.returncode == 2
    assert "articles_llm_eligible is not true" in result.stderr
    assert not (root / "refused").exists()


@pytest.mark.parametrize("opt_in", [False, True])
def test_article_and_draft_text_follow_opt_in(corpus, monkeypatch, opt_in):  # noqa: F811
    fixture = corpus.fixture
    if opt_in:
        fixture.config.write_text(fixture.config.read_text().replace("[profile]", OPT_IN))
    chains = test_delta.manifest(
        fixture,
        [
            f"The {MARKER} plan was very robust and comprehensive overall.",
            f"The {MARKER} plan works.\n\nWe keep the {MARKER} jars in the cool cupboard.",
        ],
        "llm",
    )
    delta = fixture.root / "delta.json"
    result = test_delta.cli(fixture, "--chains", chains, "--out", delta)
    assert result.returncode == 0, result.stderr
    result = fixture.cli("--articles", str(chains), "--edit-delta", str(delta))
    assert result.returncode == 0, result.stderr

    # Model-bound profile outputs carry no article text without the opt-in.
    examples = json.loads((corpus.directory / "exemplars.json").read_text())
    article = examples["registers"]["article"]
    projection = json.loads((corpus.directory / "stats-llm.json").read_text())
    assert ("ngrams" in projection["registers"]["article"]) is opt_in
    if opt_in:
        assert article["items"]
    else:
        assert article["items"] == []
        assert article["selection"]["status"] == "no_llm_eligible_source"
        assert MARKER not in json.dumps(projection)
    assert ("ngrams" in projection["registers"]["client"]) is True

    requests, payloads = [], []

    def invoke(adapter, executable, request, diagnostic):
        requests.append(request)
        if diagnostic.name != "S.diagnostic.md":
            return ""
        data = json.loads(
            request.split("BEGIN_DATA_", 1)[1].split("\n", 1)[1].rsplit("\nEND_DATA_", 1)[0]
        )
        payloads.append(data)
        return json.dumps(
            {
                "1": "Rules first.",
                "2": {r: "Measured targets." for r in data["stats"]["registers"] if r != "_global"},
                "3": "Unavailable.",
                "5": "Follow rules.",
            }
        )

    monkeypatch.setattr(dispatch, "invoke", invoke)
    assert (
        dispatch.build(
            SimpleNamespace(
                config=fixture.config,
                profile_dir=str(corpus.directory),
                prompt=PROMPT,
                adapter="codex",
                executable=None,
            )
        )
        == 0
    )
    sent = "\n".join(requests)
    assert (MARKER in sent) is opt_in
    edit = payloads[0]["edit_delta"]
    assert bool(edit["chains"]) is opt_in
    if not opt_in:
        assert edit["examples"] == edit["substitutions"] == []
        assert payloads[0]["provenance"]["article_records"] == 0
    else:
        assert payloads[0]["provenance"]["article_records"] == 1
