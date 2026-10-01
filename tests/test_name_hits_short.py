"""Contractions and short names: rule text is not a correspondent's name."""

import pytest

from ownvoice.guard.rules import common_words, name_hits

NAMES = ["Don", "Ed", "Em", "Zelphira"]


def test_fixture_names_are_not_wordlist_words():
    assert not {"don", "ed", "em"} & common_words()


@pytest.mark.parametrize(
    "text",
    [
        "Don't hesitate to ask.",
        "Please don’t.",
        "Any SR&ED claim applies.",
        "It needs to be properly [verb]ed.",
        "Reserve an em dash for interjections.",
        "article-em-dash",
    ],
)
def test_contractions_and_wrong_case_short_names_pass(text):
    assert name_hits(text, NAMES) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ask Don before Friday.", ["Don"]),
        ("Don's report is late.", ["Don"]),
        ("Ed said yes.", ["Ed"]),
        ("Copy Em on it.", ["Em"]),
        ("zelphira agreed.", ["Zelphira"]),
        ("ZELPHIRA's note", ["Zelphira"]),
    ],
)
def test_real_name_uses_still_caught(text, expected):
    assert name_hits(text, NAMES) == expected
