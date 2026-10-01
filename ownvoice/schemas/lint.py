"""Draft findings."""

from ownvoice.config import MEDIA
from ownvoice.schemas import common as c

SCHEMA = {
    **c.PROVENANCE,
    "draft": str,
    "register": c.REGISTER,
    "medium": c.enum(*MEDIA),
    "word_count": c.COUNT,
    "sentences": c.COUNT,
    "rate_checks_enabled": bool,
    "findings": c.array(
        {
            "rule_id": str,
            "check_kind": c.enum("stats", "rules", "lexicon", "structure"),
            "severity": c.enum("error", "warn", "info"),
            "metric": c.nullable(str),
            "observed": (str, int, float, bool, type(None)),
            "expected": (str, int, float, bool, type(None)),
            "locations": c.array({"line": c.POSITIVE, "col": c.POSITIVE, "excerpt": str}),
            "fix_hint": str,
        }
    ),
    "summary": dict.fromkeys(("error", "warn", "info"), c.COUNT),
}


def validate(value):
    return c.validate(value, SCHEMA, "lint")


def build(**fields):
    return c.build(fields, SCHEMA, "lint")
