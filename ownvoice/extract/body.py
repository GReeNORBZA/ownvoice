"""MIME selection, decoding and ordered body extraction; no persistence."""

import re

from ownvoice.extract.strip import html_cut, text_cut

APOSTROPHES = str.maketrans({c: "'" for c in "\u2019\u2018\u02bc\u0092"})


class Rejected(Exception):
    def __init__(self, reason, cause=None):
        self.reason = reason
        self.cause = cause
        super().__init__(reason)


def word_count(text):
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))


def decode(part, *, mboxrd=False):
    charset = (part.get_content_charset() or "us-ascii").lower()
    if charset in ("iso-8859-1", "latin-1", "us-ascii"):
        charset = "cp1252"
    payload = part.get_payload(decode=True) or b""
    try:
        text = payload.decode(charset, errors="replace")
    except LookupError as exc:
        raise Rejected("decode_error", exc) from exc
    flags = ["decode_error_partial"] if "\ufffd" in text else []
    if text and text.count("\ufffd") / len(text) > 0.05:
        raise Rejected("decode_error")
    if mboxrd:
        text = re.sub(r"^>(?=>*From )", "", text, flags=re.MULTILINE)
    return text.translate(APOSTROPHES), flags


def extract(mail, config, *, mboxrd=False):
    types = {part.get_content_type() for part in mail.walk()}
    if "text/calendar" in types or "multipart/report" in types:
        raise Rejected("non_mail_item")
    if types & {
        "application/pkcs7-mime",
        "application/x-pkcs7-mime",
        "multipart/encrypted",
        "application/pgp-encrypted",
    }:
        raise Rejected("encrypted")
    html = mail.get_body(preferencelist=("html",))
    plain = mail.get_body(preferencelist=("plain",))
    if html is None and plain is None:
        raise Rejected("no_text_body")
    results = {}
    for name, part in (("html", html), ("plain", plain)):
        if part is None:
            continue
        text, flags = decode(part, mboxrd=mboxrd)
        if "-----BEGIN PGP MESSAGE-----" in text:
            raise Rejected("encrypted")
        if re.match(r"^When:.*\nWhere:", text, re.IGNORECASE) or "*~*~*~*" in text:
            raise Rejected("non_mail_item")
        rules = []
        if name == "html":
            text, rules, html_flags = html_cut(text)
            flags.extend(html_flags)
        text, text_rules, text_flags, inline = text_cut(text, config)
        results[name] = (text, rules + text_rules, flags + text_flags, inline)
    source = "html" if html is not None else "plain"
    text, rules, flags, inline = results[source]
    if len(results) == 2:
        h, p = (word_count(results[k][0]) for k in ("html", "plain"))
        if min(h, p) > 10 and abs(h - p) / max(h, p) > 0.5:
            flags.append("body_mismatch")
    if not text:
        raise Rejected("empty_after_strip")
    if re.search(r"wrote:|^From:|^>|^Subject:", text, re.IGNORECASE | re.MULTILINE):
        flags.append("residual_marker")
    if word_count(text) > 3000:
        flags.append("long_body")
    return text, {
        "body_source": source,
        "rules_fired": rules,
        "flags": flags,
        "inline_reply": inline,
        "confidence": "low" if set(flags) - {"decode_error_partial"} else "high",
    }
