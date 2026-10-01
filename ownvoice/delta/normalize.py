"""Article normalization and chain input, retaining punctuation for measurements."""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.schemas import chains
from ownvoice.style.tokenize import normalize as quotes


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DiagnosticError(
            "read article version",
            path,
            str(exc),
            "readable UTF-8 text",
            exc,
            "restore the version file and retry",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def normalize(text, *, alignment=False):
    text = re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|$)", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[image: \1]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s*(?:[-*+] |\d+\. )", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__|\*|_)(.+?)\1", r"\2", text)
    if alignment:
        text = quotes(text).translate(str.maketrans({"“": '"', "”": '"', "—": "-", "–": "-"}))
    return text.strip()


def git(repo, identity, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            env=env,
        )
        return result.stdout
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        raise DiagnosticError(
            "read git chain",
            identity,
            getattr(exc, "stderr", None) or str(exc),
            "git installed and a readable repository/path history",
            exc,
            "install git or correct the chain repo/path and retry",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc


def resolve(base, path):
    path = Path(path).expanduser()
    return path if path.is_absolute() else base / path


def load(path):
    path = Path(path).expanduser().resolve()
    result = []
    for chain in chains.load(path)["chain"]:
        if "versions" in chain:
            texts = [read_text(resolve(path.parent, p)) for p in chain["versions"]]
        else:
            spec = chain["git"]
            repo = resolve(path.parent, spec["repo"])
            current = spec["path"]
            flags = ["--follow"] if spec["follow"] else []
            commits = git(
                repo, chain["id"], "log", *flags, "--format=%H", "--", current
            ).splitlines()
            texts = []
            # Walk newest to oldest so rename records can update the historical path.
            for commit in commits:
                texts.append(git(repo, chain["id"], "show", f"{commit}:{current}"))
                if spec["follow"]:
                    changes = git(
                        repo,
                        chain["id"],
                        "diff-tree",
                        "--root",
                        "-r",
                        "-M",
                        "--no-commit-id",
                        "--name-status",
                        "-z",
                        commit,
                    ).split("\0")
                    i = 0
                    while i < len(changes) and changes[i]:
                        status = changes[i]
                        if status.startswith(("R", "C")):
                            old, new = changes[i + 1 : i + 3]
                            if new == current:
                                current = old
                            i += 3
                        else:
                            i += 2
            texts.reverse()
        if len(texts) < 2:
            raise DiagnosticError(
                "expand article chain",
                chain["id"],
                f"{len(texts)} versions",
                "at least two versions",
                None,
                "add version history or correct the chain path",
            )
        result.append(
            {
                "id": chain["id"],
                "origin": chain["origin"],
                "texts": texts,
                "versions": [{"sha256": hashlib.sha256(t.encode()).hexdigest()} for t in texts],
            }
        )
    return result
