"""Apply a bound diff, retaining every supporting quote and merge action."""

from pathlib import Path

from ownvoice.io import write_json
from ownvoice.qual import chunk, reconcile
from ownvoice.schemas import findings_set, qual_diff


def run(existing_path, add, out):
    diff = qual_diff.validate(chunk.read_json(add))
    digest = (
        chunk.digest(chunk.read_text(existing_path)) if Path(existing_path).exists() else "0" * 64
    )
    value = reconcile.existing(existing_path, diff)
    expected = "A" if not value["passes"] else "B" if value["passes"] == ["A"] else None
    if digest != diff["existing_sha256"] or diff["pass"] != expected:
        raise chunk.problem(
            "merge qual findings",
            existing_path,
            "existing set changed or pass out of order",
            "the reconciled set, A then B only",
            "rerun reconcile against the current set or stop after B",
        )
    by_id = {f["finding_id"]: f for f in value["findings"]}
    for action in ("new", "matched", "borderline"):
        for item in diff[action]:
            row = item if action == "new" else item["finding"]
            if action != "new" and item["finding_id"] not in by_id:
                raise chunk.problem(
                    "merge qual finding",
                    add,
                    "referenced finding absent",
                    "an existing finding id",
                    "regenerate the reconciliation diff",
                )
            identifier = (
                item["finding_id"]
                if action == "matched"
                else chunk.digest(
                    "\0".join(
                        (
                            row["dimension"],
                            row["register"],
                            reconcile.normalized(row["observation"]),
                        )
                    )
                )
            )
            if identifier not in by_id:
                canonical = {
                    k: row[k] for k in ("dimension", "register", "observation", "confidence")
                }
                canonical.update(finding_id=identifier, provenance=[])
                by_id[identifier] = canonical
                value["findings"].append(canonical)
            evidence = {k: row[k] for k in ("record_id", "chunk_id", "verbatim_quote")}
            if evidence not in by_id[identifier]["provenance"]:
                by_id[identifier]["provenance"].append(evidence)
            value["changelog"].append(
                {
                    "pass": diff["pass"],
                    "finding_id": identifier,
                    "action": action,
                    "record_ids": [row["record_id"]],
                }
            )
    value["passes"].append(diff["pass"])
    value["residual"] = len(diff["new"]) if diff["pass"] == "B" else 0
    value["unresolved_failed"] += diff["unresolved_failed"]
    findings_set.validate(value)
    write_json(out, value)
    return value
