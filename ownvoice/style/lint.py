"""Deterministic rules, profile, lexicon and structure findings."""

import re

from ownvoice.style import tells
from ownvoice.style.metrics import heading_matches, measure
from ownvoice.style.tokenize import lexicon, prepare, sentences

# Article shape: length and per-email count metrics do not transfer from
# email to a long-form piece, and headings are allowed in articles. Email paragraphs
# are one or two sentences, so paragraph_len gives way to tells.paragraph_shape.
ARTICLE_SHAPE_SKIPPED = (
    "words",
    "paragraphs",
    "paragraph_len",
    "exclamations_per_email",
    "emoji_rate",
    "heading_use",
)
SUBJECT = re.compile(r"\A(?:[ \t]*\n)*[ \t]*Subject:[^\n]*(?:\n[ \t]*(?=\n|\Z))*\n?", re.IGNORECASE)


def without_subject(text):
    """Drop a leading `Subject:` line and the blank lines after it (drafts only)."""
    return SUBJECT.sub("", text, count=1)


def matches(text, pattern, kind="word"):
    if kind != "regex":
        pattern = re.escape(pattern)
        if kind in ("word", "phrase"):
            pattern = r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])"
    return list(re.finditer(pattern, text, re.IGNORECASE if kind != "char" else 0))


def check(
    text,
    stats,
    rules,
    register,
    medium,
    *,
    source=None,
    minimum=30,
    never_min=50000,
    softeners=(),
    owner_names=(),
    valedictions=None,
):
    findings = []
    structure = {"owner_names": owner_names, "valedictions": valedictions}
    # A subject line is not body text: greeting, sign-off and rate metrics start below it.
    # Rules checks still scan the whole draft with its original line numbers.
    content = without_subject(text)
    values = measure(content, softeners=softeners, **structure)
    body, greeting, signoff = prepare(content, **structure)
    count = len(sentences(body))
    enabled = values["words"] >= 80 and count >= 5

    def add(rule, kind, severity, observed, expected, hint, metric=None, hits=()):
        locations = []
        for hit in hits:
            start = hit.start()
            locations.append(
                {
                    "line": text.count("\n", 0, start) + 1,
                    "col": start - text.rfind("\n", 0, start),
                    # Lint has no correspondent lexicon. Suppress draft text rather
                    # than risk publishing identities, including partial regex hits.
                    # Single punctuation/symbol findings retain their useful glyph.
                    "excerpt": hit[0] if len(hit[0]) == 1 and not hit[0].isalnum() else "",
                }
            )
        findings.append(
            {
                "rule_id": rule,
                "check_kind": kind,
                "severity": severity,
                "metric": metric,
                "observed": observed,
                "expected": expected,
                "locations": locations,
                "fix_hint": hint,
            }
        )

    for ban in rules.get("ban", []):
        if medium in ban["media"]:
            hits = matches(text, ban["pattern"], ban["kind"])
            if hits:
                add(
                    "rules." + ban["id"],
                    "rules",
                    ban["severity"],
                    len(hits),
                    0,
                    ban["message"],
                    hits=hits,
                )
    limits = rules.get("limits", {}).get(medium, {})
    limits = {**limits, **limits.get("registers", {}).get(register, {})}
    skipped = set()
    emoji_ranges = [tuple(int(x, 16) for x in line.split("..")) for line in lexicon("emoji.txt")]
    emoji_pattern = (
        "[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in emoji_ranges) + r"]|:\)|;\)|:-\)|:D"
    )
    headings = heading_matches(text)
    specs = {
        "exclamations_max": (
            text.count("!"),
            ("exclamation_rate", "exclamations_per_email"),
            matches(text, "!", "char"),
        ),
        "emoji_max": (
            measure(text, greeting="", signoff="")["emoji_rate"],
            ("emoji_rate",),
            list(re.finditer(emoji_pattern, text)),
        ),
        "em_dashes_max": (text.count("—"), (), matches(text, "—", "char")),
        "headings_allowed": (values["heading_use"], ("heading_use",), headings),
    }
    for key, (observed, metrics, hits) in specs.items():
        if key not in limits or (key == "headings_allowed" and limits[key]):
            continue
        skipped.update(metrics)
        maximum = int(limits[key])
        if observed > maximum:
            add(
                "rules." + key,
                "rules",
                "error",
                observed,
                maximum,
                f"reduce {key.removesuffix('_max')} to {maximum} for {medium}",
                hits=hits,
            )
    spelling = rules.get("spelling", "none")
    if spelling != "none":
        for pair in lexicon("variant-pairs.txt"):
            _, british, american = pair.split()
            wrong, right = (american, british) if spelling == "en-GB-ise" else (british, american)
            hits = matches(text, wrong)
            if hits:
                add("rules.spelling", "rules", "error", wrong, right, f"use {right}", hits=hits)
    tiers = rules.get("swearing", {})
    allowed = set(tiers.get(medium, []))
    banned = set(tiers.get("never", []))
    vocabulary = {word for words in tiers.values() for word in words}
    for word in sorted(banned | (vocabulary - allowed)):
        hits = matches(text, word)
        if hits:
            add(
                "rules.swearing",
                "rules",
                "error",
                word,
                f"allowed tier for {medium}",
                "remove this word",
                hits=hits,
            )

    if not enabled:
        add(
            "stats.short_draft",
            "stats",
            "info",
            f"{values['words']} words, {count} sentences",
            "at least 80 words and 5 sentences",
            "use a longer draft to enable rate checks",
        )
    else:
        fallback_reported = False
        thin_reported = False
        checked = 0
        if register == "article":
            skipped.update(ARTICLE_SHAPE_SKIPPED)
            add(
                "stats.article_shape",
                "stats",
                "info",
                ", ".join(ARTICLE_SHAPE_SKIPPED),
                "not compared for article drafts",
                "length, per-email counts and headings follow the brief and editorial rules",
            )
        for metric, observed in values.items():
            # C7 persists distributions at four decimals. Compare at that same precision.
            observed = round(observed, 4)
            if metric in skipped:
                continue
            selected = source
            if selected is None and any(
                row["register"] == register
                and row["metric"] == metric
                and row["status"] == "diverging"
                for row in stats["contrast"]
            ):
                selected = stats["current_source"]
            registers = (
                stats["by_source"][selected]["registers"] if selected else stats["registers"]
            )
            band = registers[register]["metrics"][metric]["lint_band"]
            # Article bands never fall back to the _global short-email band.
            # A thin article band, or one a pre-rev-4 profile already replaced with
            # _global's, disables that check instead (insufficient data below).
            if register == "article":
                if band["fallback_global"]:
                    band = {**band, "n_gated": 0}
            elif band["fallback_global"] or band["n_gated"] < minimum:
                band = registers["_global"]["metrics"][metric]["lint_band"]
                if not fallback_reported:
                    add(
                        "stats.fallback_global",
                        "stats",
                        "info",
                        register,
                        "_global gated band",
                        "collect more gated records for this register",
                    )
                    fallback_reported = True
            if band["n_gated"] < minimum:
                if not thin_reported:
                    add(
                        "stats.insufficient_data",
                        "stats",
                        "info",
                        band["n_gated"],
                        minimum,
                        "collect more gated records to enable stats checks",
                    )
                    thin_reported = True
                continue
            checked += 1
            if not band["p10"] <= observed <= band["p90"]:
                add(
                    "stats." + metric,
                    "stats",
                    "warn",
                    observed,
                    f"p10–p90 {band['p10']}–{band['p90']}; target p25–p75 {band['p25']}–{band['p75']}"
                    + (f"; source {selected}" if selected else "; merged"),
                    f"adjust {metric} toward the target band",
                    metric,
                )
        enabled = checked > 0
    global_stats = stats["registers"]["_global"]
    never = set(global_stats["llm_ism_never_hit"])
    for word in sorted(never | {row[0] for row in global_stats["llm_ism_hits"]}):
        hits = matches(text, word, "phrase")
        if hits:
            severity = (
                "error"
                if word in never and global_stats["never_hit_basis_words"] >= never_min
                else "warn"
            )
            add(
                "lexicon.llm_ism",
                "lexicon",
                severity,
                word,
                "owner-attested wording",
                "replace with a concrete familiar expression",
                hits=hits,
            )
    # Tier B AI-writing thresholds: the register's own profiled p90/p10.
    thresholds = stats["registers"][register].get("ai_tells")
    if thresholds is None:
        add(
            "ai.not_profiled",
            "stats",
            "info",
            "no ai_tells in profile-stats.json",
            "a profile built by this ownvoice version",
            "rerun ownvoice profile to enable AI-writing threshold checks",
        )
    else:
        observed_tells = tells.measure(body)
        thin = []
        for metric, row in sorted(thresholds.items()):
            observed = observed_tells.get(metric)
            if observed is None:
                continue
            if row["threshold"] is None:
                thin.append(metric)
                continue
            observed = round(observed, 4)
            crossed = (
                observed > row["threshold"]
                if row["direction"] == "max"
                else observed < row["threshold"]
            )
            if crossed:
                bound = "p90" if row["direction"] == "max" else "p10"
                if row["basis"] == "article_shape":
                    bound = "article-shape limit"
                add(
                    "ai." + metric,
                    "stats",
                    "warn",
                    observed,
                    f"{'at most' if row['direction'] == 'max' else 'at least'} {row['threshold']} "
                    f"({bound}, basis {row['basis']}, n {row['n']})",
                    tells.HINTS[metric],
                    metric,
                )
        if thin:
            add(
                "ai.insufficient_data",
                "stats",
                "info",
                ", ".join(thin),
                f"at least {minimum} profiled records per metric",
                "collect more records for this register to enable these AI-writing checks",
            )
    shape = tells.paragraph_shape(body) if register == "article" else None
    if shape is not None:
        average, single = round(shape[0], 4), round(shape[1], 4)
        if average < tells.ARTICLE_PARAGRAPH_MEAN_MIN or single > tells.ARTICLE_SINGLE_SENTENCE_MAX:
            add(
                "structure.paragraph_fragmentation",
                "structure",
                "warn",
                f"mean {average} sentences per paragraph, {single} single-sentence",
                f"mean at least {tells.ARTICLE_PARAGRAPH_MEAN_MIN}, single-sentence share at "
                f"most {tells.ARTICLE_SINGLE_SENTENCE_MAX} (article-shape limit)",
                "join paragraphs that continue one line of thought; keep a one-sentence "
                "paragraph only for deliberate emphasis",
            )
    selected_register = (stats["by_source"][source]["registers"] if source else stats["registers"])[
        register
    ]
    if medium == "email":
        if values["heading_use"] and selected_register["metrics"]["heading_use"]["p90"] == 0:
            add(
                "structure.heading",
                "structure",
                "warn",
                1,
                0,
                "remove email headings",
                hits=headings,
            )
        for key, present in (("greetings", greeting), ("signoffs", signoff)):
            forms = selected_register[key]
            metric = "greeting_share" if key == "greetings" else "signoff_share"
            if not present and selected_register["metrics"][metric]["mean"] >= 0.6:
                add(
                    "structure." + key,
                    "structure",
                    "warn",
                    "absent",
                    "present",
                    "add "
                    + (
                        max(forms, key=lambda form: form["share"])["form"]
                        if forms
                        else "a " + metric.removesuffix("_share")
                    ),
                )
    return values["words"], count, enabled, findings


def summary(report):
    counts = report["summary"]
    lines = [
        (
            f"lint: {report['draft']} (register {report['register']}, medium {report['medium']}, "
            f"{report['word_count']} words): {counts['error']} error, {counts['warn']} warnings"
        )
    ]
    for severity in ("error", "warn", "info"):
        for finding in report["findings"]:
            if finding["severity"] != severity:
                continue
            locations = "; ".join(
                f"line {p['line']} col {p['col']}: {p['excerpt']!r}" for p in finding["locations"]
            )
            lines.append(
                f"  {severity:6} {finding['rule_id']}  {locations or finding['observed']} "
                f"({finding['expected']})  → {finding['fix_hint']}"
            )
    return "\n".join(lines)
