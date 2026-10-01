"""Private published article finals used by Stage Q."""

from ownvoice.schemas import common as c

SCHEMA = {
    c.PRIVATE_KEY: c.enum(c.PRIVATE_VALUE),
    "record_id": c.RECORD_ID,
    "source": c.enum("articles"),
    "recipient_class": c.enum("article"),
    "year": c.enum(None),
    "word_count": c.COUNT,
    "text": str,
    "truncated": bool,
}


def validate(value):
    return c.validate(value, SCHEMA, "article-record")


def build(**fields):
    return c.build(fields, SCHEMA, "article-record")
