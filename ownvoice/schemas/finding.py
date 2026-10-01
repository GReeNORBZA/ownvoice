"""One grounded or candidate observation."""

from ownvoice.schemas import common as c

FIELDS = {
    "dimension": c.enum(
        "tone",
        "humour",
        "persuasion",
        "bad_news",
        "apology",
        "gratitude",
        "directness",
        "self_deprecation",
        "other",
    ),
    "register": c.REGISTER,
    "observation": str,
    "verbatim_quote": str,
    "record_id": c.RECORD_ID,
    "chunk_id": str,
    "confidence": c.enum("high", "medium", "low"),
}
SCHEMA = {c.PRIVATE_KEY: c.enum(c.PRIVATE_VALUE), **FIELDS}


def _quote(value, errors):
    c.constraint(
        errors,
        "finding.verbatim_quote",
        len(value["verbatim_quote"].split()) <= 25,
        "at most 25 words",
    )


def validate(value):
    return c.validate(value, SCHEMA, "finding", _quote)


def build(**fields):
    return c.build(fields, SCHEMA, "finding", _quote)
