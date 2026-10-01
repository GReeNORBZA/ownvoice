"""Step H, inline pre-scan, Step T and mobile footers, in that order."""

import re
from itertools import pairwise

from ownvoice.extract.html2text import Events, normalize, render

HEADER = re.compile(r"^\*?(From|Sent|Date|To|Subject|Cc):\*?\s*", re.IGNORECASE)
FROM = re.compile(r"^\*?From:\*?\s.+", re.IGNORECASE)
ATTRIBUTION = re.compile(r"^On\s.{5,250}\swrote:\s*$", re.IGNORECASE)
INLINE_CUES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:see|find|refer to)\b.{0,40}\b(?:below|in-?line)\b",
        (
            r"\b(?:comments?|answers?|responses?|replies|notes?|feedback|thoughts|input)\b"
            r".{0,40}\b(?:below|in-?line|in (?:red|blue|green|bold|caps|capitals|yellow))\b"
        ),
        r"\bin-?line\b",
    )
)


def html_cut(html):
    events = Events(html).events
    for index, (kind, tag, attrs) in enumerate(events):
        if kind != "start":
            continue
        classes = (attrs.get("class") or "").split()
        rule = None
        if tag == "div" and attrs.get("id") == "divRplyFwdMsg":
            rule = "H1"
        elif tag == "div" and attrs.get("id") == "appendonsend":
            rule = "H2"
        elif {"gmail_quote", "gmail_attr"} & set(classes):
            rule = "H3"
        elif tag == "blockquote" and (attrs.get("type") or "").lower() == "cite":
            rule = "H4"
        elif tag == "div" and "moz-cite-prefix" in classes:
            rule = "H5"
        elif tag == "div" and re.search(
            r"border-top\s*:\s*solid", attrs.get("style") or "", re.IGNORECASE
        ):
            following = "".join(v for k, v, a in events[index + 1 :] if k == "text")[:200]
            if re.search(r"From:", following, re.IGNORECASE):
                rule = "H6"
        elif tag == "blockquote":
            rule = "H7"
        if rule:
            flags = []
            if rule == "H7":
                depth = 1
                for end in range(index + 1, len(events)):
                    k, t, _attrs = events[end]
                    if t == "blockquote":
                        depth += 1 if k == "start" else -1 if k == "end" else 0
                    if depth == 0:
                        if render(events[end + 1 :]).strip():
                            flags.append("inline_html_suspected")
                        break
            cut = index
            if rule == "H1":
                prior = index - 1
                while prior >= 0 and events[prior][0] == "text" and not events[prior][1].strip():
                    prior -= 1
                if prior >= 0 and events[prior][:2] == ("start", "hr"):
                    cut = prior
            return render(events[:cut]), [rule], flags
    return render(events), [], []


def _candidate(lines, index, patterns):
    line = lines[index]
    if re.fullmatch(r"-{2,}\s*Original Message\s*-{2,}\s*", line, re.IGNORECASE):
        return "T1", 1
    if re.fullmatch(
        r"-{2,}\s*Forwarded message\s*-{2,}\s*|Begin forwarded message:\s*", line, re.IGNORECASE
    ):
        return "T2", 1
    if re.fullmatch(r"_{10,}\s*", line) and any(
        FROM.match(x) for x in lines[index + 1 : index + 3]
    ):
        return "T3", 1
    if FROM.match(line):
        headers = {m[1].lower() for x in lines[index + 1 : index + 7] if (m := HEADER.match(x))}
        if len(headers - {"from"}) >= 2:
            end = index + 1
            while end < len(lines) and (not lines[end].strip() or HEADER.match(lines[end])):
                end += 1
            return "T4", end - index
    if ATTRIBUTION.match(line):
        return "T5", 1
    if index + 1 < len(lines) and ATTRIBUTION.match(line + " " + lines[index + 1]):
        return "T5", 2
    if line.startswith(">") and all(not x.strip() or x.startswith(">") for x in lines[index:]):
        return "T6", len(lines) - index
    if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
        return "T7", 1
    return None


def text_cut(text, config):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    rules, flags, inline = [], [], False
    suspected_tail = False
    for index in range(len(lines)):
        candidate = _candidate(lines, index, config["extra_attribution_patterns"])
        if not candidate:
            continue
        rule, count = candidate
        tail = lines[index + count :]
        states = [x.startswith(">") for x in tail if x.strip() and not HEADER.match(x)]
        alternations = sum(a != b for a, b in pairwise(states))
        rules.append(rule)
        if alternations >= 2:
            lines = lines[:index] + lines[index + count :]
            inline = True
        else:
            suspected_tail = rule in ("T1", "T4") and any(
                x.strip() and not x.startswith(">") and not HEADER.match(x) for x in tail
            )
            lines = lines[:index]
        break
    if any(x.startswith(">") for x in lines):
        inline = True
        lines = [x for x in lines if not x.startswith(">")]
    footers = [
        re.compile(re.escape(x) + r"(?:\s*<https?://[^>]+>)?\s*$", re.IGNORECASE)
        for x in config["mobile_footers"]
    ]
    kept = [x for x in lines if not any(p.fullmatch(x.strip()) for p in footers)]
    if len(kept) != len(lines):
        rules.append("mobile-footer")
    if suspected_tail and any(pattern.search(x) for x in kept for pattern in INLINE_CUES):
        flags.append("inline_suspected")
    return normalize("\n".join(kept)), rules, flags, inline
