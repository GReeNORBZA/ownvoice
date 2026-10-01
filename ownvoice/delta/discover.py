"""Human-reviewed chain proposals; never an implicit profile input."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from ownvoice.delta.normalize import git, read_text
from ownvoice.errors import DiagnosticError, ExitCode


def discover(directory, use_git=False):
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise DiagnosticError(
            "discover article chains",
            root,
            "directory does not exist",
            "a readable directory",
            None,
            "correct --dir and retry",
            exit_code=ExitCode.DEPENDENCY,
        )
    groups = defaultdict(list)
    for path in sorted(root.rglob("*.md")):
        match = re.match(r"\A---\s*\n(.*?)\n---", read_text(path), re.DOTALL)
        if not match:
            continue
        fields = dict(re.findall(r"^(title|date):\s*(.*?)\s*$", match[1], re.MULTILINE))
        title = fields.get("title", "").strip("\"'")
        if not title:
            continue
        stamp = (
            git(
                root, str(path.relative_to(root)), "log", "-1", "--format=%ct", "--", str(path)
            ).strip()
            if use_git
            else "0"
        )
        groups[title].append((fields.get("date", "").strip("\"'"), int(stamp or 0), str(path)))
    lines = ["# Review origins and version order, then save as chains.toml.", "schema_version = 1"]
    for title, versions in sorted(groups.items()):
        if len(versions) < 2:
            continue
        lines.extend(
            [
                "",
                "[[chain]]",
                "id = " + json.dumps(hashlib.sha256(title.encode()).hexdigest()[:16]),
                'origin = "owner" # Review: set llm only for an LLM-authored first draft.',
                "versions = " + json.dumps([v[2] for v in sorted(versions)]),
            ]
        )
    return "\n".join(lines) + "\n"
