"""Validate the entire selected input set before creating any output."""

import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from ownvoice.config import DEFAULT_READER
from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors
from ownvoice.io import inside_git_worktree
from ownvoice.layout import LABEL_PATTERN


def problem(identity, observed, expected, cause=None):
    return DiagnosticError(
        "preflight ingest",
        identity,
        observed,
        expected,
        cause,
        "correct the source or work_dir in config.toml and retry ingest",
    )


def select_sources(config, args):
    sources = deepcopy(config["source"])
    errors = []
    if args.source:
        kind, separator, path = args.source.partition(":")
        if not separator or kind not in ("eml", "mbox", "pst") or not path:
            errors.append(problem("--source", "invalid KIND:PATH", "mbox:PATH or eml:PATH"))
        if not args.label or not re.fullmatch(LABEL_PATTERN, args.label):
            errors.append(problem("--label", "missing or invalid label", LABEL_PATTERN))
        elif args.label in {s["label"] for s in sources}:
            errors.append(problem("--label", "duplicate source label", "a unique label"))
        if not args.owner:
            errors.append(problem("--owner", "no owner supplied", "at least one --owner address"))
        if not errors:
            sources.append(
                {
                    "label": args.label,
                    "kind": kind,
                    "path": str(Path(path).expanduser().resolve()),
                    "owner_addresses": args.owner,
                    "timezone": config["owner"]["timezone"],
                    "allow_inside_git_tree": False,
                    "llm_eligible": False,
                    **(
                        {"reader": DEFAULT_READER, "sent_folders": config["ingest"]["sent_folders"]}
                        if kind == "pst"
                        else {}
                    ),
                }
            )
    elif args.label or args.owner:
        errors.append(
            problem("--source", "label or owner without source", "the complete ad hoc form")
        )
    if args.only:
        labels = args.only.split(",")
        if set(labels) - {s["label"] for s in sources}:
            errors.append(problem("--only", "unknown source label", "configured source labels"))
        sources = [s for s in sources if s["label"] in labels]
    for flag in ("restart", "reparse"):
        label = getattr(args, flag)
        if label and label not in {s["label"] for s in sources}:
            errors.append(
                problem(
                    "--" + flag + " " + label,
                    "unknown or unselected source label",
                    "a configured source label included in --only",
                )
            )
    if errors:
        raise ValidationErrors(errors)
    return sources


def preflight(config, sources):
    errors, inputs = [], {}
    pst_bytes = 0
    work = Path(config["paths"]["work_dir"])
    if inside_git_worktree(work):
        errors.append(
            problem(work, "work_dir is inside a git working tree", "work_dir outside git")
        )
    ancestor = work
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
        errors.append(problem(work, "destination is not writable", "a writable directory"))
    for source in sources:
        path = Path(source["path"])
        identity = f"{source['label']} {path}"
        if inside_git_worktree(path) and not source["allow_inside_git_tree"]:
            errors.append(
                problem(
                    identity,
                    "source is inside a git working tree",
                    "source outside git or allow_inside_git_tree = true",
                )
            )
        if path.suffix.lower() == ".ost":
            errors.append(problem(identity, "OST unsupported", "PST, mbox or eml"))
        try:
            if source["kind"] == "pst":
                reader = source["reader"]
                package = "pff-tools" if reader == "pffexport" else "pst-utils"
                other = "readpst" if reader == "pffexport" else "pffexport"
                if not shutil.which(reader):
                    errors.append(
                        DiagnosticError(
                            "ingest",
                            identity,
                            f'{reader} not found on PATH (reader = "{reader}" for {path})',
                            "an installed executable on PATH",
                            None,
                            f"Install {package} (Debian/Ubuntu: apt install {package}), "
                            f'set reader = "{other}", or export the mailbox to mbox',
                            exit_code=ExitCode.DEPENDENCY,
                        )
                    )
                else:
                    result = subprocess.run(
                        [reader, "-V"], capture_output=True, text=True, check=False
                    )
                    if result.returncode:
                        errors.append(
                            DiagnosticError(
                                "inspect PST reader version",
                                identity,
                                f"{reader} -V exited {result.returncode}: {result.stderr}",
                                "exit 0",
                                subprocess.CalledProcessError(result.returncode, [reader, "-V"]),
                                f"reinstall {package} and retry ingest",
                                exit_code=ExitCode.DEPENDENCY,
                            )
                        )
                    version = re.search(r"\b(?:\d{8}|\d+\.\d+\.\d+)\b", result.stdout)
                    source["_reader_version"] = version[0] if version else "unrecognized"
                    expected = "20180714" if reader == "pffexport" else "0.6.76"
                    if source["_reader_version"] != expected:
                        print(
                            str(
                                DiagnosticError(
                                    "inspect PST reader version",
                                    identity,
                                    f"{reader} {source['_reader_version']}",
                                    expected,
                                    None,
                                    "validate this version against the real-PST fixtures before relying on it",
                                )
                            ),
                            file=sys.stderr,
                        )
        except OSError as exc:
            errors.append(problem(identity, str(exc), "an executable PST reader", exc))
        try:
            stat = path.stat()
            if source["kind"] == "pst":
                pst_bytes += stat.st_size
                if stat.st_size == 0:
                    errors.append(problem(identity, "source is 0 bytes", "size > 0 bytes"))
            if not stat.st_mode & 0o444 or not os.access(path, os.R_OK):
                errors.append(problem(identity, "source is unreadable", "a readable source"))
                continue
            if source["kind"] == "eml" and path.is_dir():
                # os.walk surfaces traversal errors, unlike Path.rglob on some Python versions.
                files = []

                def onerror(exc):
                    raise exc

                for root, dirs, names in os.walk(path, onerror=onerror, followlinks=False):
                    dirs.sort()
                    for name in names:
                        if name.endswith(".eml"):
                            files.append(Path(root) / name)
                files.sort()
            else:
                files = [path]
            inputs[source["label"]] = files
            if not files:
                errors.append(problem(identity, "no .eml files", "a nonempty eml source"))
            for item in files:
                info = item.stat()
                if (
                    inside_git_worktree(item)
                    and not source["allow_inside_git_tree"]
                    and item != path
                ):
                    errors.append(
                        problem(
                            identity, "eml target is inside git", "all source files outside git"
                        )
                    )
                if not info.st_mode & 0o444 or not os.access(item, os.R_OK):
                    errors.append(
                        problem(identity, "source file is unreadable", "readable source files")
                    )
                    continue
                if info.st_size == 0:
                    if source["kind"] != "pst":
                        errors.append(problem(identity, "source is 0 bytes", "size > 0 bytes"))
                    continue
                with item.open("rb") as stream:
                    head = stream.read(8192)
                kind = source["kind"]
                valid = (
                    head.startswith(b"From ")
                    if kind == "mbox"
                    else head.startswith(b"!BDN")
                    if kind == "pst"
                    else bool(re.match(rb"[!-9;-~]+:", head))
                )
                if not valid:
                    errors.append(
                        problem(identity, "content does not match kind", f"{kind} content magic")
                    )
        except OSError as exc:
            errors.append(problem(identity, str(exc), "an existing readable source", exc))
    if pst_bytes and shutil.disk_usage(ancestor).free < 1.5 * pst_bytes:
        errors.append(
            problem(
                work,
                f"{shutil.disk_usage(ancestor).free} bytes free",
                f"at least {int(1.5 * pst_bytes)} bytes (1.5 times selected PST sizes)",
            )
        )
    if errors:
        report = ValidationErrors(errors)
        # Invalid sources are operator errors even when a reader is also unavailable.
        if any(error.exit_code == ExitCode.OPERATOR for error in errors):
            report.exit_code = ExitCode.OPERATOR
        raise report
    return inputs
