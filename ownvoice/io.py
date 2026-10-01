"""Atomic private artefact I/O (NIST AC-6 permissions)."""

import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode

_KEY_PARTS = ("ownvoice", "artifact")
_LINE_PARTS = ("ownvoice", "private-artifact")
PRIVATE_KEY = "_".join(_KEY_PARTS)
PRIVATE_VALUE = "private"
PRIVATE_LINE = "<!-- " + ":".join(_LINE_PARTS) + " -->"


def inside_git_worktree(path):
    """Detect ordinary and linked worktrees, including not-yet-created paths.

    Checking ancestors also works without git installed and does not trust inherited
    GIT_DIR/GIT_WORK_TREE environment variables. A .git file is a linked worktree.
    """
    target = Path(path).expanduser().resolve()
    return any((parent / ".git").exists() for parent in (target, *target.parents))


def _atomic_write(path, emit):
    path = Path(path).expanduser().resolve()
    if inside_git_worktree(path):
        raise DiagnosticError(
            "write private artefact",
            path,
            "path is inside a git working tree",
            "a destination outside git working trees",
            None,
            "choose a private output directory outside the repository",
        )
    temporary = None
    try:
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
        # Only the owned destination directory, never arbitrary existing ancestors.
        path.parent.chmod(0o700)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            os.fchmod(stream.fileno(), 0o600)
            emit(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError) as exc:
        raise DiagnosticError(
            "write private artefact",
            path,
            str(exc),
            "an atomically written 0600 file in a 0700 directory",
            exc,
            "check the destination permissions and serializable input",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    def emit(stream):
        json.dump(
            {**value, PRIVATE_KEY: PRIVATE_VALUE},
            stream,
            sort_keys=True,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")

    _atomic_write(path, emit)


def write_jsonl(path, values):
    def emit(stream):
        for value in values:
            stream.write(
                json.dumps(
                    {**value, PRIVATE_KEY: PRIVATE_VALUE},
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )

    _atomic_write(path, emit)


def append_jsonl(path, value):
    """Atomically append one marked row to an existing single-writer journal."""

    def emit(stream):
        with Path(path).open(encoding="utf-8") as previous:
            shutil.copyfileobj(previous, stream)
        stream.write(
            json.dumps(
                {**value, PRIVATE_KEY: PRIVATE_VALUE},
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )

    _atomic_write(path, emit)


def write_marked_text(path, text):
    _atomic_write(path, lambda stream: stream.write(PRIVATE_LINE + "\n" + text))


def write_marked_toml(path, text):
    _atomic_write(path, lambda stream: stream.write(f'{PRIVATE_KEY} = "{PRIVATE_VALUE}"\n' + text))


def has_private_marker(path):
    """Top-level JSON/TOML key, any JSONL row, or exact first text line, under any name."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeError:
        return False
    except OSError as exc:
        raise DiagnosticError(
            "inspect private marker",
            path,
            str(exc),
            "a readable file",
            exc,
            "check the file exists and is readable",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    if text.splitlines() and text.splitlines()[0] == PRIVATE_LINE:
        return True
    try:
        if PRIVATE_KEY in tomllib.loads(text):
            return True
    except tomllib.TOMLDecodeError:
        pass  # Malformed TOML can still be marked text or JSON below.
    try:
        obj = json.loads(text)
    except ValueError:
        for line in text.splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and PRIVATE_KEY in obj:
                return True
        return False
    return isinstance(obj, dict) and PRIVATE_KEY in obj
