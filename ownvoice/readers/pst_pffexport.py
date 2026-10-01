"""Parse pffexport item properties without persisting mail identities."""

import re
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser

from ownvoice.extract.body import Rejected
from ownvoice.message import Recipient
from ownvoice.readers import eml

ITEM = re.compile(r"[A-Za-z]+\d{5,}$")


def properties(path):
    if not path.exists():
        return {}
    if not path.stat().st_mode & 0o444:
        raise PermissionError("read PST item properties: mode has no read bits")
    return {
        key.strip().casefold(): value.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def recipient_table(path):
    if not path.exists():
        return []
    if not path.stat().st_mode & 0o444:
        raise PermissionError("read PST recipients: mode has no read bits")
    result = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace")):
        fields = {
            k.strip().casefold(): v.strip()
            for line in block.splitlines()
            if ":" in line
            for k, v in [line.split(":", 1)]
        }
        address = fields.get("email address")
        name = fields.get("display name") or fields.get("recipient display name", "")
        if not address and not name:
            continue
        kind = fields.get("recipient type", "to").casefold()
        kind = {"1": "to", "2": "cc", "3": "bcc"}.get(kind, kind)
        result.append(Recipient(address, name, kind if kind in ("to", "cc", "bcc") else "to"))
    return result


def parse(path, locator, *, headers_only=False):
    if not path.stat().st_mode & 0o444 or not path.stat().st_mode & 0o111:
        raise PermissionError("read PST item directory: mode lacks read or search bits")
    if not headers_only and not re.fullmatch(r"Message\d{5,}", path.name):
        raise Rejected("non_mail_item")
    header_path = path / "InternetHeaders.txt"
    raw = header_path.read_bytes() if header_path.exists() else b""
    mail = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    outlook = properties(path / "OutlookHeaders.txt")
    for key in ("Message-ID", "In-Reply-To", "Subject", "References"):
        if not mail[key] and outlook.get(key.casefold()):
            mail[key] = outlook[key.casefold()]
    if not mail["From"]:
        name = outlook.get("sender name", outlook.get("sent representing name", ""))
        address = outlook.get(
            "sender email address", outlook.get("sent representing email address", "")
        )
        if name or address:
            mail["From"] = f"{name} <{address}>" if "@" in address else name
    message, _ = eml.parse(mail.as_bytes(), locator)
    message.recipients = recipient_table(path / "Recipients.txt")
    for key in ("client submit time", "delivery time"):
        if outlook.get(key):
            value = re.sub(r"(\.\d{6})\d+", r"\1", outlook[key])
            # libpff 20180714 emits US month/day and an explicit UTC suffix.
            for fmt in ("%b %d, %Y %H:%M:%S.%f UTC", "%b %d, %Y %H:%M:%S UTC"):
                try:
                    message.date = datetime.strptime(value, fmt).replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
            break
    if not headers_only:
        plain, html = path / "Message.txt", path / "Message.html"
        mail.clear_content()
        if plain.exists():
            mail.set_content(plain.read_text(encoding="utf-8", errors="replace"))
        if html.exists():
            value = html.read_text(encoding="utf-8", errors="replace")
            if plain.exists():
                mail.add_alternative(value, subtype="html")
            else:
                mail.set_content(value, subtype="html")
        if not plain.exists() and not html.exists():
            raise Rejected("no_text_body")
    return message, mail
