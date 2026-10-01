"""Shared deterministic draft and email tokenisation."""

import re
from functools import cache
from pathlib import Path

from ownvoice.config import DEFAULTS
from ownvoice.errors import DiagnosticError
from ownvoice.extract import greeting as greeting_parser
from ownvoice.extract.signature import valediction

DATA = Path(__file__).resolve().parents[1] / "data"
WORD = re.compile(r"\[[A-Z]+\]|[A-Za-z]+(?:'[A-Za-z]+)?")
LIST = re.compile(r"^\s*(?:[-*+] |\d+\. )")


@cache
def lexicon(name):
    path = DATA / name
    try:
        return tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read bundled style lexicon",
            path,
            str(exc),
            "a readable UTF-8 term list",
            exc,
            "restore the package data and retry the command",
        ) from exc


def normalize(text):
    return text.translate(str.maketrans(dict.fromkeys("’‘ʼ\x92", "'")))


def words(text):
    return WORD.findall(normalize(text))


def prepare(text, *, greeting=None, signoff=None, owner_names=(), valedictions=None):
    text = normalize(text).strip()
    if greeting is None:
        _, greeting, _ = greeting_parser.mask(
            text, {"all", "team", "everyone", "both", "guys", "folks"}
        )
    if signoff is None:
        for line in reversed(text.splitlines()[-6:]):
            signoff = valediction(line, valedictions or DEFAULTS["ingest"]["valedictions"])
            if signoff:
                break
    return (
        greeting_parser.metric_text(text, greeting, signoff, owner_names).strip(),
        greeting,
        signoff,
    )


def sentences(text):
    protected = text
    for abbreviation in sorted(lexicon("abbreviations.txt"), key=len, reverse=True):
        protected = re.sub(
            re.escape(abbreviation),
            lambda m: m[0].replace(".", "\x00"),
            protected,
            flags=re.IGNORECASE,
        )
    protected = re.sub(r"(?<=\d)\.(?=\d)", "\x00", protected)
    lines = protected.splitlines()
    chunks, current = [], ""
    for line in lines:
        line = line.strip()
        if not line:
            if current:
                chunks.append((current, False))
                current = ""
            continue
        if LIST.match(line):
            if current:
                chunks.append((current, False))
                current = ""
            chunks.append((LIST.sub("", line), True))
        elif current and (current[-1:] in ".!?" or re.match(r"[A-Z]", line)):
            chunks.append((current, False))
            current = line
        else:
            current = (current + " " + line).strip()
    if current:
        chunks.append((current, False))
    return [
        part.replace("\x00", ".")
        for chunk, is_list in chunks
        for part in ([chunk] if is_list else re.split(r"(?<=[.!?])\s+", chunk))
        if words(part)
    ]
