"""Frequency tables with a separate, explicit phrase-eligible input."""

from collections import Counter

from ownvoice.style.metrics import phrase_count
from ownvoice.style.tokenize import lexicon, words


def frequencies(records, phrase_records, llm_isms):
    tokens = Counter(t.lower() for r in records for t in words(r["text"]))
    total = sum(tokens.values())
    phrase_text = "\n".join(r["text"] for r in phrase_records)
    phrase_words = sum(len(words(r["text"])) for r in phrase_records)

    def rates(name):
        return {
            p: phrase_count(phrase_text, p) * 1000 / phrase_words if phrase_words else 0
            for p in lexicon(name)
        }

    def forms(key):
        counts = Counter(r[key] for r in phrase_records if r[key])
        return [
            {"form": form, "count": count, "share": count / len(phrase_records)}
            for form, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        ]

    spelling = dict.fromkeys(("ise", "ize", "our", "or"), 0)
    pairs = []
    for line in lexicon("variant-pairs.txt"):
        group, british, american = line.split()
        spelling[group] += tokens[british]
        spelling[{"ise": "ize", "our": "or"}[group]] += tokens[american]
        pairs.extend([word, tokens[word]] for word in (british, american) if tokens[word])
    text = "\n".join(r["text"] for r in records)
    hits = [[p, phrase_count(text, p)] for p in llm_isms]
    return {
        "greetings": forms("greeting"),
        "signoffs": forms("signoff"),
        "spelling": {**spelling, "top_pairs": sorted(pairs, key=lambda x: (-x[1], x[0]))},
        "function_words": {
            p: tokens[p] * 1000 / total if total else 0 for p in lexicon("function-words.txt")
        },
        "discourse_markers": rates("discourse-markers.txt"),
        "hedges": rates("hedges.txt"),
        "llm_ism_hits": sorted([x for x in hits if x[1]], key=lambda x: (-x[1], x[0])),
        "llm_ism_never_hit": sorted(p for p, n in hits if not n),
        "never_hit_basis_words": total,
        "dash_chars": {
            "em": text.count("—") * 1000 / total if total else 0,
            "en": text.count("–") * 1000 / total if total else 0,
        },
    }
