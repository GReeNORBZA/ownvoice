"""Verbatim exemplar selection contract."""

from ownvoice.schemas import common as c

SCHEMA = {
    **c.PROVENANCE,
    "registers": c.registers(
        {
            "low_confidence": c.optional(bool),
            "selection": {
                "criterion": c.enum("hash-spaced within length tertiles"),
                "status": c.enum("ok", "no_llm_eligible_source"),
                "strata": c.array(
                    {
                        "boundaries": c.tuple_array(c.RATE, c.RATE),
                        "eligible": c.COUNT,
                        "eligibility_rate": c.SHARE,
                    }
                ),
                "coverage": c.enum("full", "partial"),
                "eligible": c.COUNT,
                "selected": c.COUNT,
                "words": c.COUNT,
                "by_source": c.mapping(c.COUNT),
                "basis": c.optional(
                    c.enum("records", "chain_final_paragraphs", "long_email_paragraphs")
                ),
                "shortfall": c.optional({"wanted": c.POSITIVE, "selected": c.COUNT}),
            },
            "items": c.array(
                {
                    "record_id": c.RECORD_ID,
                    "source": c.LABEL,
                    "stratum": c.bounded(int, 0, 2),
                    "pick_rank": c.COUNT,
                    "word_count": c.COUNT,
                    "thread_position": c.THREAD,
                    "year": c.nullable(c.bounded(int, 1, 9999)),
                    "text": str,
                }
            ),
        }
    ),
}


def validate(value):
    return c.validate(value, SCHEMA, "exemplars")


def build(**fields):
    return c.build(fields, SCHEMA, "exemplars")
