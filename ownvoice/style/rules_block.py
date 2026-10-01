"""Single parser for the editorial rules machine contract."""

import re
import tomllib
from pathlib import Path

from ownvoice.config import CLASSES, MEDIA
from ownvoice.errors import DiagnosticError, ValidationErrors

__all__ = ("MEDIA", "load", "parse")
LIMITS = {"exclamations_max", "emoji_max", "em_dashes_max", "headings_allowed"}


def parse(text, identity="editorial-rules"):
    errors = []

    def check(ok, field, expected, cause=None):
        if not ok:
            errors.append(
                DiagnosticError(
                    "validate editorial rules",
                    f"{identity}:{field}",
                    "missing or invalid value",
                    expected,
                    cause,
                    "correct the ownvoice-rules machine block and retry lint",
                )
            )

    blocks = re.findall(r"^```ownvoice-rules\s*\n(.*?)^```\s*$", text, re.MULTILINE | re.DOTALL)
    check(len(blocks) == 1, "block", "exactly one ownvoice-rules fenced block")
    if errors:
        raise ValidationErrors(errors)
    try:
        data = tomllib.loads(blocks[0])
    except tomllib.TOMLDecodeError as exc:
        check(False, "TOML", "valid TOML syntax", exc)
        raise ValidationErrors(errors) from exc
    check(
        type(data.get("schema_version")) is int and data["schema_version"] == 1,
        "schema_version",
        "integer 1",
    )
    check(
        data.get("spelling", "none") in ("none", "en-US", "en-GB-ise"),
        "spelling",
        "none, en-US or en-GB-ise",
    )
    for key in data.keys() - {"schema_version", "spelling", "ban", "limits", "swearing"}:
        check(False, key, "a documented rules field")
    bans = data.get("ban", [])
    check(isinstance(bans, list), "ban", "an array of ban tables")
    ids = set()
    for i, ban in enumerate(bans if isinstance(bans, list) else []):
        field = f"ban[{i}]"
        check(isinstance(ban, dict), field, "a ban table")
        if not isinstance(ban, dict):
            continue
        for key in ("id", "pattern", "message"):
            check(
                isinstance(ban.get(key), str) and bool(ban[key]),
                f"{field}.{key}",
                "a nonempty string",
            )
        ident = ban.get("id")
        if isinstance(ident, str):
            check(
                bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", ident)) and ident not in ids,
                f"{field}.id",
                "a unique opaque rule id",
            )
            ids.add(ident)
        check(
            ban.get("kind") in ("word", "phrase", "regex", "char"),
            f"{field}.kind",
            "word, phrase, regex or char",
        )
        check(
            ban.get("severity") in ("error", "warn", "info"),
            f"{field}.severity",
            "error, warn or info",
        )
        media = ban.get("media")
        check(
            isinstance(media, list) and bool(media) and all(m in MEDIA for m in media),
            f"{field}.media",
            "a nonempty list of supported media",
        )
        pattern = ban.get("pattern")
        if isinstance(pattern, str):
            check(
                ban.get("kind") != "char" or len(pattern) == 1,
                f"{field}.pattern",
                "one character for a char ban",
            )
            if ban.get("kind") == "regex":
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    check(False, f"{field}.pattern", "a valid regular expression", exc)
        for key in ban.keys() - {"id", "pattern", "message", "kind", "severity", "media"}:
            check(False, f"{field}.{key}", "a documented ban field")

    def limits(value, field, overrides=False):
        check(isinstance(value, dict), field, "a limits table")
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if key == "registers" and not overrides:
                check(isinstance(item, dict), field + ".registers", "a register override table")
                if isinstance(item, dict):
                    for register, override in item.items():
                        check(
                            register in (*CLASSES, "article"),
                            field + ".registers." + register,
                            "a supported register",
                        )
                        limits(override, field + ".registers." + register, True)
            elif key == "headings_allowed":
                check(type(item) is bool, field + "." + key, "a boolean")
            else:
                check(
                    key in LIMITS and type(item) is int and item >= 0,
                    field + "." + key,
                    "a supported nonnegative integer limit",
                )

    for section in ("limits", "swearing"):
        value = data.get(section, {})
        check(isinstance(value, dict), section, "a table")
        for medium, item in value.items() if isinstance(value, dict) else []:
            check(
                medium in (*MEDIA, "never") if section == "swearing" else medium in MEDIA,
                section + "." + medium,
                "a supported medium" + (" or never" if section == "swearing" else ""),
            )
            if section == "limits":
                limits(item, section + "." + medium)
            else:
                check(
                    isinstance(item, list) and all(isinstance(w, str) and w for w in item),
                    section + "." + medium,
                    "a list of nonempty words",
                )
    if errors:
        raise ValidationErrors(errors)
    return data


def load(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read editorial rules",
            path,
            str(exc),
            "readable UTF-8 Markdown",
            exc,
            "correct the rules path or encoding and retry lint",
        ) from exc
    return parse(text, str(path))
