"""An allowed phrase in names-allow.txt exempts only that phrase, not the name."""

import pytest

from ownvoice.cli import main as ownvoice
from ownvoice.guard.rules import name_hits, without_allowed
from ownvoice.qual.synthesis_check import check


@pytest.fixture
def names(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("Em\nZelphira\n")
    (tmp_path / "names-allow.txt").write_text("# reviewed\nem dash\n")
    return path


def test_phrase_is_exempt_but_name_is_not(names):
    loaded = without_allowed(["Em", "Zelphira"], names)
    assert tuple(loaded) == ("Em", "Zelphira")
    assert loaded.phrases == ("em dash",)
    assert name_hits("- **Em dash in articles.** Use a comma instead.", loaded) == []
    assert name_hits("Ask Em about the em dash.", loaded) == ["Em"]
    assert name_hits("Em dashes and Em.", loaded) == ["Em"]


def test_check_and_guard_cli_honour_phrases(names, tmp_path):
    check("**Em dash in articles.** Prefer commas.", names, [])
    with pytest.raises(Exception, match="Em"):
        check("Copy Em on it.", names, [])
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "note.md").write_text("**Em dash in articles.**\n")
    assert ownvoice(["guard", "--tree", str(tree), "--names-file", str(names)]) == 0
    (tree / "note.md").write_text("Copy Em on it.\n")
    assert ownvoice(["guard", "--tree", str(tree), "--names-file", str(names)]) == 5
