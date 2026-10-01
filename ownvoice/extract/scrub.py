"""Deterministic, shared name/pattern scrubber and private lexicon collector."""

import hashlib
import re
from email.utils import getaddresses
from importlib.resources import files
from pathlib import Path

from ownvoice.errors import DiagnosticError
from ownvoice.extract import greeting
from ownvoice.extract.body import Rejected, decode
from ownvoice.extract.html2text import Events, render
from ownvoice.extract.strip import HEADER, _candidate

TOKEN = re.compile(r"\b[A-Z][a-zA-Z]+(?:[-'][A-Z]?[a-z]+)*\b")
EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"(?:https?://|www\.)[^\s<>]+|\b(?:[a-zA-Z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>]*)?")
PHONE = re.compile(r"(?<!\w)\+?\d(?:[\d ()+.-]*\d)?(?!\w)")
NUMBER = re.compile(r"\b\d{6,}\b")
MONEY = re.compile(
    r"(?:[$£€]\s*\d[\d,.]*(?:\s*(?:million|billion|thousand))?"
    r"|\b(?:USD|CAD|GBP|EUR|ZAR)\s+\d[\d,.]*"
    r"|\b\d[\d,.]*\s+(?:dollars|pounds|euros|rand|USD|CAD|GBP|EUR|ZAR)\b)",
    re.IGNORECASE,
)


def read_terms(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read scrub lexicon",
            path,
            str(exc),
            "a readable UTF-8 term list",
            exc,
            "correct the configured lexicon path or encoding and retry ingest",
        ) from exc
    return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}


def shipped(name):
    return read_terms(str(files("ownvoice").joinpath("data", name + ".txt")))


def sensitive_terms(setting):
    terms = set() if setting == "none" else shipped("sensitive")
    if setting not in ("none", "builtin"):
        terms.update(read_terms(setting))
    terms = {term.casefold() for term in terms}
    return terms, {
        "source": setting if setting in ("none", "builtin") else "builtin+file",
        "sha256": hashlib.sha256("\n".join(sorted(terms)).encode()).hexdigest(),
    }


def owner_tokens(owner_names):
    return {token.casefold() for name in owner_names for token in TOKEN.findall(name)}


def name_tokens(values, owner_names):
    owners = owner_tokens(owner_names)
    return {
        token
        for value in values
        for token in TOKEN.findall(value)
        if token.casefold() not in owners
    }


def display_names(values):
    # Bare names in Outlook header blocks/attributions have no SMTP address.
    return [
        name or (address if "@" not in address else "")
        for value in values
        for name, address in (getaddresses([value]) if "@" in value else [(value, "")])
    ]


def harvest(mail, owner_names, config):
    """Collect all-folder headers plus T4/T5 names before any quoted text is cut.

    PST adapters can feed parsed header messages through this same collector.
    Undecodable bodies contribute headers only; the parse pass records their rejection.
    """
    values = display_names(
        [str(v) for key in ("From", "To", "Cc", "Bcc", "Reply-To") for v in mail.get_all(key, [])]
    )
    for part in mail.walk():
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        try:
            text, _ = decode(part)
        except Rejected:
            continue  # Not a silent ingest failure: process_source persists the reject.
        if part.get_content_type() == "text/html":
            text = render(Events(text).events)
        lines = text.splitlines()
        for index in range(len(lines)):
            candidate = _candidate(lines, index, config["extra_attribution_patterns"])
            if candidate and candidate[0] == "T4":
                headers = [
                    HEADER.sub("", line)
                    for line in lines[index : index + candidate[1]]
                    if re.match(r"^\*?(From|To|Cc):", line, re.IGNORECASE)
                ]
                values.extend(display_names(headers))
            elif candidate and candidate[0] == "T5":
                attribution = " ".join(lines[index : index + candidate[1]])
                # Standard attribution dates precede the final comma-delimited name.
                attribution = re.sub(r"\s+wrote:\s*$", "", attribution, flags=re.IGNORECASE)
                attribution = attribution.rsplit(",", 1)[-1]
                attribution = re.sub(r"^On\s+", "", attribution)
                values.extend(display_names([attribution]))
    return name_tokens(values, owner_names)


def initial(text, start):
    prefix = text[:start].rstrip()
    return not prefix or prefix[-1] in ".!?\n" or not text[:start].split("\n")[-1].strip()


def scrub(text, names, owner_names=(), *, deny_terms=(), allowlist=(), wordlist=None, groups=None):
    words = shipped("wordlist") if wordlist is None else wordlist
    groups = shipped("groups") if groups is None else groups
    text, detected, count = greeting.mask(text, groups)
    counts = dict.fromkeys(
        ("greeting_names", "lexicon_names", "emails", "phones", "urls", "numbers"), 0
    )
    counts["greeting_names"] = count
    owners = owner_tokens(owner_names)

    def replace_name(match):
        token = match[0]
        if (
            token in names
            and token.casefold() not in owners
            and (token.casefold() not in words or not initial(text, match.start()))
        ):
            counts["lexicon_names"] += 1
            return "[NAME]"
        return token

    # Protect complete addresses/URLs from name substitutions that would break patterns.
    protected = [(m.start(), m.end()) for pattern in (EMAIL, URL) for m in pattern.finditer(text)]
    text = TOKEN.sub(
        lambda m: m[0] if any(a <= m.start() < b for a, b in protected) else replace_name(m), text
    )
    for term in sorted(deny_terms, key=lambda x: (-len(x), x)):
        text, n = re.subn(
            r"(?<!\w)" + re.escape(term) + r"(?!\w)", "[NAME]", text, flags=re.IGNORECASE
        )
        counts["lexicon_names"] += n
    text, counts["emails"] = EMAIL.subn("[EMAIL]", text)
    text, counts["urls"] = URL.subn(
        lambda m: "[URL]" + (m[0][-1] if m[0][-1] in ".,!?" else ""), text
    )
    money = [(m.start(), m.end()) for m in MONEY.finditer(text)]

    def number(match):
        if any(a <= match.start() < b for a, b in money):
            return match[0]
        value = match[0]
        if sum(c.isdigit() for c in value) >= 7 and re.search(r"[ ()+.-]", value):
            counts["phones"] += 1
            return "[PHONE]"
        value, n = NUMBER.subn("[NUM]", value)
        counts["numbers"] += n
        return value

    text = PHONE.sub(number, text)
    allowed = set(allowlist) | {"NAME", "ORG", "EMAIL", "URL", "PHONE", "NUM"}
    counts["residual_capitalised"] = sorted(
        {
            m[0]
            for m in TOKEN.finditer(text)
            if m[0] not in allowed
            and m[0].casefold() not in owners
            and (m[0].casefold() not in words or (initial(text, m.start()) and m[0] in names))
        }
    )
    # Greeting is a projection of the already scrubbed text, never a second identity surface.
    if detected:
        detected = text.splitlines()[0].split(",", 1)[0] + ","
    return text, detected, counts


def sensitive(text, terms):
    return any(
        re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) for term in terms
    )
