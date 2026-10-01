"""RFC 5322 parsing into the shared, memory-only message boundary."""

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

from ownvoice.message import Message, Recipient


def parse(raw, locator):
    mail = BytesParser(policy=policy.default).parsebytes(raw)
    sender = getaddresses([str(mail.get("From", ""))])
    message = Message(
        source_locator=locator,
        recipients=[
            Recipient(address if "@" in address else None, name or address, kind)
            for kind in ("to", "cc", "bcc")
            for name, address in getaddresses([str(v) for v in mail.get_all(kind, [])])
            if name or address
        ],
        date=str(mail["Date"]) if mail["Date"] else None,
        message_id=str(mail["Message-ID"]) if mail["Message-ID"] else None,
        in_reply_to=str(mail["In-Reply-To"]) if mail["In-Reply-To"] else None,
        references=str(mail.get("References", "")).split(),
        subject=str(mail.get("Subject", "")),
        sender_address=sender[0][1] if sender else None,
        sender_name=sender[0][0] if sender else "",
    )
    return message, mail


def messages(paths):
    for index, path in enumerate(paths):
        yield index, path.read_bytes()
