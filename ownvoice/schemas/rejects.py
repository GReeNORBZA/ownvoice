"""Rejection metadata only."""

from ownvoice.schemas import common as c

REASONS = (
    "not_owner",
    "duplicate",
    "excluded_label",
    "empty_after_strip",
    "no_text_body",
    "encrypted",
    "non_mail_item",
    "parse_error",
    "decode_error",
    "out_of_range_year",
)
SCHEMA = {
    c.PRIVATE_KEY: c.enum(c.PRIVATE_VALUE),
    "source_locator": str,
    "record_id": c.nullable(c.RECORD_ID),
    "reason": c.enum(*REASONS),
    "detail": str,
}


def validate(value):
    return c.validate(value, SCHEMA, "rejects")


def build(**fields):
    return c.build(fields, SCHEMA, "rejects")
