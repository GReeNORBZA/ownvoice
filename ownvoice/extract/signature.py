"""In-memory signature fingerprints, isolated by source and year."""

import re
from collections import Counter, defaultdict
from itertools import pairwise


def contact(line):
    return bool(re.search(r"https?://|www\.|\S+@\S+|(?:\d[ ()+.-]*){7}", line))


def valediction(line, valedictions):
    value = line.strip().rstrip(",.!").casefold()
    return next((v.casefold() for v in valedictions if v.casefold() == value), None)


def sig_dash(text):
    lines = text.splitlines()
    cut = next((i for i, line in enumerate(lines) if line in ("--", "-- ")), len(lines))
    return lines[:cut], cut < len(lines)


def learn(records, owner_names, valedictions):
    windows = defaultdict(list)
    owners = {name.casefold() for name in owner_names}
    for record in records:
        windows[record["source"], record["year"]].append(record["text"])
    result = {}
    for window, texts in windows.items():
        occurrences, blocks = Counter(), Counter()
        for text in texts:
            lines, _ = sig_dash(text)
            tail = [line.strip() for line in lines if line.strip()][-8:]
            anchors = [
                i
                for i, line in enumerate(tail)
                if line.casefold() in owners or valediction(line, valedictions)
            ]
            candidates = tail[anchors[0] + 1 :] if anchors else []
            candidates = [
                line
                for line in candidates
                if line.casefold() not in owners
                and not valediction(line, valedictions)
                and (contact(line) or not (re.search(r"[.!?]$", line) and len(line.split()) >= 5))
            ]
            unique = set(candidates)
            occurrences.update(unique)
            # A repeated adjacent pair is the minimum recurring multi-line block.
            blocks.update(set(pairwise(candidates)))
        lexicon = set()
        for line, count in occurrences.items():
            recurring = max((n for pair, n in blocks.items() if line in pair), default=0)
            if count >= max(10, len(texts) * 0.05) and recurring >= count * 0.8:
                lexicon.add(line)
        result[window] = lexicon
    return result


def strip(text, owner_names, valedictions, lexicon=()):
    lines, dashed = sig_dash(text)
    rules = ["sig-dash"] if dashed else []
    owners = {name.casefold() for name in owner_names}
    # Never let a learned suffix consume the valediction or the owner's name.
    anchors = [
        i
        for i, line in enumerate(lines)
        if line.strip().casefold() in owners or valediction(line, valedictions)
    ]
    floor = anchors[-1] + 1 if anchors else 0
    for start in range(floor, len(lines)):
        tail = [line.strip() for line in lines[start:] if line.strip()]
        if tail and sum(line in lexicon for line in tail) >= len(tail) * 0.5:
            lines = lines[:start]
            rules.append("signature-fingerprint")
            break
    # Remove legal paragraphs before the final-six-line valediction search.
    for i, line in enumerate(lines):
        if not valediction(line, valedictions):
            continue
        suffix = "\n".join(lines[i + 1 :])
        for paragraph in suffix.split("\n\n"):
            if len(paragraph.split()) > 30 and re.search(
                r"confidential|intended recipient|disclaimer", paragraph, re.IGNORECASE
            ):
                start = "\n".join(lines).find(paragraph, len("\n".join(lines[: i + 1])))
                lines = "\n".join(lines)[:start].rstrip().splitlines()
                rules.append("legal-disclaimer")
                break
        break
    signoff = None
    for i in range(len(lines) - 1, max(-1, len(lines) - 7), -1):
        signoff = valediction(lines[i], valedictions)
        if signoff:
            following = next((j for j in range(i + 1, len(lines)) if lines[j].strip()), None)
            if following is not None and lines[following].strip().casefold() in owners:
                lines = lines[: following + 1]
            break
    return "\n".join(lines).strip(), signoff, rules
