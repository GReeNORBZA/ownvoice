"""First-mapped recipient cascade, with identity summaries kept in memory."""

import re


def resolve(message, domain_map):
    stages = dict.fromkeys(("smtp", "x500", "names", "unknown"), 0)
    classes, domains, orgs, names = [], set(), set(), set()
    for recipient in message.recipients:
        address = (recipient.address or "").casefold()
        name = recipient.display_name.casefold()
        category, stage, domain, org = None, "unknown", None, None
        if "@" in address and not address.startswith("/o="):
            domain = address.rsplit("@", 1)[1]
            category = domain_map["addresses"].get(address)
            matches = [d for d in domain_map["domains"] if domain == d or domain.endswith("." + d)]
            if category is None and matches:
                category = domain_map["domains"][max(matches, key=len)]
            if category is not None:
                stage = "smtp"
        match = re.search(r"(?:^|/)o=([^/]+)", address, re.IGNORECASE)
        if category is None and match:
            org = match[1]
            category = domain_map.get("x500", {}).get(org)
            if category is not None:
                stage = "x500"
        if category is None and name in domain_map["names"]:
            category, stage = domain_map["names"][name], "names"
        if category is None:
            category = "unknown"
            if domain:
                domains.add(domain)
            elif org:
                orgs.add(org)
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
    return (
        category,
        "4+" if count >= 4 else "2-3" if count >= 2 else "1",
        stages,
        domains,
        names,
        orgs,
    )
