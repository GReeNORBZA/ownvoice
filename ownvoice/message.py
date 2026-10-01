"""Unscrubbed, in-memory reader boundary. Never serialize this type."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Recipient:
    address: str | None
    display_name: str
    type: Literal["to", "cc", "bcc"]


@dataclass
class Message:
    source_locator: str
    recipients: list[Recipient] = field(default_factory=list)
    date: datetime | str | None = None
    delivery_date: datetime | str | None = None
    message_class: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    subject: str = ""
    plain_body: str | None = None
    html_body: str | None = None
    sender_address: str | None = None
    sender_name: str = ""
