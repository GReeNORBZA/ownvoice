"""Stable identity deduplication and explicit source/merge template passes."""

from collections import Counter


def unique(records):
    seen, kept, duplicates = set(), [], []
    for record in records:
        if record["record_id"] in seen:
            duplicates.append(record)
        else:
            seen.add(record["record_id"])
            kept.append(record)
    return kept, duplicates


def templates(records):
    keys = [" ".join(record["text"].split()).casefold() for record in records]
    counts = Counter(keys)
    for record, key in zip(records, keys):
        record["template"] = counts[key] >= 3
    return records


def merge(records):
    kept, duplicates = unique(records)
    # Copies keep merged template flags independent of per-source flags.
    return templates([dict(record) for record in kept]), len(duplicates)
