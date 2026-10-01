"""Strict compact LLM projection. Unknown fields are rejected."""

from ownvoice.schemas import common as c
from ownvoice.schemas.profile_stats import CONTRAST, NGRAMS

REGISTER = {
    "n": c.COUNT,
    "low_confidence": bool,
    "derived_from": c.nullable(c.REGISTER),
    "metrics": c.mapping(dict.fromkeys(("p25", "p50", "p75"), c.NUMBER)),
    "greetings": c.optional(c.array(c.FORM)),
    "signoffs": c.optional(c.array(c.FORM)),
    "spelling": c.SPELLING,
    "function_words": c.optional(c.mapping(c.RATE)),
    "ngrams": c.optional(NGRAMS),
    "discourse_markers": c.optional(c.mapping(c.RATE)),
    "hedges": c.optional(c.mapping(c.RATE)),
    "llm_ism_hits": c.array(c.tuple_array(str, c.COUNT)),
    "llm_ism_never_hit": c.optional(c.array(str)),
}
SCHEMA = {
    **c.PROVENANCE,
    "registers": c.registers(REGISTER),
    "contrast": c.array({**CONTRAST, "status": c.enum("diverging")}),
}


def validate(value):
    return c.validate(value, SCHEMA, "stats-llm")


def build(**fields):
    return c.build(fields, SCHEMA, "stats-llm")
