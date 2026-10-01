"""The owner's reviewed names-allow.txt beside names.txt removes only listed entries."""

import pytest

from ownvoice.cli import main as ownvoice
from ownvoice.errors import DiagnosticError
from ownvoice.guard.rules import without_allowed
from ownvoice.qual.synthesis_check import check


def test_allow_file_beside_names_drops_only_listed_entries(tmp_path):
    names = tmp_path / "names.txt"
    names.write_text("Zelphira\nAcmecorp\nQuorbital\n")
    assert without_allowed(["Zelphira", "Acmecorp"], names) == ("Zelphira", "Acmecorp")
    (tmp_path / "names-allow.txt").write_text("# reviewed\nacmecorp\n\n")
    assert without_allowed(["Zelphira", "Acmecorp", "Quorbital"], names) == (
        "Zelphira",
        "Quorbital",
    )
    check("Acmecorp shipped it.", names, [])
    with pytest.raises(DiagnosticError, match="Quorbital"):
        check("Quorbital shipped it.", names, [])


def test_guard_cli_honours_allow_file(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "note.md").write_text("Acmecorp shipped it.\n")
    names = tmp_path / "names.txt"
    names.write_text("Acmecorp\n")
    assert ownvoice(["guard", "--tree", str(tree), "--names-file", str(names)]) == 5
    (tmp_path / "names-allow.txt").write_text("Acmecorp\n")
    assert ownvoice(["guard", "--tree", str(tree), "--names-file", str(names)]) == 0
