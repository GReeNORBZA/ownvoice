"""Deterministic bounded Stage Q sample."""

import hashlib
import re
from collections import defaultdict

from ownvoice.style.tokenize import words


def articles(rows, sample_words, max_record_words):
    selected, total = [], 0
    for original in sorted(rows, key=lambda r: hashlib.sha256(r["record_id"].encode()).digest()):
        row = dict(original)
        if row["word_count"] > max_record_words:
            boundaries = [m.start() for m in re.finditer(r"\n\s*\n", row["text"])]
            end = max(
                (end for end in boundaries if len(words(row["text"][:end])) <= max_record_words),
                default=0,
            )
            row.update(text=row["text"][:end].rstrip(), truncated=True)
            row["word_count"] = len(words(row["text"]))
        if total + row["word_count"] <= sample_words:
            selected.append(row)
            total += row["word_count"]
    return selected


def select(rows, eligible, sample_words, max_record_words):
    groups = defaultdict(list)
    for row in rows:
        if (
            row["source"] in eligible
            and row["strip"]["confidence"] == "high"
            and not row["template"]
            and not row["sensitive"]
            and row["word_count"] <= max_record_words
        ):
            groups[row["source"], row["recipient_class"]].append(row)
    selected = []
    for key in sorted(groups):
        total = 0
        for row in sorted(
            groups[key], key=lambda r: hashlib.sha256(r["record_id"].encode()).digest()
        ):
            if total + row["word_count"] <= sample_words:
                selected.append(row)
                total += row["word_count"]
    return selected
