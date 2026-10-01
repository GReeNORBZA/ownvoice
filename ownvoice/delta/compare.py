"""Blind paired-edit scoring."""

from difflib import SequenceMatcher
from pathlib import Path

from ownvoice.delta.normalize import read_text, resolve
from ownvoice.schemas import ac14
from ownvoice.style.tokenize import words


def tokens(text):
    return ["[mask]" if w.startswith("[") else w.lower() for w in words(text)]


def compare(path):
    path = Path(path).expanduser().resolve()
    rows = []
    for brief in ac14.load(path)["brief"]:
        row = {"id": brief["id"]}
        for flow in ("old", "new"):
            draft, final = (
                resolve(path.parent, brief[f"{flow}_{kind}"]) for kind in ("draft", "final")
            )
            row[f"{flow}_ratio"] = SequenceMatcher(
                None,
                tokens(read_text(draft)),
                tokens(read_text(final)),
                autojunk=False,
            ).ratio()
            row[f"{flow}_draft"], row[f"{flow}_final"] = draft.name, final.name
        row["new_wins"] = row["new_ratio"] > row["old_ratio"]
        rows.append(row)
    return {"briefs": rows, "wins": sum(r["new_wins"] for r in rows)}
