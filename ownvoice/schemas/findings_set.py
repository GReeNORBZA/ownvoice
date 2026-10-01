"""Canonical findings retain all supporting record/quote pairs and merge history."""

from ownvoice.schemas import common as c
from ownvoice.schemas.finding import FIELDS

CANONICAL = {
    key: value
    for key, value in FIELDS.items()
    if key not in ("record_id", "chunk_id", "verbatim_quote")
}
CANONICAL.update(
    finding_id=str,
    provenance=c.array({"record_id": c.RECORD_ID, "chunk_id": str, "verbatim_quote": str}),
)
SCHEMA = {
    **c.PROVENANCE,
    "findings": c.array(CANONICAL),
    "changelog": c.array(
        {
            "pass": c.enum("A", "B"),
            "finding_id": str,
            "action": c.enum("new", "matched", "borderline"),
            "record_ids": c.array(c.RECORD_ID),
        }
    ),
    "passes": c.array(c.enum("A", "B")),
    "residual": c.COUNT,
    "unresolved_failed": c.COUNT,
}


def validate(value):
    return c.validate(value, SCHEMA, "findings-set")


def build(**fields):
    return c.build(fields, SCHEMA, "findings-set")
