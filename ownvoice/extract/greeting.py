"""Greeting spans and sentence-metric exclusions."""

import re

PREFIX = re.compile(
    r"^(?:Hi|Hey|Hello|Heya|Dear|Morning|Good (?:day|morning|afternoon|evening))\b"
    r"\s*([^,\n]{1,40})?,",
    re.IGNORECASE,
)
BARE = re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),")


def mask(text, groups):
    lines = text.splitlines()
    if not lines:
        return text, None, 0
    index = next((i for i, line in enumerate(lines) if line.strip()), 0)
    match = PREFIX.match(lines[index]) or BARE.match(lines[index])
    if not match:
        return text, None, 0
    name = (match[1] or "").strip()
    count = int(bool(name) and name.casefold() not in groups)
    end = match.end()
    if count:
        start, stop = match.span(1)
        lines[index] = lines[index][:start] + "[NAME]" + lines[index][stop:]
        end += len("[NAME]") - (stop - start)
    return "\n".join(lines), lines[index][:end], count


def metric_text(text, greeting, signoff, owner_names):
    """Exclude structural lines only from metrics, retaining them in stored text."""
    owners = {name.casefold() for name in owner_names}
    lines = text.splitlines()
    if greeting and lines:
        lines = lines[1:]
    return "\n".join(
        line
        for line in lines
        if line.strip().casefold() not in owners
        and (not signoff or line.strip().rstrip(",.!").casefold() != signoff.casefold())
    )
