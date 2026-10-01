"""readpst's semicolon-delimited display-name recipient headers."""

from email.utils import getaddresses

from ownvoice.message import Recipient
from ownvoice.readers import eml


def parse(raw, locator):
    message, mail = eml.parse(raw, locator)
    recipients = []
    for kind in ("to", "cc", "bcc"):
        for value in [v for key, v in mail.raw_items() if key.casefold() == kind]:
            for token in str(value).split(";"):
                token = token.strip()
                if not token:
                    continue
                if "@" in token:
                    recipients.extend(
                        Recipient(address, name, kind)
                        for name, address in getaddresses([token])
                        if address
                    )
                else:
                    recipients.append(Recipient(None, token.strip('"'), kind))
    message.recipients = recipients
    return message, mail
