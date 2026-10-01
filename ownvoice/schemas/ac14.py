"""Private blind-edit pairs manifest."""

from ownvoice.schemas import common as c

SCHEMA = {
    "schema_version": c.optional(c.enum(1)),
    "brief": c.array(
        dict.fromkeys(("id", "old_draft", "new_draft", "old_final", "new_final"), str)
    ),
}


def _briefs(value, errors):
    ids = set()
    c.constraint(errors, "ac14.brief", bool(value["brief"]), "at least one brief")
    for index, brief in enumerate(value["brief"]):
        for key, item in brief.items():
            c.constraint(
                errors, f"ac14.brief[{index}].{key}", bool(item.strip()), "a nonempty string"
            )
        c.constraint(errors, f"ac14.brief[{index}].id", brief["id"] not in ids, "a unique brief id")
        ids.add(brief["id"])


def validate(value):
    return c.validate(value, SCHEMA, "ac14", _briefs)


def build(**fields):
    return c.build(fields, SCHEMA, "ac14", _briefs)


def load(path):
    return c.load_manifest(path, validate)
