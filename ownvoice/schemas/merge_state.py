"""Private source-report digests committing the completed merge."""

from ownvoice.schemas import common as c

SCHEMA = {**c.PROVENANCE, "sources": c.mapping(c.SHA256)}


def validate(value):
    return c.validate(value, SCHEMA, "merge-state")


def build(**fields):
    return c.build(fields, SCHEMA, "merge-state")
