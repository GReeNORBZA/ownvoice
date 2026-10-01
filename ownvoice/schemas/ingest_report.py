"""Per-source and merged ingest reports."""

from ownvoice.schemas import common as c
from ownvoice.schemas.rejects import REASONS

LEXICONS = {"sensitive": {"source": str, "sha256": c.SHA256}}

SCHEMA = {
    **c.PROVENANCE,
    "lexicons": c.optional(LEXICONS),
    "source": c.LABEL,
    "kind": c.enum("pst", "mbox", "eml"),
    "reader": c.nullable(c.enum("pffexport", "readpst")),
    "reader_version": c.nullable(str),
    "path_basename": str,
    "fingerprint": c.FINGERPRINT,
    "status": c.enum("complete", "partial", "failed"),
    "llm_eligible": bool,
    "allow_inside_git_tree": bool,
    "folders": c.array(
        {
            "name": str,
            "messages_seen": c.COUNT,
            "records": c.COUNT,
            "rejects": c.COUNT,
            "error": c.nullable(str),
        }
    ),
    "skipped_folders": c.COUNT,
    "skipped_messages": c.COUNT,
    "extract": c.nullable({"elapsed_s": c.RATE, "dump_bytes": c.COUNT}),
    "messages_seen": c.COUNT,
    "selected": c.COUNT,
    "records_written": c.COUNT,
    "rejected_by_reason": {reason: c.optional(c.COUNT) for reason in REASONS},
    "recipient_resolution": {"recipients": c.COUNT, **c.STAGES},
    "unmapped": dict.fromkeys(("domains", "x500_orgs", "names"), c.COUNT),
    **dict.fromkeys(
        ("low_confidence", "low_confidence_excluded", "templates", "duplicates", "sensitive"),
        c.COUNT,
    ),
    "rules_fired_counts": c.mapping(c.COUNT),
    "invariant": c.enum("seen == records + rejects"),
}
MERGED_SCHEMA = {
    **c.PROVENANCE,
    "lexicons": c.optional(LEXICONS),
    "sources": c.mapping(c.COUNT),
    "merged_records": c.COUNT,
    "cross_source_duplicates": c.COUNT,
    "invariant": c.enum("merged_records == sum source records - cross_source_duplicates"),
}


def _conservation(value, errors):
    c.constraint(
        errors,
        "ingest-report.messages_seen",
        value["messages_seen"]
        == value["records_written"] + sum(value["rejected_by_reason"].values()),
        "messages_seen == records_written + rejected counts",
    )
    resolution = value["recipient_resolution"]
    c.constraint(
        errors,
        "ingest-report.recipient_resolution.recipients",
        resolution["recipients"] == sum(resolution[key] for key in c.STAGES),
        "recipients == smtp + x500 + names + unknown",
    )


def _merged_conservation(value, errors):
    c.constraint(
        errors,
        "ingest-report.merged_records",
        value["merged_records"]
        == sum(value["sources"].values()) - value["cross_source_duplicates"],
        "merged_records == sum source records - cross_source_duplicates",
    )


def validate(value):
    return c.validate(value, SCHEMA, "ingest-report", _conservation)


def build(**fields):
    return c.build(fields, SCHEMA, "ingest-report", _conservation)


def validate_merged(value):
    return c.validate(value, MERGED_SCHEMA, "ingest-report", _merged_conservation)


def build_merged(**fields):
    return c.build(fields, MERGED_SCHEMA, "ingest-report", _merged_conservation)
