"""Per-text measurements shared with lint and edit-delta."""

import re

from ownvoice.style.tokenize import LIST, lexicon, prepare, sentences, words

METRIC_IDS = (
    "words",
    "sentence_len",
    "paragraph_len",
    "paragraphs",
    "contraction_rate",
    "question_softener_rate",
    "question_rate",
    "exclamation_rate",
    "exclamations_per_email",
    "parenthetical_rate",
    "ellipsis_rate",
    "spaced_dash_rate",
    "emoji_rate",
    "first_person_rate",
    "second_person_rate",
    "list_use",
    "heading_use",
    "flesch_reading_ease",
    "greeting_share",
    "signoff_share",
)


def phrase_count(text, phrase):
    return len(
        re.findall(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", text, re.IGNORECASE)
    )


def syllables(word):
    word = word.lower()
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ye")) and count > 1:
        count -= 1
    return max(1, count)


def heading_matches(text, *, body_source="plain"):
    """Return heading lines, retaining original offsets for lint locations."""
    lines = list(re.finditer(r"^[^\r\n]*(?:\r?\n|$)", text, re.MULTILINE))
    hits = []
    for index, line in enumerate(lines):
        content = line[0].strip()
        atx = re.match(r"#{1,6}[ \t]+", content)
        bold = re.fullmatch(r"(?:\*\*\S(?:.*\S)?\*\*|__\S(?:.*\S)?__)", content)
        # HTML extraction renders b/strong as single stars. In drafts those
        # stars denote italics, so only the recorded HTML source enables them.
        html_bold = body_source == "html" and re.fullmatch(r"\*\S(?:.*\S)?\*", content)
        setext = (
            index + 1 < len(lines)
            and words(content)
            and not LIST.match(content)
            and not content.startswith(">")
            and re.fullmatch(r"(?:=+|-+)", lines[index + 1][0].strip())
        )
        if atx or bold or html_bold or setext:
            hits.append(line)
    return hits


def measure(text, *, softeners=(), body_source="plain", **structure):
    body, greeting, signoff = prepare(text, **structure)
    tokens, split = words(body), sentences(body)
    n, s = len(tokens), len(split)
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if words(p)]

    def rate(count, denominator, scale):
        return count * scale / denominator if denominator else 0

    softeners = (*lexicon("softeners.txt"), *softeners)
    lower = [token.lower() for token in tokens]
    contractions = sum(
        bool(re.search(r"(?:n't|'m|'re|'ve|'ll|'d)$", t))
        or t
        in {"it's", "that's", "there's", "here's", "what's", "who's", "where's", "how's", "let's"}
        for t in lower
    )
    emoji_ranges = [tuple(int(x, 16) for x in line.split("..")) for line in lexicon("emoji.txt")]
    emoji = sum(any(lo <= ord(char) <= hi for lo, hi in emoji_ranges) for char in body)
    emoji += len(re.findall(r":\)|;\)|:-\)|:D", body))
    values = {
        "words": n,
        "sentence_len": rate(n, s, 1),
        "paragraph_len": rate(s, len(paragraphs), 1),
        "paragraphs": len(paragraphs),
        "contraction_rate": rate(contractions, n, 100),
        "question_softener_rate": rate(
            sum(x.endswith("?") and any(phrase_count(x, p) for p in softeners) for x in split),
            s,
            100,
        ),
        "question_rate": rate(sum(x.endswith("?") for x in split), s, 100),
        "exclamation_rate": rate(sum(x.endswith("!") for x in split), s, 100),
        "exclamations_per_email": body.count("!"),
        "parenthetical_rate": rate(
            sum(bool(words(x)) for x in re.findall(r"\([^()]*\)", body)), s, 100
        ),
        "ellipsis_rate": rate(len(re.findall(r"\.\.\.|…", body)), n, 1000),
        "spaced_dash_rate": rate(
            len(re.findall(r"(?<=[A-Za-z\]]) [–—-] (?=[A-Za-z\[])", body)), n, 1000
        ),
        "emoji_rate": emoji,
        "first_person_rate": rate(sum(t in {"i", "me", "my", "mine"} for t in lower), n, 100),
        "second_person_rate": rate(sum(t in {"you", "your", "yours"} for t in lower), n, 100),
        "list_use": int(any(LIST.match(line) for line in body.splitlines())),
        "heading_use": int(bool(heading_matches(body, body_source=body_source))),
        "flesch_reading_ease": 206.835
        - 1.015 * n / s
        - 84.6 * sum(syllables(t) for t in tokens) / n
        if n and s
        else 0,
        "greeting_share": int(bool(greeting)),
        "signoff_share": int(bool(signoff)),
    }
    return values


def quantile(values, fraction):
    if not values:
        return 0
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower = int(index)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (
        index - lower
    )


def distribution(values, gated, fallback=False):
    result = {f"p{p}": quantile(values, p / 100) for p in (10, 25, 50, 75, 90)}
    result.update(
        mean=sum(values) / len(values) if values else 0,
        nonzero_share=sum(x != 0 for x in values) / len(values) if values else 0,
    )
    result["lint_band"] = {f"p{p}": quantile(gated, p / 100) for p in (10, 25, 75, 90)}
    result["lint_band"].update(n_gated=len(gated), fallback_global=fallback)
    return result
