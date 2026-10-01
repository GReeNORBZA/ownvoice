"""Deterministic, source-balanced verbatim examples."""

import hashlib
from collections import Counter
from statistics import quantiles

from ownvoice.config import CLASSES
from ownvoice.errors import DiagnosticError
from ownvoice.schemas import exemplars as schema
from ownvoice.style.tokenize import words


def apportion(counts, total, floors):
    """Largest remainder, reserving floors first and respecting pool capacity."""
    quotas = list(floors)
    if sum(quotas) > total:
        raise DiagnosticError(
            "allocate exemplar quota",
            "[profile].exemplars_min/exemplars_max",
            f"required floors total {sum(quotas)}, quota {total}",
            "a quota large enough for every stratum and source floor",
            None,
            "raise exemplars_min and exemplars_max to accommodate the source floors",
        )
    remaining = min(total, sum(counts)) - sum(quotas)
    while remaining:
        active = [i for i, count in enumerate(counts) if quotas[i] < count]
        weight = sum(counts[i] for i in active)
        shares = {i: remaining * counts[i] for i in active}
        added = {i: min(counts[i] - quotas[i], shares[i] // weight) for i in active}
        for i, count in added.items():
            quotas[i] += count
            remaining -= count
        for i in sorted(active, key=lambda i: (-(shares[i] % weight), i)):
            if remaining and quotas[i] < counts[i]:
                quotas[i] += 1
                remaining -= 1
    return quotas


def shingles(text):
    tokens = [word.lower() for word in words(text)]
    return {tuple(tokens[i : i + 5]) for i in range(len(tokens) - 4)}


def summarize(register):
    items = register["items"]
    register["selection"].update(
        selected=len(items),
        words=sum(r["word_count"] for r in items),
        by_source=dict(sorted(Counter(r["source"] for r in items).items())),
    )


def select_register(rows, eligible_sources, options):
    minimum = options["exemplars_min"]
    cap = options["exemplar_words_per_register"]
    lengths = [r["word_count"] for r in rows]
    cuts = quantiles(lengths, n=3, method="inclusive") if len(lengths) > 1 else lengths * 2
    cuts = cuts or [0, 0]
    bounds = [min(lengths, default=0), *cuts, max(lengths, default=0)]
    pools, all_counts = [[], [], []], [0, 0, 0]
    for row in rows:
        stratum = sum(row["word_count"] > cut for cut in cuts)
        all_counts[stratum] += 1
        if (
            row["source"] in eligible_sources
            and row["strip"]["confidence"] == "high"
            and not row["strip"]["inline_reply"]
            and not row["template"]
            and not row["sensitive"]
            and not row["scrub"]["residual_capitalised"]
            and 8 <= row["word_count"] <= cap // minimum
        ):
            pools[stratum].append(row)
    counts = list(map(len, pools))
    eligible = sum(counts)
    result = {
        "low_confidence": bool(eligible_sources) and eligible < minimum,
        "selection": {
            "criterion": "hash-spaced within length tertiles",
            "status": "ok" if eligible_sources else "no_llm_eligible_source",
            "strata": [
                {
                    "boundaries": bounds[i : i + 2],
                    "eligible": counts[i],
                    "eligibility_rate": counts[i] / all_counts[i] if all_counts[i] else 0,
                }
                for i in range(3)
            ],
            "coverage": "full" if all(counts) else "partial",
            "eligible": eligible,
        },
        "items": [],
    }
    thin = eligible < minimum
    target = min(eligible, max(minimum, min(options["exemplars_max"], eligible // 25)))
    sources = [sorted({r["source"] for r in pool}) for pool in pools]
    floors = [max(min(2, counts[i]), len(sources[i])) for i in range(3)]
    quotas = counts if thin else apportion(counts, target, floors)
    schedules = []
    for pool, labels, quota in zip(pools, sources, quotas, strict=True):
        groups = [
            sorted(
                (r for r in pool if r["source"] == label),
                key=lambda r: hashlib.sha256(r["record_id"].encode()).hexdigest(),
            )
            for label in labels
        ]
        sizes = list(map(len, groups))
        shares = sizes if thin else apportion(sizes, quota, [1] * len(groups))
        # Interleave source slots too, so a cap cannot consume only the larger era.
        schedule = []
        for i in range(max(shares, default=0)):
            for group, share in zip(groups, shares, strict=True):
                if i < share:
                    schedule.append((group, (2 * i + 1) * len(group) // (2 * share)))
        schedules.append(schedule)
    used, picked_shingles, total_words = set(), [], 0
    for i in range(max(map(len, schedules), default=0)):
        for stratum, schedule in enumerate(schedules):
            if i >= len(schedule):
                continue
            group, start = schedule[i]
            for offset in range(len(group)):
                row = group[(start + offset) % len(group)]
                if row["record_id"] in used:
                    continue
                candidate = shingles(row["text"])
                if not thin and any(
                    len(candidate & prior) / len(candidate | prior) > 0.6
                    for prior in picked_shingles
                    if candidate | prior
                ):
                    continue
                if len(result["items"]) >= minimum and total_words + row["word_count"] > cap:
                    summarize(result)
                    return result
                used.add(row["record_id"])
                picked_shingles.append(candidate)
                total_words += row["word_count"]
                result["items"].append(
                    {
                        **{
                            key: row[key]
                            for key in (
                                "record_id",
                                "source",
                                "word_count",
                                "thread_position",
                                "year",
                                "text",
                            )
                        },
                        "stratum": stratum,
                        "pick_rank": len(result["items"]),
                    }
                )
                break
    summarize(result)
    return result


def build(rows, eligible_sources, options, provenance):
    # Chain-final article paragraphs come from edit-delta chains. No duplicate email exemplars.
    return schema.build(
        **provenance,
        registers={
            name: select_register(
                [r for r in rows if r["recipient_class"] == name], eligible_sources, options
            )
            for name in (*CLASSES, "article")
        },
    )
