"""Mechanical grounding against digest-bound, masked record spans."""

import math
import re
from difflib import SequenceMatcher
from pathlib import Path

from ownvoice.errors import ValidationErrors
from ownvoice.io import PRIVATE_LINE, write_json, write_jsonl
from ownvoice.qual import chunk
from ownvoice.schemas import common, finding, qual_report


def best_window(quote, text, threshold):
    """Best character ratio among contiguous whole-word windows of <=25 words.

    Length bounds discard only windows whose theoretical maximum cannot pass.
    Exact substrings are returned immediately, including punctuation and [CAP].
    """
    if not quote.strip():
        return 0.0, ""
    if quote in text:
        return 1.0, quote
    tokens = list(re.finditer(r"\S+", text))
    best, span = 0.0, ""
    for i, first in enumerate(tokens):
        for last in tokens[i : i + 25]:
            candidate = text[first.start() : last.end()]
            if 2 * min(len(quote), len(candidate)) / (len(quote) + len(candidate)) < threshold:
                continue
            ratio = SequenceMatcher(None, quote, candidate, autojunk=False).ratio()
            if ratio > best:
                best, span = ratio, candidate
    return best, span


def report_path(path):
    return Path(str(path) + ".report.json")


def run(manifest_path, findings_path, out, threshold):
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise chunk.problem(
            "ground qual findings",
            "--threshold",
            "threshold outside limits",
            "a finite ratio greater than 0 and at most 1",
            "correct --threshold",
        )
    value = chunk.load(manifest_path)
    chunk.listed_paths(manifest_path, value)
    lookup = {}
    for row in value["chunks"]:
        if row["status"] != "done":
            continue
        path = Path(row["text_path"])
        if not path.is_absolute():
            path = Path(manifest_path).resolve().parent / path
        text = chunk.read_text(path)
        if (
            not text.startswith(PRIVATE_LINE + "\n")
            or chunk.digest(text) != row.get("text_sha256")
            or "records" not in row
        ):
            raise chunk.problem(
                "ground qual chunk",
                path,
                "marker, digest or record spans do not match",
                "the original marked chunk with its recorded digest and spans",
                "regenerate chunks and rerun the pass",
            )
        text = text[len(PRIVATE_LINE) + 1 :]
        spans = row["records"]
        if (
            [s["record_id"] for s in spans] != row["record_ids"]
            or len({s["record_id"] for s in spans}) != len(spans)
            or any(
                s["end"] < s["start"]
                or s["end"] > len(text)
                or s["register"] not in row["registers"]
                for s in spans
            )
        ):
            raise chunk.problem(
                "ground qual chunk",
                path,
                "record span map inconsistent with chunk",
                "one valid text span per listed record",
                "regenerate chunks and rerun the pass",
            )
        lookup[row["chunk_id"]] = {
            s["record_id"]: (s["register"], text[s["start"] : s["end"]]) for s in spans
        }
    kept, dropped = [], []
    for index, raw in enumerate(chunk.read_json(findings_path, lines=True)):
        try:
            item = finding.build(**raw) if isinstance(raw, dict) else finding.validate(raw)
        except ValidationErrors:
            dropped.append({"index": index, "reason": "invalid_finding_schema"})
            continue
        target = lookup.get(item["chunk_id"], {}).get(item["record_id"])
        if target is None:
            dropped.append({"index": index, "reason": "record_not_in_completed_chunk"})
            continue
        register, text = target
        ratio, span = best_window(item["verbatim_quote"], text, threshold)
        if ratio < threshold:
            dropped.append({"index": index, "reason": "quote_not_grounded"})
            continue
        item.update(register=register, verbatim_quote=span)
        kept.append(finding.validate(item))
    write_jsonl(out, kept)
    states = chunk.counts(value)
    report = qual_report.build(
        **{k: value[k] for k in common.PROVENANCE if k in value},
        **{"pass": value["pass"]},
        kept=len(kept),
        dropped=dropped,
        unresolved_failed=states["failed"],
        pending=states["pending"],
        grounded_sha256=chunk.digest(chunk.read_text(out)),
    )
    write_json(report_path(out), report)
    return report
