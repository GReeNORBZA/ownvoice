"""Eligible-only n-grams ranked against the other recipient registers."""

import math
from collections import Counter

from ownvoice.style.tokenize import lexicon, words


def counts(records, size):
    function = set(lexicon("function-words.txt"))
    known = set(lexicon("wordlist.txt"))
    result = Counter()
    for record in records:
        tokens = words(record["text"])
        for i in range(len(tokens) - size + 1):
            span = tokens[i : i + size]
            if any(t[0].isupper() and t.lower() not in known for t in span):
                continue
            lower = [t.lower() for t in span]
            if all(t in function or t.startswith("[") for t in lower):
                continue
            result[" ".join(lower)] += 1
    return result


def keyness(a, total_a, b, total_b):
    if not total_a or not total_b:
        return 0.0
    observed = (a, total_a - a, b, total_b - b)
    expected = (
        (a + b) * total_a / (total_a + total_b),
        (total_a + total_b - a - b) * total_a / (total_a + total_b),
        (a + b) * total_b / (total_a + total_b),
        (total_a + total_b - a - b) * total_b / (total_a + total_b),
    )
    return 2 * sum(o * math.log(o / e) for o, e in zip(observed, expected) if o and e)


def ranked(records, others):
    result = {}
    for name, size in (("bi", 2), ("tri", 3)):
        own, other = counts(records, size), counts(others, size)
        rows = [
            [phrase, count, keyness(count, sum(own.values()), other[phrase], sum(other.values()))]
            for phrase, count in own.items()
            if count >= 5
        ]
        result[name] = sorted(rows, key=lambda r: (-r[2], -r[1], r[0]))[:40]
    return result
