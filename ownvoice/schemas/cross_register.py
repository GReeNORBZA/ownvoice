"""Grounded cross-register groups, separate from canonical findings."""

from ownvoice.schemas import common as c

GROUP = {
    "group_id": c.SHA256,
    "dimension": str,
    "registers": c.array(c.REGISTER),
    "finding_ids": c.array(str),
    "quotes": c.array({"register": c.REGISTER, "verbatim_quote": str, "record_id": c.RECORD_ID}),
}
SCHEMA = {c.PRIVATE_KEY: c.enum(c.PRIVATE_VALUE), "groups": c.array(GROUP)}


def validate(value):
    return c.validate(value, SCHEMA, "cross-register")


def build(**fields):
    return c.build(fields, SCHEMA, "cross-register")
