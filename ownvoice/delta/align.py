"""Sentence opcodes with original punctuation retained on each side."""

from difflib import SequenceMatcher

from ownvoice.delta.normalize import normalize
from ownvoice.style.tokenize import sentences


def align(before, after):
    left, right = sentences(before), sentences(after)
    matcher = SequenceMatcher(
        None,
        [normalize(s, alignment=True) for s in left],
        [normalize(s, alignment=True) for s in right],
        autojunk=False,
    )
    for op, a, b, c, d in matcher.get_opcodes():
        # Alignment-only dash/quote equality must still expose actual edits to tags.
        if op == "equal":
            for x, y in zip(left[a:b], right[c:d], strict=True):
                if x != y:
                    yield "replace", [x], [y]
        else:
            yield op, left[a:b], right[c:d]
