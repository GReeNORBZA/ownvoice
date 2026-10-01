"""Private identity summary: domains and X.500 orgs only, never display names."""

from ownvoice.schemas import common as c

SCHEMA = {
    **c.PROVENANCE,
    "source": c.optional(c.LABEL),
    "domains": c.array({"domain": str, "messages": c.COUNT}),
    "x500_orgs": c.array({"org": str, "messages": c.COUNT}),
    "unresolved_names": c.COUNT,
}


def _limits(value, errors):
    # The design caps the work_dir summary. Per-source private identity state must
    # retain every label so resume can recover the checkpoint's hashed counts.
    if "source" not in value:
        for key in ("domains", "x500_orgs"):
            c.constraint(
                errors, f"unmapped-domains.{key}", len(value[key]) <= 50, "at most 50 entries"
            )
    for index, row in enumerate(value["x500_orgs"]):
        c.constraint(
            errors,
            f"unmapped-domains.x500_orgs[{index}].org",
            "/" not in row["org"],
            "the org component only, without an X.500 distinguished name",
        )


def validate(value):
    return c.validate(value, SCHEMA, "unmapped-domains", _limits)


def build(**fields):
    return c.build(fields, SCHEMA, "unmapped-domains", _limits)
