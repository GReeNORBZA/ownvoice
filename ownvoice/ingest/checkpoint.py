"""Durable scrubbed parse prefixes, with the checkpoint as the commit boundary."""

import hashlib
import json
import os
from collections import Counter

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.io import append_jsonl, write_json, write_jsonl
from ownvoice.schemas import checkpoint, unmapped_domains


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise DiagnosticError(
            "read ingest state",
            path,
            type(exc).__name__,
            "readable valid JSON",
            exc,
            "restore the private state or use ingest --restart LABEL",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def identity(paths):
    # Bind every file's metadata, not only aggregate size and maximum mtime.
    data = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def matches(state, fingerprint, files):
    previous = state["fingerprint"]
    return state["files"] == files and all(
        previous[key] == fingerprint[key]
        for key in ("size", "mtime_ns", "first_sha256", "last_sha256")
        if key in ("size", "mtime_ns")
        or (previous[key] is not None and fingerprint[key] is not None)
    )


def rows(path, count=None):
    try:
        with path.open("rb") as stream:
            result = []
            while count is None or len(result) < count:
                line = stream.readline()
                if not line:
                    break
                result.append(json.loads(line))
        if count is not None and len(result) != count:
            raise ValueError(f"expected {count} committed rows, got {len(result)}")
        return result
    except (OSError, ValueError) as exc:
        raise DiagnosticError(
            "read ingest prefix",
            path,
            type(exc).__name__,
            "the committed JSONL prefix",
            exc,
            "restore the private source output or use ingest --restart LABEL",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def domains(outputs, state, key="domains"):
    summary = read(outputs["checkpoint"].with_name("unmapped-domains.json"))
    unmapped_domains.validate(summary)
    field = "domain" if key == "domains" else "org"
    labels = [row[field] for row in summary[key]]
    return Counter(
        {
            label: state.get(key, {}).get(hashlib.sha256(label.encode()).hexdigest(), 0)
            for label in labels
            if hashlib.sha256(label.encode()).hexdigest() in state.get(key, {})
        }
    )


class Journal:
    def __init__(self, outputs, provenance, fingerprint, files, previous=None):
        self.outputs = outputs
        self.provenance = {k: v for k, v in provenance.items() if k != "lexicons"}
        self.fingerprint, self.files = fingerprint, files
        self.previous = previous
        self.folder = previous["folder"] if previous else "messages"
        self.records = rows(outputs["records"], previous["records"]) if previous else []
        self.rejects = rows(outputs["rejects"], previous["rejects"]) if previous else []
        # Ignore even a torn final JSON line beyond the committed prefix.
        write_jsonl(outputs["records"], self.records)
        write_jsonl(outputs["rejects"], self.rejects)

    def append(self, kind, value):
        append_jsonl(self.outputs[kind], value)

    def save(self, index, selected, resolution, domains, names, *, complete=False, orgs=None):
        try:
            for kind in ("records", "rejects"):
                with self.outputs[kind].open("rb") as stream:
                    os.fsync(stream.fileno())
        except OSError as exc:
            raise DiagnosticError(
                "flush ingest prefix",
                self.outputs["checkpoint"],
                str(exc),
                "durable records and rejects before checkpoint",
                exc,
                "check disk space and retry ingest",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc
        value = checkpoint.build(
            **self.provenance,
            folder=self.folder,
            message_index=index,
            records=len(self.records),
            rejects=len(self.rejects),
            state={
                "fingerprint": self.fingerprint,
                "files": self.files,
                "complete": complete,
                "selected": selected,
                "resolution": resolution,
                "domains": {hashlib.sha256(d.encode()).hexdigest(): n for d, n in domains.items()},
                "names": sorted(names),
                "x500_orgs": {
                    hashlib.sha256(o.encode()).hexdigest(): n for o, n in (orgs or {}).items()
                },
            },
        )
        # Labels are permitted only on the dedicated private identity surface. Its
        # superset may advance before a crash; only checkpoint counts are committed.
        write_json(
            self.outputs["checkpoint"].with_name("unmapped-domains.json"),
            unmapped_domains.build(
                **self.provenance,
                source=self.outputs["checkpoint"].parent.name,
                domains=[{"domain": d, "messages": n} for d, n in sorted(domains.items())],
                x500_orgs=[{"org": o, "messages": n} for o, n in sorted((orgs or {}).items())],
                unresolved_names=len(names),
            ),
        )
        write_json(self.outputs["checkpoint"], value)


def reset(outputs):
    # C6 owns extraction state. Reparse intentionally preserves it.
    for kind in ("checkpoint", "report", "records", "rejects"):
        path = outputs[kind]
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise DiagnosticError(
                "reset ingest source",
                path,
                str(exc),
                "removable source parse state",
                exc,
                "check source output permissions and retry ingest",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc
