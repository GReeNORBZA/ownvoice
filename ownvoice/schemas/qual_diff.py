"""Mechanical reconciliation result, consumed by qual merge."""

from ownvoice.schemas import common as c
from ownvoice.schemas.finding import SCHEMA as FINDING

SCHEMA = {
    **c.PROVENANCE,
    "pass": c.enum("A", "B"),
    "existing_sha256": c.SHA256,
    "unresolved_failed": c.COUNT,
    "new": c.array(FINDING),
    "matched": c.array({"finding": FINDING, "finding_id": str}),
    "borderline": c.array({"finding": FINDING, "finding_id": str}),
}


def validate(value):
    return c.validate(value, SCHEMA, "qual-diff")


def build(**fields):
    return c.build(fields, SCHEMA, "qual-diff")
