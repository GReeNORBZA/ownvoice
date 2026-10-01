"""Marked, line-delimited private name lexicon."""

from ownvoice.io import PRIVATE_LINE
from ownvoice.schemas import common as c


def validate(value):
    errors = []
    c.check(value, str, "names.text", errors)
    if not errors:
        c.constraint(
            errors,
            "names.marker",
            value.startswith(PRIVATE_LINE + "\n"),
            "the private marker on the first line",
        )
        c.constraint(errors, "names.lines", value.endswith("\n"), "newline-terminated names")
    if errors:
        raise c.ValidationErrors(errors)
    return value


def build(values):
    return validate(PRIVATE_LINE + "\n" + "".join(name + "\n" for name in sorted(values)))
