"""Publish-boundary rules, independent of file selection."""

import fnmatch
import ipaddress
import re
from functools import cache
from pathlib import Path, PurePosixPath

from ownvoice.extract.scrub import initial, shipped

ARTIFACT_PATTERNS = (
    "*.pst",
    "*.ost",
    "*.mbox",
    "mbox",
    "*.eml",
    "*.msg",
    "records*.jsonl",
    "rejects*.jsonl",
    "ingest-report*.json",
    "checkpoint.json",
    "profile-stats*.json",
    "stats-llm*.json",
    "exemplars*.json",
    "edit-delta*.json",
    "findings-set*.json",
    "profiled-articles*.jsonl",
    "cross-register*.json",
    "unmapped-domains*.json",
    "domain-map*.toml",
    "chains*.toml",
    "voice-profile*.md",
    "names*.txt",
    "config.toml",
    "Recipients.txt",
    "OutlookHeaders.txt",
    "InternetHeaders.txt",
)
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@([\w-]+(?:\.[\w-]+)+)")
RESERVED = {"example.com", "example.org", "example.net"}
PRIVATE_SECTION = "ownvoice" + ":" + "private-begin"
RELEASE_PATTERNS = (
    re.compile(re.escape(PRIVATE_SECTION)),
    re.compile("#" + r"\d{2,5}\b"),
    re.compile("FIX" + r"-\d{4}-\d{4}\b"),
    re.compile("/" + "home/|/" + "Users/|" + re.escape("C:" + "\\Users\\")),
)
HOST_PORT = re.compile(r"(?<![\w.-])([A-Za-z0-9][A-Za-z0-9.-]*):" + r"(\d{1,5})\b")
ISO_HOUR = re.compile(r"\d{4}-\d\d-\d\dT\d\d")


def host_port(text):
    """True when text holds a host:port pair.

    The host must contain a letter, so clock times (`01:30`) never count, and an ISO
    timestamp's date-hour (`2026-09-25T00`) is not a host. A dotted or hyphenated host,
    or localhost, counts with any port. A bare word counts only with a port of three or
    more digits and no leading zero, so format specs (`i:03`, `severity:6`) and image
    tags (`node:22`) pass while a container name with a service port does not.
    """
    for match in HOST_PORT.finditer(text):
        host, port = match[1], match[2]
        if not any(c.isalpha() for c in host) or ISO_HOUR.fullmatch(host):
            continue
        if "." in host or "-" in host or host.lower() == "localhost":
            return True
        if len(port) >= 3 and not port.startswith("0"):
            return True
    return False


PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10" + ".0.0.0/8", "172" + ".16.0.0/12", "192" + ".168.0.0/16")
)


def artifact_name(path, paths):
    parts = PurePosixPath(path).parts
    if parts[:2] == ("tests", "fixtures"):
        return False
    return (
        any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in ARTIFACT_PATTERNS)
        or ("raw" in parts[:-1] and parts[-1].endswith(".jsonl"))
        or any(part.endswith(".export") for part in parts[:-1])
        or any(
            part == "extract" and "/".join((*parts[: index + 1], ".done")) in paths
            for index, part in enumerate(parts[:-1])
        )
    )


@cache
def common_words():
    return frozenset(shipped("wordlist"))


ALLOW_FILE = "names-allow.txt"


def without_allowed(names, names_path):
    """Drop entries listed in the owner's private names-allow.txt beside names_path.

    The allow file holds harvested display-name tokens the owner reviewed as not
    personal (companies, products, places). It sits next to names.txt, so a
    reingest that regenerates names.txt keeps the review. Matching ignores case;
    blank lines and lines starting with # are ignored. A line with a space is an
    allowed phrase (e.g. "em dash"): the name stays blocked everywhere except
    inside that exact phrase. The result carries phrases for name_hits.
    """
    allow_path = Path(names_path).with_name(ALLOW_FILE)
    if not allow_path.is_file():
        return Names(names)
    entries = [
        line.strip()
        for line in allow_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    allowed = {entry.casefold() for entry in entries if " " not in entry}
    phrases = tuple(entry for entry in entries if " " in entry)
    return Names((name for name in names if name.casefold() not in allowed), phrases)


class Names(tuple):
    """Names to block, plus owner-allowed phrases that may contain them."""

    def __new__(cls, names=(), phrases=()):
        value = super().__new__(cls, names)
        value.phrases = tuple(phrases)
        return value


def name_hits(text, names):
    """Return the names present in text.

    A match is a whole word, and like the scrubber's tokens an n't contraction
    stays one word ("Don't" does not contain "Don"; "Don's" does). A name that
    is also a common word (the scrubber's shipped wordlist, e.g. "Will") counts
    only where the scrubber masks it: exact case and not sentence-initial. A
    name of three letters or fewer must match its exact case ("em dash" and
    "SR&ED" are not "Em" or "Ed"). Longer names match case-insensitively.
    """
    words = common_words()
    for phrase in getattr(names, "phrases", ()):
        # Blank allowed phrases, keeping offsets for the sentence-initial test.
        text = re.sub(
            r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
            lambda m: " " * len(m[0]),
            text,
            flags=re.IGNORECASE,
        )
    hits = []
    for name in names:
        pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w|['’]t\b)"
        if name.casefold() in words:
            found = any(not initial(text, m.start()) for m in re.finditer(pattern, text))
        else:
            flags = 0 if len(name) <= 3 else re.IGNORECASE
            found = re.search(pattern, text, flags) is not None
        if found:
            hits.append(name)
    return hits


def content_rules(text, names, release):
    violations = []
    if any(
        domain.lower() not in RESERVED and not domain.lower().endswith(".example")
        for domain in EMAIL.findall(text)
    ):
        violations.append(3)
    if name_hits(text, names):
        violations.append(4)
    if release:
        private_ip = False
        for candidate in re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            private_ip |= any(address in network for network in PRIVATE_NETWORKS)
        if (
            private_ip
            or host_port(text)
            or any(pattern.search(text) for pattern in RELEASE_PATTERNS)
        ):
            violations.append(5)
    return violations
