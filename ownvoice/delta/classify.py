"""Computed operations, edit tags and bounded word substitutions."""

from collections import Counter
from difflib import SequenceMatcher

from ownvoice.style.metrics import phrase_count
from ownvoice.style.tokenize import lexicon, normalize, words


def expanded(text):
    text = normalize(text).lower()
    for contraction, full in (("won't", "will not"), ("can't", "can not"), ("shan't", "shall not")):
        text = text.replace(contraction, full)
    for suffix, full in (
        ("n't", " not"),
        ("'re", " are"),
        ("'ve", " have"),
        ("'ll", " will"),
        ("'m", " am"),
        ("'d", " would"),
        ("'s", " is"),
    ):
        text = text.replace(suffix, full)
    return words(text)


def classify(op, left, right, llm_isms=None):
    before, after = " ".join(left), " ".join(right)
    a, b = expanded(before), expanded(after)
    coverage = sum((Counter(a) & Counter(b)).values()) / len(a) if a else 0
    if len(left) > 1 and len(right) == 1 and coverage >= 0.8:
        op = "join"
    elif len(left) == 1 and len(right) > 1:
        op = "split"
    tags, substitutions = [], []
    if (
        op not in ("replace", "join")
        or SequenceMatcher(
            None, normalize(before).lower(), normalize(after).lower(), autojunk=False
        ).ratio()
        < 0.5
    ):
        return op, tags, substitutions
    a = [w.lower() for w in words(before)]
    b = [w.lower() for w in words(after)]
    changes = [
        x for x in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if x[0] != "equal"
    ]
    inserted = sum(d - c for _, _, _, c, d in changes)
    if op == "join":
        tags.append("join")
        if after.count(",") > before.count(","):
            tags.append("sentence_joined_comma")
    for token in b:
        if (
            "'" in token
            and token not in a
            and len(expanded(token)) > 1
            and " ".join(expanded(token)) in " ".join(expanded(before))
        ):
            tags.append("contraction")
            break
    if before.count("—") > after.count("—"):
        tags.append("em_dash_removed")
        if after.count(" - ") > before.count(" - "):
            tags.append("em_dash_to_spaced_hyphen")
    for tag, terms in (
        ("llm_ism", llm_isms if llm_isms is not None else lexicon("llm-isms.txt")),
        ("hedge", lexicon("hedges.txt")),
    ):
        old = sum(phrase_count(before, t) for t in terms)
        new = sum(phrase_count(after, t) for t in terms)
        if old > new:
            tags.append(tag + "_removed")
        elif new > old and tag == "hedge":
            tags.append("hedge_added")
    for tag, tokens in (
        ("first_person_added", {"i", "me", "my", "mine"}),
        ("second_person_added", {"you", "your", "yours"}),
    ):
        if sum(w in tokens for w in b) > sum(w in tokens for w in a):
            tags.append(tag)
    if b and inserted / len(b) >= 0.30:
        tags.append("scope_broadened")
    original_a, original_b = words(before), words(after)
    for _, i, j, k, l in changes:
        if 0 < j - i <= 4 and 0 < l - k <= 4:
            substitutions.append((" ".join(original_a[i:j]), " ".join(original_b[k:l])))
    return op, sorted(tags), substitutions
