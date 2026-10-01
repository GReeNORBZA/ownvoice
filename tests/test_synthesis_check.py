from pathlib import Path

import pytest

from ownvoice.errors import DiagnosticError
from ownvoice.qual.synthesis_check import check


@pytest.fixture
def names(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("Zyxora\n")
    return path


def test_names_and_absent_quotes_are_listed(names):
    with pytest.raises(DiagnosticError) as caught:
        check('Zyxora said "invented purple rockets".', names, ["actual text"])
    message = str(caught.value)
    for part in (
        "check profile synthesis",
        "draft.md",
        "Zyxora",
        "invented purple rockets",
        "expected",
        "next step",
    ):
        assert part in message


@pytest.mark.parametrize(
    "quote",
    [
        '"absent span"',
        "“absent span”",
        "‘absent span’",
        "'absent span'",
        "`absent span`",
        "> absent span",
    ],
)
def test_quote_notation_cannot_hide_ungrounded_span(names, quote):
    with pytest.raises(DiagnosticError, match="absent span"):
        check(quote, names, ["actual text"])


def test_cap_quote_and_contractions_pass(names):
    check('We don\'t speculate. "Steady words [CAP] today."', names, ["Steady words [CAP] today."])


def test_names_guard_still_checks_copied_rules(names):
    with pytest.raises(DiagnosticError, match="Zyxora"):
        check("Copied rules: Zyxora", names, [], quoted_text="No authored quotation.")


def test_missing_names_preserves_cause(tmp_path):
    path = tmp_path / "absent.txt"
    with pytest.raises(DiagnosticError) as caught:
        check("draft", path, [])
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    for part in ("read qual input", str(path), "expected", "next step"):
        assert part in str(caught.value)


def test_guard_rejects_nonreserved_address(names):
    address = "recipient" + "@" + "private.invalid"
    with pytest.raises(DiagnosticError, match="guard exit=5"):
        check(address, names, [])


def test_check_does_not_leave_draft_in_repository(names):
    check("Numerical profile.", names, [])
    assert not (Path.cwd() / "draft.md").exists()
