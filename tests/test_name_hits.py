"""Names that are also common words match the way the scrubber masks them."""

import pytest

from ownvoice.errors import DiagnosticError
from ownvoice.guard.rules import common_words, content_rules, name_hits
from ownvoice.qual.synthesis_check import check

# "Will" and "An" are wordlist words; "Zelphira" is not.
NAMES = ["Will", "An", "Zelphira"]


def test_fixture_words_are_on_the_shipped_wordlist():
    assert {"will", "an"} <= common_words()
    assert "zelphira" not in common_words()


@pytest.mark.parametrize(
    "text",
    [
        "We will send it. An update follows.",
        "Will you confirm?\nAn early reply helps.",
        "It is an easy fix, and it will ship.",
        "Plain prose with no names.",
    ],
)
def test_common_word_names_ignored_lowercase_or_sentence_initial(text):
    assert name_hits(text, NAMES) == []
    assert 4 not in content_rules(text, NAMES, release=False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please ask Will before Friday.", ["Will"]),
        ("I met An yesterday.", ["An"]),
        ("zelphira agreed.", ["Zelphira"]),
        ("We spoke to ZELPHIRA.", ["Zelphira"]),
        ("Thanks Will, and zelphira too.", ["Will", "Zelphira"]),
    ],
)
def test_names_still_caught(text, expected):
    assert name_hits(text, NAMES) == expected
    assert 4 in content_rules(text, NAMES, release=False)


def test_whole_word_only():
    assert name_hits("Zelphiran and Willow and Anna", NAMES) == []


def test_synthesis_check_allows_common_words_but_not_names(tmp_path):
    names = tmp_path / "names.txt"
    names.write_text("\n".join(NAMES) + "\n")
    check("An owner will reply. Be brief.", names, [])
    with pytest.raises(DiagnosticError, match="offending names=\\['Will'\\]"):
        check("Forward it to Will today.", names, [])
