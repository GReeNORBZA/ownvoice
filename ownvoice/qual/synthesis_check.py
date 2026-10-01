"""Mechanical checks for a private synthesis, before publication to its profile dir."""

import contextlib
import io
import re
import tempfile
from pathlib import Path

from ownvoice.cli import main as ownvoice
from ownvoice.guard.rules import name_hits, without_allowed
from ownvoice.qual.chunk import problem, read_text


def quoted_spans(text):
    """The synthesis contract uses double quotes or Markdown block quotes.

    Also recognize paired single/curly quotes and inline code, so alternate
    Markdown spelling cannot hide an invented quotation. Apostrophes inside
    words are not opening quotation marks.
    """
    spans = []
    for pattern in (
        r'"([^"\n]+)"',
        r"“([^”]+)”",
        r"‘([^’]+)’",
        r"(?<!\w)'([^'\n]+)'(?!\w)",
        r"`([^`\n]+)`",
        r"(?m)^\s*>\s?(.*)$",
    ):
        spans.extend(re.findall(pattern, text))
    return list(dict.fromkeys(span for span in spans if span.strip()))


def check(draft, names_file, sources, *, quoted_text=None):
    """Check the complete unmarked draft with guard and all authored quotations.

    quoted_text excludes only the code-copied rules/provenance/contrast/hash
    blocks, whose fidelity is guaranteed by assembly, never model generation.
    Return nothing on success, otherwise list offending spans in the exception.
    The caller retains this diagnostic privately, not in content-free progress.
    """
    names = without_allowed(
        [line.strip() for line in read_text(names_file).splitlines() if line.strip()], names_file
    )
    offending_names = name_hits(draft, names)
    absent = [
        span
        for span in quoted_spans(draft if quoted_text is None else quoted_text)
        if not any(span in source for source in sources)
    ]
    # The publish guard intentionally rejects private markers and artefact
    # filenames. It sees an unmarked draft under a neutral temporary filename.
    with tempfile.TemporaryDirectory(prefix="ownvoice-synthesis-check-") as directory:
        path = Path(directory) / "draft.md"
        path.touch(mode=0o600)
        path.write_text(draft, encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            status = ownvoice(["guard", "--tree", directory, "--names-file", str(names_file)])
    if status or offending_names or absent:
        raise problem(
            "check profile synthesis",
            "draft.md",
            f"guard exit={status}; offending names={offending_names!r}; absent quotes={absent!r}",
            "guard exit 0, no names and every quote in masked source text",
            "correct the listed spans and regenerate the profile",
            output.getvalue() or None,
        )
