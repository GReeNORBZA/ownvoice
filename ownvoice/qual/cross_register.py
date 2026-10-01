"""Deterministic single-linkage selection from grounded canonical findings."""

from ownvoice.io import write_json
from ownvoice.qual import chunk, reconcile
from ownvoice.schemas import cross_register, findings_set


def select(findings):
    components = []
    for row in sorted(findings, key=lambda f: f["finding_id"]):
        linked = [
            group
            for group in components
            if any(
                other["dimension"] == row["dimension"]
                and reconcile.observation_comparison(other["observation"], row["observation"])[0]
                != "new"
                for other in group
            )
        ]
        for group in linked:
            components.remove(group)
        components.append([row, *(other for group in linked for other in group)])
    ranked = []
    for group in components:
        registers = sorted({row["register"] for row in group})
        if len(registers) < 2:
            continue
        ids = sorted(row["finding_id"] for row in group)
        support = {p["record_id"] for row in group for p in row["provenance"]}
        evidence = sorted(
            (
                {"register": row["register"], **{k: p[k] for k in ("record_id", "verbatim_quote")}}
                for row in group
                for p in row["provenance"]
            ),
            key=lambda p: (p["record_id"], p["register"], p["verbatim_quote"]),
        )
        quotes, counts = [], {}
        for quote in evidence:
            register = quote["register"]
            if counts.get(register, 0) < 2 and quote not in quotes:
                quotes.append(quote)
                counts[register] = counts.get(register, 0) + 1
            if len(quotes) == 6:
                break
        value = {
            "group_id": chunk.digest("\0".join(ids)),
            "dimension": group[0]["dimension"],
            "registers": registers,
            "finding_ids": ids,
            "quotes": quotes,
        }
        ranked.append(((-len(registers), -len(support), value["group_id"]), value))
    return [value for _, value in sorted(ranked, key=lambda item: item[0])[:20]]


def run(path, out):
    findings = findings_set.validate(chunk.read_json(path))
    value = cross_register.build(groups=select(findings["findings"]))
    write_json(out, value)
    return value["groups"]
