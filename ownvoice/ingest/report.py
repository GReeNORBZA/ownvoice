"""Schema-backed per-source accounting and privacy-safe stderr summaries."""

import sys
from collections import Counter
from pathlib import Path

from ownvoice.errors import DiagnosticError, internal_error
from ownvoice.schemas import ingest_report


def build(
    source,
    provenance,
    fingerprint,
    records,
    rejects,
    selected,
    resolution,
    domains,
    names,
    orgs=None,
    reader=None,
):
    reasons = Counter(r["reason"] for r in rejects)
    rules = Counter(rule for r in records for rule in r["strip"]["rules_fired"])
    low = sum(r["strip"]["confidence"] == "low" for r in records)
    seen = len(records) + len(rejects)
    folders = [
        {
            "name": "messages",
            "messages_seen": seen,
            "records": len(records),
            "rejects": len(rejects),
            "error": None,
        }
    ]
    if reader:
        by_name = {folder["name"]: dict(folder) for folder in reader.folders}
        for error in reader.errors:
            if error["name"] in by_name:
                by_name[error["name"]]["error"] = error["error"]
            else:
                by_name[error["name"]] = error
        folders = list(by_name.values())
    return ingest_report.build(
        **provenance,
        source=source["label"],
        kind=source["kind"],
        reader=source.get("reader"),
        reader_version=source.get("_reader_version"),
        path_basename=Path(source["path"]).name,
        fingerprint=fingerprint,
        status="partial" if reader and reader.errors else "complete" if records else "failed",
        llm_eligible=source["llm_eligible"],
        allow_inside_git_tree=source["allow_inside_git_tree"],
        folders=folders,
        skipped_folders=reader.skipped_folders if reader else 0,
        skipped_messages=reader.skipped_messages if reader else 0,
        extract=reader.extraction if reader else None,
        messages_seen=seen,
        selected=selected,
        records_written=len(records),
        rejected_by_reason=dict(reasons),
        recipient_resolution=resolution,
        unmapped={"domains": len(domains), "x500_orgs": len(orgs or {}), "names": len(names)},
        low_confidence=low,
        low_confidence_excluded=low,
        templates=sum(r["template"] for r in records),
        duplicates=reasons["duplicate"],
        sensitive=sum(r["sensitive"] for r in records),
        rules_fired_counts=dict(rules),
        invariant="seen == records + rejects",
    )


def merged(provenance, source_counts, records, cross_duplicates):
    expected = sum(source_counts.values()) - cross_duplicates
    if len(records) != expected:
        cause = ValueError(
            f"merged_records={len(records)}, expected={expected}, "
            f"source_records={sum(source_counts.values())}, "
            f"cross_source_duplicates={cross_duplicates}"
        )
        raise internal_error("account for merged records", "ingest-report.json", cause) from cause
    return ingest_report.build_merged(
        **provenance,
        sources=source_counts,
        merged_records=len(records),
        cross_source_duplicates=cross_duplicates,
        invariant="merged_records == sum source records - cross_source_duplicates",
    )


def summary(report, rejects_path, records):
    label = report["source"]
    print(
        f"ingest[{label}]: {report['messages_seen']} messages, {report['records_written']} records; "
        f"rejects={report['rejected_by_reason']}; folders skipped={report['skipped_folders']} "
        f"failed={sum(f['error'] is not None for f in report['folders'])}; "
        f"low_confidence={report['low_confidence']}; rejects={rejects_path}; "
        f"recipient_resolution={report['recipient_resolution']}",
        file=sys.stderr,
    )
    if records and report["low_confidence"] / len(records) > 0.1:
        implicated = Counter(
            rule
            for r in records
            if r["strip"]["confidence"] == "low"
            for rule in (r["strip"]["rules_fired"] or r["strip"]["flags"])
        )
        top = ", ".join(rule for rule, _ in implicated.most_common(3))
        print(
            str(
                DiagnosticError(
                    "assess ingest confidence",
                    label,
                    f"low-confidence share exceeds 10%; top rules: {top}",
                    "at most 10%",
                    None,
                    "inspect the private records and configure attribution patterns",
                )
            ),
            file=sys.stderr,
        )
