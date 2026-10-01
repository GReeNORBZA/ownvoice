"""Edit tendencies."""

from ownvoice.schemas import common as c

TAGS = (
    "contraction",
    "join",
    "em_dash_to_spaced_hyphen",
    "em_dash_removed",
    "llm_ism_removed",
    "second_person_added",
    "first_person_added",
    "hedge_removed",
    "hedge_added",
    "sentence_joined_comma",
    "scope_broadened",
)
SCHEMA = {
    **c.PROVENANCE,
    "chains": c.array({"id": str, "versions": c.array({"sha256": c.SHA256})}),
    "pairs": c.COUNT,
    "aggregate": c.mapping(dict.fromkeys(("before", "after", "delta"), c.NUMBER)),
    "operations": dict.fromkeys(("join", "split", "replace", "insert", "delete"), c.COUNT),
    "substitutions": c.array({"before": str, "after": str, "count": c.COUNT}),
    "examples": c.array(
        {"chain_id": str, "before": str, "after": str, "tags": c.array(c.enum(*TAGS))}
    ),
}


def _limits(value, errors):
    c.constraint(errors, "edit-delta.examples", len(value["examples"]) <= 20, "at most 20 examples")
    for index, example in enumerate(value["examples"]):
        for key in ("before", "after"):
            c.constraint(
                errors,
                f"edit-delta.examples[{index}].{key}",
                len(example[key].split()) <= 60,
                "at most 60 words",
            )


def validate(value):
    return c.validate(value, SCHEMA, "edit-delta", _limits)


def build(**fields):
    return c.build(fields, SCHEMA, "edit-delta", _limits)
