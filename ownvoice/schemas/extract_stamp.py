"""extract/.done stores the input fingerprint."""

from ownvoice.schemas import common as c

SCHEMA = {**c.PROVENANCE, "fingerprint": c.FINGERPRINT}


def validate(value):
    return c.validate(value, SCHEMA, "extract/.done")


def build(**fields):
    return c.build(fields, SCHEMA, "extract/.done")
