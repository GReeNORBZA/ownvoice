"""Stage Q chunk manifest."""

from ownvoice.schemas import common as c

CHUNK = {
    "chunk_id": str,
    "pass": c.enum("A", "B"),
    "source": c.LABEL,
    "registers": c.array(c.REGISTER),
    "record_ids": c.array(c.RECORD_ID),
    "est_tokens": c.COUNT,
    "text_path": str,
    "status": c.enum("pending", "done", "failed"),
    "attempts": c.COUNT,
    "text_sha256": c.optional(c.SHA256),
    "raw_paths": c.optional(c.array(str)),
    "records": c.optional(
        c.array(
            {
                "record_id": c.RECORD_ID,
                "register": c.REGISTER,
                "start": c.COUNT,
                "end": c.COUNT,
            }
        )
    ),
}
SCHEMA = {
    **c.PROVENANCE,
    "pass": c.enum("A", "B"),
    "max_tokens": c.POSITIVE,
    "sample_words": c.POSITIVE,
    "chunks": c.array(CHUNK),
}


def validate(value):
    return c.validate(value, SCHEMA, "manifest")


def build(**fields):
    return c.build(fields, SCHEMA, "manifest")
