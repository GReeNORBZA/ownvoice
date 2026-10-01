"""Per-source parse resume state."""

from ownvoice.schemas import common as c

SCHEMA = {
    **c.PROVENANCE,
    "folder": str,
    "message_index": c.COUNT,
    "records": c.COUNT,
    "rejects": c.COUNT,
    "state": c.optional(
        {
            "fingerprint": c.FINGERPRINT,
            "files": c.SHA256,
            "complete": bool,
            "selected": c.COUNT,
            "resolution": {"recipients": c.COUNT, **c.STAGES},
            "domains": c.mapping(c.COUNT),
            "x500_orgs": c.optional(c.mapping(c.COUNT)),
            "names": c.array(str),
        }
    ),
}


def validate(value):
    return c.validate(value, SCHEMA, "checkpoint")


def build(**fields):
    return c.build(fields, SCHEMA, "checkpoint")
