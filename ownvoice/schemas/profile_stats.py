"""Local detailed statistics."""

from ownvoice.schemas import common as c

CONTRAST = {
    "register": c.REGISTER,
    "metric": str,
    "p50_by_source": c.mapping(c.NUMBER),
    "iqr_merged": c.RATE,
    "status": c.enum("diverging", "same", "insufficient_data"),
    "default_source": c.LABEL,
}
NGRAMS = {
    "bi": c.array(c.tuple_array(str, c.COUNT, c.NUMBER)),
    "tri": c.array(c.tuple_array(str, c.COUNT, c.NUMBER)),
}
# Tier B threshold per metric: the register's own p90 (or p10 for "min").
AI_TELL = {
    "direction": c.enum("max", "min"),
    "threshold": c.nullable(c.NUMBER),
    "p50": c.NUMBER,
    "n": c.COUNT,
    "basis": c.enum("register", "_global", "long_emails", "article_shape"),
}
# Baseline cutoff and article-basis provenance.
BASELINE = {
    "before": c.nullable(("pattern", r"\d{4}-\d{2}-\d{2}")),
    "granularity": c.enum("year"),
    "excluded_after": c.COUNT,
    "excluded_undated": c.COUNT,
    "article_basis": c.enum("chain_finals", "long_emails", "professional-warm"),
    "article_finals_excluded": bool,
    "long_email_min_words": c.RATE,
    "long_emails": c.COUNT,
}
REGISTER = {
    "n": c.COUNT,
    "low_confidence": bool,
    "derived_from": c.nullable(c.REGISTER),
    "metrics": c.mapping(c.METRIC),
    "dash_chars": {"em": c.RATE, "en": c.RATE},
    "greetings": c.array(c.FORM),
    "signoffs": c.array(c.FORM),
    "spelling": {**c.SPELLING, "top_pairs": c.array(c.tuple_array(str, c.COUNT))},
    "function_words": c.mapping(c.RATE),
    "ngrams": NGRAMS,
    "discourse_markers": c.mapping(c.RATE),
    "hedges": c.mapping(c.RATE),
    "llm_ism_never_hit": c.array(str),
    "never_hit_basis_words": c.COUNT,
    "llm_ism_hits": c.array(c.tuple_array(str, c.COUNT)),
    "ai_tells": c.optional(c.mapping(AI_TELL)),
    "by_thread_position": {
        key: {"n": c.COUNT, "metrics": c.mapping(c.METRIC)} for key in ("new", "reply", "forward")
    },
}
SCHEMA = {
    **c.PROVENANCE,
    "profiled_records": c.optional({"file": str, "sha256": c.SHA256}),
    "profiled_articles": c.optional({"file": str, "sha256": c.SHA256}),
    "edit_delta": c.optional({"file": str, "sha256": c.SHA256}),
    "current_source": c.LABEL,
    "baseline": c.optional(BASELINE),
    "corpus": {
        "records": c.COUNT,
        "rejected": c.COUNT,
        "low_confidence_excluded": c.COUNT,
        "span_years": c.tuple_array(c.COUNT, c.COUNT),
        "per_register": c.registers(c.COUNT),
        "sources": c.mapping(
            {
                "records": c.COUNT,
                "era": c.nullable(str),
                "status": c.enum("complete", "partial", "failed"),
                "llm_eligible": bool,
            }
        ),
    },
    "by_source": c.mapping({"registers": c.registers(REGISTER)}),
    "lexicons": {key: {"source": str, "sha256": c.SHA256} for key in ("llm_ism", "sensitive")},
    "contrast": c.array(CONTRAST),
    "registers": c.registers(REGISTER),
    "time": {key: c.mapping(c.COUNT) for key in ("by_year", "by_weekday", "by_hour_bucket")},
}


def validate(value):
    return c.validate(value, SCHEMA, "profile-stats")


def build(**fields):
    return c.build(fields, SCHEMA, "profile-stats")
