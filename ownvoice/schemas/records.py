"""Scrubbed owner email. No headers or recipient identities."""

from ownvoice.schemas import common as c

SCHEMA = {
    c.PRIVATE_KEY: c.enum(c.PRIVATE_VALUE),
    "record_id": c.RECORD_ID,
    "source": c.LABEL,
    "era": c.nullable(("pattern", r"\d{4}-\d{4}")),
    "source_kind": c.enum("pst", "mbox", "eml"),
    "year": c.nullable(c.bounded(int, 1, 9999)),
    "weekday": c.nullable(c.bounded(int, 0, 6)),
    "hour_bucket": c.nullable(c.enum("night", "morning", "afternoon", "evening")),
    "recipient_class": c.enum(*c.CLASSES),
    "recipient_count_bucket": c.enum("1", "2-3", "4+"),
    "recipient_stages": c.STAGES,
    "thread_position": c.THREAD,
    "word_count": c.COUNT,
    "text": str,
    "greeting": c.nullable(str),
    "signoff": c.nullable(str),
    "strip": {
        "body_source": c.enum("html", "plain"),
        "rules_fired": c.array(str),
        "inline_reply": bool,
        "confidence": c.enum("high", "low"),
        "flags": c.array(str),
    },
    "scrub": {
        **dict.fromkeys(
            ("greeting_names", "lexicon_names", "emails", "phones", "urls", "numbers"), c.COUNT
        ),
        "residual_capitalised": c.array(str),
    },
    "template": bool,
    "sensitive": bool,
}


def validate(value):
    return c.validate(value, SCHEMA, "records")


def build(**fields):
    return c.build(fields, SCHEMA, "records")
