"""Deterministic local statistics and the restricted LLM projection."""

import hashlib
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import quantiles

from ownvoice import provenance
from ownvoice.config import CLASSES, load_config
from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors
from ownvoice.extract import dedup
from ownvoice.extract.scrub import sensitive, sensitive_terms
from ownvoice.io import write_json, write_jsonl
from ownvoice.layout import Layout
from ownvoice.schemas import (
    article_records,
    edit_delta,
    extract_stamp,
    ingest_report,
    profile_stats,
    records,
)
from ownvoice.schemas import exemplars as exemplar_schema
from ownvoice.style import budget, contrast, exemplars, ngrams, tables, tells
from ownvoice.style.metrics import METRIC_IDS, distribution, measure, quantile
from ownvoice.style.project import project
from ownvoice.style.tokenize import DATA, prepare, sentences, words


def read_input(path, *, lines=False):
    try:
        text = path.read_text(encoding="utf-8")
        return (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if lines
            else json.loads(text)
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise DiagnosticError(
            "read profile input",
            path,
            type(exc).__name__,
            "readable UTF-8 JSONL" if lines else "readable UTF-8 JSON",
            exc,
            "restore the private ingest output and retry profile",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def read_lexicon(path):
    try:
        return tuple(
            sorted(
                {
                    line.strip().lower()
                    for line in Path(path).read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")
                }
            )
        )
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read profile lexicon",
            path,
            str(exc),
            "a readable UTF-8 term list",
            exc,
            "correct the configured lexicon path or encoding and retry profile",
        ) from exc


def select_records(rows):
    seen, result = set(), []
    for row in sorted(rows, key=lambda r: r["record_id"]):
        if row["strip"]["confidence"] == "low":
            continue
        if row["template"]:
            key = " ".join(row["text"].split()).casefold()
            if key in seen:
                continue
            seen.add(key)
        result.append(row)
    return result


def tell_thresholds(selected, tell_values, minimum):
    """Tier B thresholds from the selection's own distribution."""
    result = {}
    for metric, direction in tells.METRICS.items():
        observed = [
            tell_values[r["record_id"]][metric]
            for r in selected
            if tell_values[r["record_id"]][metric] is not None
        ]
        threshold = None
        if len(observed) >= minimum:
            threshold = (
                max(quantile(observed, 0.9), tells.FLOORS.get(metric, 0))
                if direction == "max"
                else quantile(observed, 0.1)
            )
        result[metric] = {
            "direction": direction,
            "threshold": threshold,
            "p50": quantile(observed, 0.5),
            "n": len(observed),
            "basis": "register",
        }
    return result


def aggregate(rows, config, eligible, llm_isms, softeners):
    rows = select_records(rows)
    values, gates, tell_values = {}, set(), {}
    for row in rows:
        structure = {
            "greeting": row["greeting"],
            "signoff": row["signoff"],
            "owner_names": config["owner"]["names"],
            "valedictions": config["ingest"]["valedictions"],
        }
        value = measure(
            row["text"], body_source=row["strip"]["body_source"], softeners=softeners, **structure
        )
        values[row["record_id"]] = value
        body = prepare(row["text"], **structure)[0]
        tell_values[row["record_id"]] = tells.measure(body)
        if value["words"] >= 80 and len(sentences(body)) >= 5:
            gates.add(row["record_id"])
    minimum = config["profile"]["thin_register_min"]
    safe = [
        r
        for r in rows
        if r["source"] in eligible and not r["sensitive"] and not r["scrub"]["residual_capitalised"]
    ]
    global_gated = [r for r in rows if r["record_id"] in gates]

    def metrics(selected):
        gated = [r for r in selected if r["record_id"] in gates]
        fallback = len(gated) < minimum
        if fallback:
            gated = global_gated
        return {
            metric: distribution(
                [values[r["record_id"]][metric] for r in selected],
                [values[r["record_id"]][metric] for r in gated],
                fallback,
            )
            for metric in METRIC_IDS
        }

    registers = {}
    for name in (*CLASSES, "_global"):
        selected = rows if name == "_global" else [r for r in rows if r["recipient_class"] == name]
        phrases = safe if name == "_global" else [r for r in safe if r["recipient_class"] == name]
        others = [] if name == "_global" else [r for r in safe if r["recipient_class"] != name]
        registers[name] = {
            "n": len(selected),
            "low_confidence": len(selected) < minimum,
            "derived_from": None,
            "metrics": metrics(selected),
            **tables.frequencies(selected, phrases, llm_isms),
            "ngrams": ngrams.ranked(phrases, others),
            "ai_tells": tell_thresholds(selected, tell_values, minimum),
            "by_thread_position": {
                position: {
                    "n": sum(r["thread_position"] == position for r in selected),
                    "metrics": metrics([r for r in selected if r["thread_position"] == position]),
                }
                for position in ("new", "reply", "forward")
            },
        }
    for name in CLASSES:
        for metric, row in registers[name]["ai_tells"].items():
            fallback = registers["_global"]["ai_tells"][metric]
            if row["threshold"] is None and fallback["threshold"] is not None:
                row.update(threshold=fallback["threshold"], basis="_global")
    return registers


def long_emails(rows):
    """The long stratum: records above the upper length tertile of all usable records.

    Tertile boundaries use statistics.quantiles (n=3, inclusive; a record
    equal to a boundary belongs to the lower stratum), over the _global selection.
    """
    counted = select_records(rows)
    lengths = [r["word_count"] for r in counted]
    cut = quantiles(lengths, n=3, method="inclusive")[1] if len(lengths) > 1 else 0
    return [r for r in counted if r["word_count"] > cut], cut


def anchor_article(register, long_register, minimum):
    """Article targets never use the _global short-email band.

    A metric whose band or Tier B threshold is thin, or fell back to _global, takes
    the long-email register's instead. Headings follow the article-shape limit.
    """
    for metric, value in register["metrics"].items():
        band = value["lint_band"]
        if long_register is not None and (band["fallback_global"] or band["n_gated"] < minimum):
            value["lint_band"] = deepcopy(long_register["metrics"][metric]["lint_band"])
        # The band now comes from the article basis or the long emails, never _global.
        value["lint_band"]["fallback_global"] = False
    for metric, row in register["ai_tells"].items():
        if long_register is None:
            row["basis"] = "long_emails"
        elif row["threshold"] is None or row["basis"] == "_global":
            source = long_register["ai_tells"][metric]
            row.update({key: source[key] for key in ("threshold", "p50", "n")})
            row["basis"] = "long_emails"
    register["ai_tells"]["heading_density"].update(
        threshold=tells.ARTICLE_HEADING_DENSITY_MAX, basis="article_shape"
    )
    return register


def paragraph_rows(rows):
    """Paragraph units of email records for article exemplars (article register)."""
    units = []
    for row in rows:
        for index, text in enumerate(p.strip() for p in re.split(r"\n\s*\n", row["text"])):
            if not words(text):
                continue
            units.append(
                {
                    **row,
                    "record_id": hashlib.sha256(
                        (row["record_id"] + str(index)).encode()
                    ).hexdigest()[:16],
                    "text": text,
                    "word_count": len(words(text)),
                }
            )
    return units


def apply_cutoff(rows, cutoff):
    """Keep records provably dated before the cutoff (year granularity, conservative)."""
    if cutoff is None:
        return rows, 0, 0
    year = date.fromisoformat(cutoff).year
    kept = [r for r in rows if r["year"] is not None and r["year"] < year]
    undated = sum(r["year"] is None for r in rows)
    return kept, len(rows) - len(kept) - undated, undated


def rounded(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: rounded(child) for key, child in value.items()}
    if isinstance(value, list):
        return [rounded(child) for child in value]
    return value


def article_rows(path, config):
    from ownvoice.commands.edit_delta import scrubber
    from ownvoice.delta.normalize import load, normalize

    clean = scrubber(config)
    terms, _ = sensitive_terms(config["ingest"]["sensitive_terms"])
    finals, paragraphs = [], []
    for chain in load(path):
        text = normalize(chain["texts"][-1])
        for index, unit in enumerate([text, *re.split(r"\n\s*\n", text)]):
            cleaned, greeting, counts = clean(unit)
            row = {
                "record_id": hashlib.sha256((chain["id"] + str(index - 1)).encode()).hexdigest()[
                    :16
                ],
                "text": cleaned,
                "word_count": len(words(cleaned)),
                "source": "articles",
                "recipient_class": "article",
                "thread_position": "new",
                "year": None,
                "greeting": greeting,
                "signoff": None,
                "template": False,
                "sensitive": sensitive(unit, terms),
                "scrub": counts,
                "strip": {"body_source": "plain", "confidence": "high", "inline_reply": False},
            }
            (finals if index == 0 else paragraphs).append(row)
    return finals, paragraphs


def run(args):
    config, _ = load_config(args.config)
    layout = Layout(Path(config["paths"]["work_dir"]))
    source_config = {s["label"]: s for s in config["source"]}
    selected = set(args.sources.split(",")) if args.sources else set(source_config)
    if not selected or selected - source_config.keys():
        raise DiagnosticError(
            "select profile sources",
            "--sources",
            "empty or unknown source labels",
            "configured source labels",
            None,
            "use labels shown by config show",
        )
    current = config["profile"]["current_source"]
    if current not in selected:
        current = next(s["label"] for s in reversed(config["source"]) if s["label"] in selected)
    path = (
        Path(args.records).expanduser().resolve()
        if args.records
        else layout.work_dir / "records.jsonl"
    )
    rows = (
        read_input(path, lines=True)
        if args.records
        else [
            row
            for label in source_config
            if label in selected
            for row in read_input(layout.source_paths(label)["records"], lines=True)
        ]
    )
    for row in rows:
        records.validate(row)
    unknown = {r["source"] for r in rows} - source_config.keys()
    if unknown:
        raise DiagnosticError(
            "validate profile sources",
            path,
            "records reference unconfigured source labels",
            "configured source labels only",
            None,
            "restore the matching config or rerun ingest",
        )
    rows = [r for r in rows if r["source"] in selected]
    source_rows = {label: [r for r in rows if r["source"] == label] for label in selected}
    if not args.records:
        rows, _ = dedup.merge(rows)
    else:
        rows, _ = dedup.unique(rows)
    cutoff = config["profile"].get("baseline_before")
    rows, excluded_after, excluded_undated = apply_cutoff(rows, cutoff)
    source_rows = {label: apply_cutoff(value, cutoff)[0] for label, value in source_rows.items()}
    if cutoff is not None and not args.quiet:
        # Counts only; printed before any refusal so an empty baseline is explained.
        print(
            f"profile: [profile].baseline_before {cutoff}: kept {len(rows)} records dated "
            f"before {date.fromisoformat(cutoff).year}, excluded {excluded_after} from later "
            f"years and {excluded_undated} undated",
            file=sys.stderr,
        )
    if not select_records(rows):
        raise DiagnosticError(
            "compute profile",
            path,
            "0 usable records",
            "at least 1 high-confidence record",
            None,
            "run ingest and inspect the source reports before retrying profile",
        )
    reports, errors = {}, []
    for label in sorted(selected):
        paths = layout.source_paths(label)
        report = ingest_report.validate(read_input(paths["report"]))
        provenance.require_scrub(config, report, label)
        reports[label] = report
        if report["source"] != label:
            errors.append(
                DiagnosticError(
                    "validate profile report",
                    label,
                    "source label does not match report",
                    "a matching source report",
                    None,
                    "restore the source report or rerun ingest",
                )
            )
        if report["status"] == "partial" and not args.allow_partial:
            folders = ", ".join(f["name"] for f in report["folders"] if f["error"])
            errors.append(
                DiagnosticError(
                    "compute profile",
                    label,
                    f"partial source; failed folders: {folders}",
                    "a complete source or --allow-partial",
                    None,
                    "repair and re-ingest the named folders or pass --allow-partial",
                )
            )
        if report["status"] == "failed":
            errors.append(
                DiagnosticError(
                    "compute profile",
                    label,
                    "source status=failed",
                    "complete or explicitly allowed partial source",
                    None,
                    "repair the source and rerun ingest",
                )
            )
        if paths["extract"].exists() and not args.allow_stale_dump:
            stamp = extract_stamp.validate(read_input(paths["extract_done"]))
            age = (
                datetime.now(UTC) - datetime.fromisoformat(stamp["generated_at"])
            ).total_seconds()
            if age > 7 * 86400:
                errors.append(
                    DiagnosticError(
                        "compute profile",
                        label,
                        f"retained dump age={int(age)} seconds",
                        "at most 604800 seconds or --allow-stale-dump",
                        None,
                        f"run ownvoice clean --extracted {label} or pass --allow-stale-dump",
                    )
                )
    if errors:
        raise ValidationErrors(errors)
    eligible = {label for label in selected if source_config[label]["llm_eligible"]}
    lexicon_path = config["profile"]["llm_ism_lexicon"] or DATA / "llm-isms.txt"
    llm_isms = read_lexicon(lexicon_path)
    softeners = read_lexicon(config["ingest"]["softeners"]) if config["ingest"]["softeners"] else ()
    registers = aggregate(rows, config, eligible, llm_isms, softeners)
    # Article targets never use the _global short-email band. With a cutoff
    # they are the long email stratum alone: chain finals are undated, so a cutoff
    # cannot place them before it, and they may carry AI-assisted wording. Without a
    # cutoff the previous basis stays (chain finals, else professional-warm), and any
    # thin band takes the long-email band instead of _global.
    minimum = config["profile"]["thin_register_min"]
    long_rows, long_cut = long_emails(rows)
    long_register = aggregate(long_rows, config, eligible, llm_isms, softeners)["_global"]
    long_register["derived_from"] = "_global"
    long_register = anchor_article(long_register, None, minimum)
    article_paragraphs = []
    if args.articles:
        finals, article_paragraphs = article_rows(args.articles, config)
    if cutoff is not None:
        article_basis = "long_emails"
        registers["article"] = long_register
    elif args.articles:
        article_basis = "chain_finals"
        finals_register = aggregate(finals, config, {"articles"}, llm_isms, softeners)["_global"]
        registers["article"] = anchor_article(finals_register, long_register, minimum)
    else:
        article_basis = "professional-warm"
        derived = deepcopy(registers["professional-warm"])
        derived["derived_from"] = "professional-warm"
        registers["article"] = anchor_article(derived, long_register, minimum)
    use_finals = article_basis == "chain_finals"
    by_source = {
        label: {"registers": aggregate(source_rows[label], config, eligible, llm_isms, softeners)}
        for label in sorted(selected)
    }
    # One article target for every source: email-era contrast must not override it.
    for source in by_source.values():
        source["registers"]["article"] = deepcopy(registers["article"])
    counted = select_records(rows)
    years = [r["year"] for r in counted if r["year"] is not None]
    # Bind time to persisted ingest inputs, never the wall clock of this profile run.
    prov = provenance.build(
        config,
        config["paths"]["domain_map"],
        config["paths"]["editorial_rules"],
        timestamp=max(r["generated_at"] for r in reports.values()),
        readers={
            label: {"reader": r["reader"], "reader_version": r["reader_version"]}
            for label, r in reports.items()
            if r["reader"]
        },
    )
    _, sensitive = sensitive_terms(config["ingest"]["sensitive_terms"])
    output = Path(args.out_dir).expanduser().resolve() if args.out_dir else layout.profile_dir
    retained_records = output / "profiled-records.jsonl"
    delta_binding = {}
    if args.edit_delta:
        selected_delta = edit_delta.validate(read_input(Path(args.edit_delta).expanduser()))
        provenance.require_current(config, selected_delta, args.edit_delta, "edit-delta")
        retained_delta = output / "edit-deltas" / Path(args.edit_delta).name
        write_json(retained_delta, selected_delta)
        delta_binding = {
            "edit_delta": {
                "file": retained_delta.relative_to(output).as_posix(),
                "sha256": provenance.file_sha256(retained_delta),
            }
        }
    write_jsonl(retained_records, rows)
    article_binding = {}
    if args.articles:
        retained_articles = output / "profiled-articles.jsonl"
        write_jsonl(
            retained_articles,
            [
                article_records.build(
                    **{
                        key: row[key]
                        for key in (
                            "record_id",
                            "source",
                            "recipient_class",
                            "year",
                            "word_count",
                            "text",
                        )
                    },
                    truncated=False,
                )
                for row in finals
            ],
        )
        article_binding["profiled_articles"] = {
            "file": retained_articles.name,
            "sha256": provenance.file_sha256(retained_articles),
        }
    stats = profile_stats.build(
        **prov,
        **delta_binding,
        **article_binding,
        profiled_records={
            "file": retained_records.name,
            "sha256": provenance.file_sha256(retained_records),
        },
        current_source=current,
        baseline={
            "before": cutoff,
            "granularity": "year",
            "excluded_after": excluded_after,
            "excluded_undated": excluded_undated,
            "article_basis": article_basis,
            "article_finals_excluded": bool(args.articles) and not use_finals,
            "long_email_min_words": long_cut,
            "long_emails": len(long_rows),
        },
        corpus={
            "records": len(counted),
            "rejected": sum(sum(r["rejected_by_reason"].values()) for r in reports.values()),
            "low_confidence_excluded": sum(r["strip"]["confidence"] == "low" for r in rows),
            "span_years": [min(years), max(years)] if years else [0, 0],
            "per_register": {name: r["n"] for name, r in registers.items()},
            "sources": {
                label: {
                    "records": by_source[label]["registers"]["_global"]["n"],
                    "era": next((r["era"] for r in source_rows[label]), None),
                    "status": reports[label]["status"],
                    "llm_eligible": label in eligible,
                }
                for label in sorted(selected)
            },
        },
        by_source=by_source,
        lexicons={
            "llm_ism": {
                "source": "file" if config["profile"]["llm_ism_lexicon"] else "builtin",
                "sha256": hashlib.sha256("\n".join(llm_isms).encode()).hexdigest(),
            },
            "sensitive": sensitive,
        },
        contrast=contrast.compare(
            registers, by_source, current, config["profile"]["thin_register_min"]
        ),
        registers=registers,
        time={
            "by_" + field: dict(
                sorted(Counter(str(r[field]) for r in counted if r[field] is not None).items())
            )
            for field in ("year", "weekday", "hour_bucket")
        },
    )
    projection = project(
        stats, eligible=bool(eligible), never_hit_min_words=config["profile"]["never_hit_min_words"]
    )
    examples = exemplars.build(rows, eligible, config["profile"], prov)
    if use_finals:
        article_examples = exemplars.select_register(
            article_paragraphs, {"articles"}, config["profile"]
        )
        article_examples["selection"]["basis"] = "chain_final_paragraphs"
    else:
        # Never fabricate: only the long emails' own paragraphs, same eligibility rules.
        article_examples = exemplars.select_register(
            paragraph_rows(long_rows), eligible, config["profile"]
        )
        article_examples["selection"]["basis"] = "long_email_paragraphs"
    examples["registers"]["article"] = article_examples
    projection = rounded(projection)
    examples = budget.enforce(projection, examples, config["profile"])
    article_selection = examples["registers"]["article"]["selection"]
    if article_selection["status"] == "ok" and article_selection["selected"] < 3:
        # write-in-voice uses 3-5 article exemplars; disclose any shortfall.
        article_selection["shortfall"] = {"wanted": 3, "selected": article_selection["selected"]}
    examples = exemplar_schema.validate(examples)
    write_json(output / "profile-stats.json", rounded(stats))
    write_json(output / "stats-llm.json", projection)
    write_json(output / "exemplars.json", examples)
    if not args.quiet:
        print(
            f"profile: {len(counted)} records, {len(selected)} sources, {len(registers)} registers",
            file=sys.stderr,
        )
    return 0
