"""Recipient classification, thread and local date metadata."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


def recipients(message, domain_map):
    stages = dict.fromkeys(("smtp", "x500", "names", "unknown"), 0)
    classes, domains, names = [], set(), set()
    for recipient in message.recipients:
        address = (recipient.address or "").casefold()
        name = recipient.display_name.casefold()
        category, stage, domain = None, "unknown", None
        if "@" in address:
            domain = address.rsplit("@", 1)[1]
            category = domain_map["addresses"].get(address)
            if category is None:
                matches = [
                    d for d in domain_map["domains"] if domain == d or domain.endswith("." + d)
                ]
                if matches:
                    category = domain_map["domains"][max(matches, key=len)]
            if category is not None:
                stage = "smtp"
        if category is None and name in domain_map["names"]:
            category, stage = domain_map["names"][name], "names"
        if category is None:
            category = "unknown"
            if domain:
                domains.add(domain)
            elif name:
                names.add(name)
        stages[stage] += 1
        classes.append(category)
    count = len(message.recipients)
    category = (
        "group"
        if count >= domain_map["group_threshold"]
        else next((c for c in domain_map["precedence"] if c in classes), "unknown")
    )
    return category, "4+" if count >= 4 else "2-3" if count >= 2 else "1", stages, domains, names


def date_fields(message, source):
    try:
        date = (
            message.date
            if isinstance(message.date, datetime)
            else parsedate_to_datetime(message.date)
        )
        if date.tzinfo is None:
            date = date.replace(tzinfo=ZoneInfo(source["timezone"]))
        local = date.astimezone(ZoneInfo(source["timezone"]))
        return (
            local.year,
            local.weekday(),
            ("night", "morning", "afternoon", "evening")[local.hour // 6],
        )
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None, None, None


def thread_position(message, rules, config):
    subject = message.subject.casefold()
    if subject.startswith(("fw:", "fwd:")) or "T2" in rules:
        return "forward"
    if (
        message.in_reply_to
        or message.references
        or any(subject.startswith(p.casefold()) for p in config["reply_prefixes"])
        or set(rules) & {"T1", "T3", "T4", "T5", "T6", *(f"H{i}" for i in range(1, 8))}
    ):
        return "reply"
    return "new"
