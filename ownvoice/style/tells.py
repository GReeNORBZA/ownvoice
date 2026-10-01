"""Tier B AI-writing threshold metrics, regex and counting only.

Each metric maps a prepared body (greeting, sign-off and owner-name lines already
removed, as for the 9.1 metrics) to a number, or to None when the text is too
short for that metric to mean anything. `profile` turns each register's values
into a one-sided threshold (the register's own p90, or p10 for `min` metrics);
`lint` warns when a draft crosses it. No threshold is hardcoded to any owner's
corpus: the only constants are metric definitions, the documented `FLOORS` and
the article-shape heading limit.
"""

import re
from statistics import mean, pstdev

from ownvoice.style.tokenize import lexicon, normalize, sentences, words

# metric id -> direction: "max" warns above the threshold, "min" warns below it.
METRICS = {
    "sentence_cv": "min",
    "ing_tail_rate": "max",
    "tricolon_rate": "max",
    "tricolon_paragraphs": "max",
    "negation_contrast_rate": "max",
    "ai_vocab_rate": "max",
    "staccato_runs": "max",
    "anaphora_runs": "max",
    "aphorism_ratio": "max",
    "heading_density": "max",
    "bold_first_bullets": "max",
    "pivot_paragraphs": "max",
    "connector_rate": "max",
    "balanced_openers": "max",
    "magic_adverb_rate": "max",
    "hedge_stacks": "max",
    "service_phrases": "max",
}
HINTS = {
    "sentence_cv": "vary sentence length with the content; avoid uniform rhythm",
    "ing_tail_rate": "cut trailing ', -ing' glosses; state the point in its own sentence",
    "tricolon_rate": "list only the items you have; drop a third item added for rhythm",
    "tricolon_paragraphs": "keep at most one list of three per paragraph",
    "negation_contrast_rate": "say what it is; drop 'not X but Y' and 'rather than' framing",
    "ai_vocab_rate": "replace stock AI vocabulary with plain, specific words",
    "staccato_runs": "merge runs of short, same-length sentences",
    "anaphora_runs": "vary sentence openings; avoid three in a row with the same word",
    "aphorism_ratio": "end sections and paragraphs on the last fact, not a maxim",
    "heading_density": "use fewer headings; let sections run longer",
    "bold_first_bullets": "drop bold labels at the start of bullets",
    "pivot_paragraphs": "remove one-line bridging paragraphs; name the next subject instead",
    "connector_rate": "cut sentence-initial connectors (Moreover, Furthermore, However)",
    "balanced_openers": "state the position; drop 'While X, Y' balancing openers",
    "magic_adverb_rate": "cut mood adverbs (deeply, fundamentally, arguably)",
    "hedge_stacks": "keep one hedge at most ('may', not 'may potentially')",
    "service_phrases": "keep at most one service phrase ('feel free', 'don't hesitate')",
}
# Definitional minimum thresholds, not calibrations: one service phrase alone is
# ordinary email, only a stack of two or more is the tell.
FLOORS = {"service_phrases": 1}
# Article shape: headings are allowed in articles, at most one per 300 words
# (sections of about 300 words or more). Email corpora cannot calibrate this
# because extraction loses formatting, so the article register uses this limit.
ARTICLE_HEADING_DENSITY_MAX = 1.0
# Article shape: an article paragraph carries a line of thought. Email paragraphs
# (the only measured basis) are one or two sentences, so the article register uses
# owner-set fragmentation limits instead of the email paragraph_len band: a mean of at
# least 3 sentences per prose paragraph and at most 15% single-sentence paragraphs,
# checked once a draft has ARTICLE_PARAGRAPHS_MIN prose paragraphs.
ARTICLE_PARAGRAPH_MEAN_MIN = 3.0
ARTICLE_SINGLE_SENTENCE_MAX = 0.15
ARTICLE_PARAGRAPHS_MIN = 4
# Tier B metrics that the spec defines but this module does not implement.
NOT_IMPLEMENTED = {
    "syntactic_templates": "needs a part-of-speech tagger (parked)",
    "recap_overlap": "lexical overlap saturates on genuine articles (parked)",
}

MIN_WORDS = 150
HEADING = re.compile(r"^\s{0,3}(?:#{1,6}[ \t]+\S|\*\*[^*\n]+\*\*\s*$|__[^_\n]+__\s*$)")
BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+")
BOLD_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+\*\*[^*\n]+\*\*")
TRIPLE = re.compile(
    r"\b\w+(?:\s\w+){0,3},\s+\w+(?:\s\w+){0,3},?\s+(?:and|or)\s+\w+(?:\s\w+){0,3}\b"
)
ING_TAIL = re.compile(r",\s+([a-z]+ing)\b")
ING_STOP = frozenset(
    [
        "including",
        "according",
        "regarding",
        "concerning",
        "following",
        "pending",
        "during",
        "morning",
        "evening",
        "nothing",
        "something",
        "anything",
        "everything",
        "thing",
        "meeting",
        "building",
        "training",
        "funding",
        "pricing",
        "planning",
        "testing",
        "reporting",
        "marketing",
        "banking",
        "billing",
        "licensing",
        "hosting",
        "networking",
        "being",
        "setting",
        "heading",
        "booking",
        "listing",
        "processing",
        "accounting",
        "engineering",
        "logging",
        "monitoring",
        "onboarding",
        "patching",
        "scanning",
        "phishing",
        "bring",
        "spring",
        "string",
        "king",
        "ring",
        "sing",
        "wing",
    ]
)
NEGATION_CONTRAST = re.compile(
    r"\bnot\s+[^.!?\n,;]{1,40},?\s+but\s+|\brather than\b", re.IGNORECASE
)
CONNECTOR = re.compile(
    r"^(?:Moreover|Furthermore|Additionally|Notably|Importantly|Interestingly|However|Also"
    r"|Therefore|Thus|Consequently|Similarly|Meanwhile|Instead|Indeed)\b"
)
BALANCED = re.compile(r"^(?:While|Although|Though|Whilst)\b[^,]{5,80},")
HEDGE_STACK = re.compile(
    r"\b(?:could|may|might|can)\s+(?:potentially|possibly|eventually|perhaps)\b", re.IGNORECASE
)
SERVICE = (
    re.compile(r"\b(?:don't|do not) hesitate to\b", re.IGNORECASE),
    re.compile(
        r"\bfeel free to (?:reach out|contact|let me know|get in touch|call)\b", re.IGNORECASE
    ),
    re.compile(
        r"\blet me know if (?:there's|there is|you have|you need) anything else\b", re.IGNORECASE
    ),
    re.compile(r"\bI hope this helps\b", re.IGNORECASE),
    re.compile(r"\bwould you like me to\b", re.IGNORECASE),
)
PRONOUNS = frozenset(["i", "we", "you", "he", "she", "they", "it"])
DEMONSTRATIVES = PRONOUNS | frozenset(["this", "that", "these", "those"])
ABSTRACT = frozenset(
    [
        "truth",
        "trust",
        "power",
        "cost",
        "habit",
        "silence",
        "clarity",
        "kindness",
        "value",
        "risk",
        "security",
        "culture",
        "judgement",
        "judgment",
        "discipline",
        "attention",
        "work",
        "time",
        "speed",
        "simplicity",
        "leverage",
        "control",
        "fear",
        "confidence",
        "evidence",
        "process",
        "people",
    ]
)
APHORISM_VERB = re.compile(
    r"\b(?:is|are|in the end|ultimately|after all|at the end of the day)\b", re.IGNORECASE
)
MASK = re.compile(r"\[[A-Z]+\]")


def _blocks(body):
    return [b for b in re.split(r"\n\s*\n", body) if b.strip()]


def _prose(block):
    """A block's prose: its lines that are neither headings nor bullets."""
    lines = [
        line for line in block.splitlines() if not HEADING.match(line) and not BULLET.match(line)
    ]
    return "\n".join(lines).strip()


def _runs(values, test, minimum=3):
    """Count maximal runs of at least `minimum` consecutive items where test(prev, item)."""
    count, length = 0, 1
    for index in range(1, len(values) + 1):
        if index < len(values) and test(values[index - 1], values[index]):
            length += 1
            continue
        count += length >= minimum
        length = 1
    return count


def aphoristic(sentence):
    tokens = words(sentence)
    if not 4 <= len(tokens) <= 15 or not sentence.rstrip().endswith("."):
        return False
    if re.search(r"\d", sentence) or MASK.search(sentence):
        return False
    if tokens[0].lower() in DEMONSTRATIVES:
        return False
    if any(token[:1].isupper() for token in tokens[1:]):
        return False
    lower = {token.lower() for token in tokens}
    return bool(lower & ABSTRACT) and bool(APHORISM_VERB.search(sentence))


def measure(body):
    """Tier B values for one prepared body; None marks a metric that does not apply."""
    body = normalize(body)
    blocks = _blocks(body)
    prose_blocks = [p for p in (_prose(b) for b in blocks) if words(p)]
    para_sentences = [sentences(p) for p in prose_blocks]
    flat = [s for group in para_sentences for s in group]
    lengths = [len(words(s)) for s in flat]
    n = len(words(body))
    prose_text = "\n\n".join(prose_blocks)
    long_enough = n >= MIN_WORDS

    def per(count, scale):
        return count * scale / n if long_enough and n else None

    def lexicon_hits(name):
        terms = lexicon(name)
        return sum(
            len(re.findall(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", body, re.IGNORECASE))
            for t in terms
        )

    lines = body.splitlines()
    bullets = [line for line in lines if BULLET.match(line)]
    headings = [line for line in lines if HEADING.match(line)]

    # Section finals (text with headings) or multi-sentence paragraph finals.
    if headings:
        sections, current = [], []
        for line in lines:
            if HEADING.match(line):
                sections.append(current)
                current = []
            else:
                current.append(line)
        sections.append(current)
        finals = []
        for section in sections:
            prose = [p for p in (_prose(b) for b in _blocks("\n".join(section))) if words(p)]
            split = [s for p in prose for s in sentences(p)]
            if split:
                finals.append(split[-1])
    else:
        finals = [group[-1] for group in para_sentences if len(group) >= 2]
    prose_words = [len(words(p)) for p in prose_blocks]
    pivots = sum(
        1
        for i in range(1, len(prose_blocks) - 1)
        if prose_words[i] <= 12
        and prose_blocks[i].rstrip()[-1:] in ".!?"
        and not re.search(r"\d", prose_blocks[i])
        and prose_words[i - 1] > 25
        and prose_words[i + 1] > 25
    )
    first_words = [words(s)[0].lower() for s in flat]
    return {
        "sentence_cv": pstdev(lengths) / mean(lengths) if len(lengths) >= 8 else None,
        "ing_tail_rate": (
            sum(m[1] not in ING_STOP for m in ING_TAIL.finditer(prose_text)) * 100 / len(flat)
            if len(flat) >= 5
            else None
        ),
        "tricolon_rate": per(len(TRIPLE.findall(prose_text)), 1000),
        "tricolon_paragraphs": sum(len(TRIPLE.findall(p)) >= 2 for p in prose_blocks),
        "negation_contrast_rate": per(len(NEGATION_CONTRAST.findall(prose_text)), 1000),
        "ai_vocab_rate": per(lexicon_hits("ai-vocabulary.txt"), 500),
        "staccato_runs": sum(_staccato(group) for group in para_sentences),
        "anaphora_runs": _runs(
            first_words, lambda a, b: a == b and b not in PRONOUNS and a not in PRONOUNS
        ),
        "aphorism_ratio": sum(map(aphoristic, finals)) / len(finals) if finals else None,
        "heading_density": per(len(headings), 300),
        "bold_first_bullets": (
            sum(bool(BOLD_BULLET.match(line)) for line in bullets) / len(bullets)
            if len(bullets) >= 3
            else None
        ),
        "pivot_paragraphs": pivots,
        "connector_rate": per(sum(bool(CONNECTOR.match(s)) for s in flat), 1000),
        "balanced_openers": per(sum(bool(BALANCED.match(s)) for s in flat), 1000),
        "magic_adverb_rate": per(lexicon_hits("magic-adverbs.txt"), 1000),
        "hedge_stacks": len(HEDGE_STACK.findall(body)),
        "service_phrases": sum(bool(p.search(body)) for p in SERVICE),
    }


def paragraph_shape(body):
    """(mean sentences per prose paragraph, single-sentence share) or None when too few.

    Headings and bullet lines are not prose, so they neither count as paragraphs nor
    shorten the paragraph they sit in.
    """
    counts = [len(sentences(p)) for p in (_prose(b) for b in _blocks(normalize(body))) if words(p)]
    if len(counts) < ARTICLE_PARAGRAPHS_MIN:
        return None
    return mean(counts), sum(c == 1 for c in counts) / len(counts)


def _staccato(group):
    """Runs of 3+ consecutive sentences of <= 6 words whose lengths differ by <= 2."""
    lengths = [len(words(s)) for s in group]
    count, start = 0, 0
    while start < len(lengths):
        end = start
        while (
            end < len(lengths)
            and lengths[end] <= 6
            and max(lengths[start : end + 1]) - min(lengths[start : end + 1]) <= 2
        ):
            end += 1
        if end - start >= 3:
            count += 1
            start = end
        else:
            start += 1
    return count
