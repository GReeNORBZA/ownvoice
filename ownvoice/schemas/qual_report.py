"""Grounding sidecar, including empty passes and content-free drop reasons."""

from ownvoice.schemas import common as c

SCHEMA = {
    **c.PROVENANCE,
    "pass": c.enum("A", "B"),
    "kept": c.COUNT,
    "dropped": c.array({"index": c.COUNT, "reason": str}),
    "unresolved_failed": c.COUNT,
    "pending": c.COUNT,
    "grounded_sha256": c.SHA256,
}


def validate(value):
    return c.validate(value, SCHEMA, "qual-report")


def build(**fields):
    return c.build(fields, SCHEMA, "qual-report")
