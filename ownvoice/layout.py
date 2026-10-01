"""Shared private output layout and resume-state contracts."""

import re
from dataclasses import dataclass
from pathlib import Path

from ownvoice.errors import DiagnosticError

LABEL_PATTERN = r"[a-z0-9-]{1,32}"


@dataclass(frozen=True)
class Layout:
    work_dir: Path

    @property
    def profile_dir(self):
        return self.work_dir / "profile" / "ownvoice"

    @property
    def names(self):
        return self.work_dir / "names.txt"

    @property
    def unmapped_domains(self):
        return self.work_dir / "unmapped-domains.json"

    def source(self, label):
        if not isinstance(label, str) or not re.fullmatch(LABEL_PATTERN, label):
            raise DiagnosticError(
                "resolve source layout",
                "source.label",
                "invalid source label",
                LABEL_PATTERN,
                None,
                "correct source.label in config.toml",
            )
        return self.work_dir / "sources" / label

    def source_paths(self, label):
        root = self.source(label)
        return {
            name: root / filename
            for name, filename in {
                "records": "records.jsonl",
                "report": "ingest-report.json",
                "rejects": "rejects.jsonl",
                "checkpoint": "checkpoint.json",
                "extract": "extract",
                "extract_done": "extract/.done",
            }.items()
        }

    def resolved_paths(self, editorial_rules):
        return {
            key: str(value)
            for key, value in {
                "work_dir": self.work_dir,
                "profile_dir": self.profile_dir,
                "profile_stats": self.profile_dir / "profile-stats.json",
                "stats_llm": self.profile_dir / "stats-llm.json",
                "exemplars": self.profile_dir / "exemplars.json",
                "editorial_rules": editorial_rules,
                "names": self.names,
            }.items()
        }


# The persisted shapes are validated by the same schema machinery as artefacts.
def checkpoint(**fields):
    from ownvoice.schemas.checkpoint import build

    return build(**fields)


def extract_stamp(**fields):
    from ownvoice.schemas.extract_stamp import build

    return build(**fields)
