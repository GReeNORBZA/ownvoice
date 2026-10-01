"""Private chains.toml loader and contract."""

from ownvoice.schemas import common as c

SCHEMA = {
    c.PRIVATE_KEY: c.optional(c.enum(c.PRIVATE_VALUE)),
    "schema_version": c.enum(1),
    "chain": c.array(
        {
            "id": str,
            "origin": c.enum("llm", "owner"),
            "versions": c.optional(c.array(str)),
            "git": c.optional({"repo": str, "path": str, "follow": bool}),
        }
    ),
}


def _chains(value, errors):
    ids = set()
    c.constraint(errors, "chains.chain", bool(value["chain"]), "at least one chain")
    for index, chain in enumerate(value["chain"]):
        field = f"chains.chain[{index}]"
        c.constraint(
            errors,
            field + ".id",
            bool(chain["id"].strip()) and chain["id"] not in ids,
            "a nonempty unique id",
        )
        ids.add(chain["id"])
        c.constraint(
            errors,
            field + ".versions",
            ("versions" in chain) != ("git" in chain),
            "exactly one of versions or git",
        )
        if "versions" in chain:
            c.constraint(
                errors,
                field + ".versions",
                len(chain["versions"]) >= 2 and all(x.strip() for x in chain["versions"]),
                "at least two nonempty version paths, oldest first",
            )
        if "git" in chain:
            for key in ("repo", "path"):
                c.constraint(
                    errors,
                    field + ".git." + key,
                    bool(chain["git"][key].strip()),
                    "a nonempty path",
                )


def validate(value):
    return c.validate(value, SCHEMA, "chains", _chains)


def build(**fields):
    return c.build(fields, SCHEMA, "chains", _chains)


def load(path):
    return c.load_manifest(path, validate)
