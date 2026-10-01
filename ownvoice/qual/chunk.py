"""Source-pure chunks, private file boundaries and dispatch bookkeeping."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.io import PRIVATE_LINE, write_json, write_marked_text
from ownvoice.schemas import manifest


def problem(operation, identity, observed, expected, next_step, cause=None):
    return DiagnosticError(operation, identity, observed, expected, cause, next_step)


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read qual input",
            path,
            type(exc).__name__,
            "readable UTF-8 text",
            exc,
            "restore the private input path and permissions",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def read_json(path, *, lines=False):
    text = read_text(path)
    try:
        return (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if lines
            else json.loads(text)
        )
    except ValueError as exc:
        raise problem(
            "parse qual input",
            path,
            str(exc),
            "valid JSONL" if lines else "valid JSON",
            "repair the input JSON syntax",
            exc,
        ) from exc


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def is_article(row):
    """Validated article records have truncation metadata; email records do not."""
    return "truncated" in row


def masked(row):
    if is_article(row):
        return row["text"]
    residual = row["scrub"]["residual_capitalised"]
    if not residual:
        return row["text"]
    pattern = (
        r"(?<!\w)(?:"
        + "|".join(re.escape(t) for t in sorted(residual, key=lambda t: (-len(t), t)))
        + r")(?!\w)"
    )
    return re.sub(pattern, "[CAP]", row["text"])


def render(rows):
    text, spans = "", []
    for row in rows:
        text += f"record_id={row['record_id']}\n"
        start = len(text)
        text += masked(row)
        spans.append(
            {
                "record_id": row["record_id"],
                "register": row["recipient_class"],
                "start": start,
                "end": len(text),
            }
        )
        text += "\n\n"
    return text, spans


def estimate(rows):
    text, _ = render(rows)
    # Conservative word estimate plus serialized marker/record-header overhead.
    words = sum(len(masked(row).split()) for row in rows)
    overhead = len(PRIVATE_LINE) + 1 + len(text) - sum(len(masked(row)) for row in rows)
    return math.ceil(words * 1.8) + math.ceil(overhead / 3.5)


def build(rows, pass_name, max_tokens, sample_words, out, prov):
    if pass_name not in ("A", "B") or not 1 <= max_tokens <= 10000 or sample_words < 1:
        raise problem(
            "build qual chunks",
            out,
            "pass or budget outside limits",
            "pass A|B, positive sample words and 1..10000 max tokens",
            "correct --pass, --sample-words and --max-tokens",
        )
    groups = []
    if pass_name == "A":
        for row in rows:
            key = (is_article(row), row["source"], row["recipient_class"])
            if not groups or key != (
                is_article(groups[-1][0]),
                groups[-1][0]["source"],
                groups[-1][0]["recipient_class"],
            ):
                groups.append([])
            groups[-1].append(row)
    else:
        for row in sorted(
            rows, key=lambda r: (r["source"], is_article(r), r["year"] or 0, r["record_id"])
        ):
            if (
                not groups
                or groups[-1][0]["source"] != row["source"]
                or is_article(groups[-1][0]) != is_article(row)
                or estimate(groups[-1] + [row]) > max_tokens
            ):
                groups.append([])
            groups[-1].append(row)
    if any(estimate(group) > max_tokens for group in groups):
        raise problem(
            "build qual chunks",
            out,
            "sample group exceeds token ceiling",
            f"every chunk <= {max_tokens} estimated tokens",
            "lower --sample-words or qual_max_record_words, or raise --max-tokens up to 10000",
        )
    out = Path(out).expanduser().resolve()
    chunks, texts = [], []
    for group in groups:
        text, spans = render(group)
        chunk_id = pass_name + "-" + digest(text)[:16]
        text_path = out.parent / "chunks" / f"{chunk_id}.txt"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "pass": pass_name,
                "source": group[0]["source"],
                "registers": sorted({r["recipient_class"] for r in group}),
                "record_ids": [r["record_id"] for r in group],
                "est_tokens": estimate(group),
                "text_path": str(text_path),
                "status": "pending",
                "attempts": 0,
                "text_sha256": digest(PRIVATE_LINE + "\n" + text),
                "records": spans,
                "raw_paths": [str(out.parent / "raw" / f"{chunk_id}.{i}.jsonl") for i in (1, 2)],
            }
        )
        texts.append(text)
    value = manifest.build(
        **prov,
        **{"pass": pass_name},
        max_tokens=max_tokens,
        sample_words=sample_words,
        chunks=chunks,
    )
    for row, text in zip(chunks, texts, strict=True):
        write_marked_text(row["text_path"], text)
    write_json(out, value)
    return value


def counts(value):
    return {
        status: sum(c["status"] == status for c in value["chunks"])
        for status in ("pending", "done", "failed")
    }


def record_attempt(value, chunk_id, *, valid, retries=2):
    """One combined two-framing dispatch attempt. A valid empty return is valid.

    The caller owns dispatch. This helper enforces its bounded durable state.
    """
    manifest.validate(value)
    selected = [c for c in value["chunks"] if c["chunk_id"] == chunk_id]
    if (
        len(selected) != 1
        or type(valid) is not bool
        or type(retries) is not int
        or retries < 0
        or selected[0]["status"] == "done"
        or selected[0]["attempts"] >= retries + 1
    ):
        raise problem(
            "record qual attempt",
            chunk_id,
            "unknown, complete or exhausted chunk",
            "an unfinished chunk within its retry budget",
            "inspect qual status and retry only eligible chunks",
        )
    row = selected[0]
    row["attempts"] += 1
    row["status"] = "done" if valid else "failed"
    return value


def load(path):
    value = manifest.validate(read_json(path))
    ids = [c["chunk_id"] for c in value["chunks"]]
    if any(n > 1 for n in Counter(ids).values()) or any(
        c["pass"] != value["pass"] for c in value["chunks"]
    ):
        raise problem(
            "load qual manifest",
            path,
            "duplicate chunks or inconsistent pass",
            "unique chunks in the declared pass",
            "regenerate the manifest with qual chunk",
        )
    return value


def listed_paths(path, value):
    """Constrain untrusted manifest targets before reading or deleting anything."""
    root = Path(path).expanduser().resolve().parent
    result = []
    for row in value["chunks"]:
        for category, paths in (("chunks", [row["text_path"]]), ("raw", row.get("raw_paths", []))):
            for name in paths:
                target = Path(name)
                if not target.is_absolute():
                    target = root / target
                if (
                    target.is_symlink()
                    or target.parent.is_symlink()
                    or target.resolve().parent != root / category
                    or (target.exists() and not target.is_file())
                ):
                    raise problem(
                        "resolve qual manifest target",
                        path,
                        "target escapes its private file directory",
                        "regular files directly under chunks/ or raw/ beside the manifest",
                        "regenerate the manifest before reading or cleaning chunks",
                    )
                target = target.resolve()
                if target not in result:
                    result.append(target)
    return result
