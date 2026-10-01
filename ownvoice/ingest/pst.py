"""PST export lifecycle and folder-isolated, privacy-safe iteration."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.extract import scrub
from ownvoice.extract.body import Rejected
from ownvoice.io import inside_git_worktree, write_json
from ownvoice.readers import mbox, pst_pffexport, pst_readpst
from ownvoice.schemas import extract_stamp


def problem(source, observed, expected, cause=None, *, operator=False):
    return DiagnosticError(
        "ingest PST",
        source["label"],
        observed,
        expected,
        cause,
        "Check the file is a PST (not an OST renamed to .pst) and readable; "
        "run with --verbose for the full command line",
        exit_code=ExitCode.OPERATOR if operator else ExitCode.DEPENDENCY,
    )


def size(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def retained(work):
    root = Path(work) / "sources"
    return sorted(root.glob("*/extract")) if root.exists() else []


def listing(work):
    for path in retained(work):
        print(
            f"retained export [{path.parent.name}]: {size(path)} bytes, "
            f"age {max(0, int(time.time() - path.stat().st_mtime))} s",
            file=sys.stderr,
        )


def remove(path):
    if path.is_symlink() or inside_git_worktree(path):
        raise DiagnosticError(
            "delete PST export",
            path,
            "symlink or git working tree target",
            "an owned private extract directory",
            None,
            "correct work_dir and inspect the target before retrying",
        )
    if path.exists():
        try:
            # Only the owned export tree is traversed, never symlink targets. Reader
            # permission failures must not make raw exports impossible to clean.
            for folder, directories, files in os.walk(path, topdown=True):
                for child in [Path(folder), *(Path(folder) / d for d in directories)]:
                    if not child.is_symlink():
                        child.chmod(child.stat().st_mode | 0o700)
            shutil.rmtree(path)
        except OSError as exc:
            raise DiagnosticError(
                "delete PST export",
                path,
                str(exc),
                "a removable directory",
                exc,
                "restore directory permissions and retry clean",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc


def prepare(source, outputs, fingerprint, provenance, config, args):
    root, stamp = outputs["extract"], outputs["extract_done"]
    valid = False
    if stamp.exists():
        try:
            value = json.loads(stamp.read_text())
            extract_stamp.validate(value)
            old = value["fingerprint"]
            valid = all(
                old[k] == v
                for k, v in fingerprint.items()
                if k in ("size", "mtime_ns") or old[k] is not None and v is not None
            )
            valid &= (root / "pst.export").exists() == (source["reader"] == "pffexport")
        except (ValueError, OSError) as exc:
            raise problem(
                source, "cannot read extract/.done", "a valid private stamp", exc
            ) from exc
    if args.reparse == source["label"] and not valid:
        raise DiagnosticError(
            "reparse PST",
            source["label"],
            "no matching retained export",
            "extract/.done with the current fingerprint",
            None,
            f"--restart {source['label']} re-exports the PST",
        )
    if args.restart == source["label"]:
        valid = False
    if valid:
        return Reader(source, root, {"elapsed_s": 0.0, "dump_bytes": size(root)})
    remove(root)
    # The marker writer creates 0700 parents outside git before invoking a binary.
    write_json(
        root / ".preparing",
        extract_stamp.build(
            **{k: v for k, v in provenance.items() if k != "lexicons"}, fingerprint=fingerprint
        ),
    )
    reader = source["reader"]
    if reader == "pffexport":
        argv = [reader, "-m", "items", "-f", "text", "-q", "-t", str(root / "pst"), source["path"]]
    else:
        argv = [
            reader,
            "-r",
            "-8",
            "-b",
            "-q",
            "-j",
            str(config["ingest"]["readpst_jobs"]),
            "-t",
            "e",
            "-o",
            str(root),
            source["path"],
        ]
    if args.verbose:
        print(shlex.join(argv), file=sys.stderr)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, umask=0o077
        )
        while True:
            try:
                _, stderr = process.communicate(timeout=30)
                break
            except subprocess.TimeoutExpired:
                print(
                    f"extract [{source['label']}]: {int(time.monotonic() - started)} s, "
                    f"{size(root)} bytes",
                    file=sys.stderr,
                )
        if process.returncode:
            cause = subprocess.CalledProcessError(process.returncode, argv, stderr=stderr)
            raise problem(
                source,
                f"{reader} on {source['path']} exited {process.returncode}, "
                f"stderr {stderr.decode(errors='replace')!r} "
                f"({reader} {source['_reader_version']})",
                "exit 0",
                cause,
            ) from cause
    except OSError as exc:
        raise problem(
            source, f"execute {reader} on {source['path']}: {exc}", "exit 0", exc
        ) from exc
    write_json(
        stamp,
        extract_stamp.build(
            **{k: v for k, v in provenance.items() if k != "lexicons"}, fingerprint=fingerprint
        ),
    )
    (root / ".preparing").unlink()
    return Reader(
        source, root, {"elapsed_s": round(time.monotonic() - started, 4), "dump_bytes": size(root)}
    )


class Reader:
    def __init__(self, source, root, extraction):
        self.source, self.root, self.extraction = source, root, extraction
        self.pff = source["reader"] == "pffexport"
        self.selected, self.all_items, self.folders = [], [], []
        self.errors, self.skipped_folders, self.skipped_messages = [], 0, 0
        wanted = {s.casefold() for s in source["sent_folders"]}
        found = []
        base = root / "pst.export" if self.pff else root

        def onerror(exc):
            path = Path(exc.filename)
            if wanted.intersection(p.casefold() for p in path.relative_to(base).parts):
                self.folder_error(path, exc)

        for folder, directories, files in os.walk(base, onerror=onerror):
            directories.sort()
            path = Path(folder)
            relative = path.relative_to(base)
            selected = bool(wanted.intersection(p.casefold() for p in relative.parts))
            found.append(str(relative))
            if selected and not path.stat().st_mode & 0o444:
                self.folder_error(path, PermissionError("folder mode has no read bits"))
                directories[:] = []
                continue
            if self.pff:
                items = [path / d for d in directories if pst_pffexport.ITEM.fullmatch(d)]
                directories[:] = [d for d in directories if not pst_pffexport.ITEM.fullmatch(d)]
            else:
                items = [path / "mbox"] if "mbox" in files else []
            self.all_items.extend(items)
            if selected:
                self.selected.extend(items)
            elif items:
                self.skipped_folders += 1
                self.skipped_messages += (
                    len(items) if self.pff else sum(1 for _ in mbox.messages(items))
                )
        self.selected.sort()
        if not self.selected and not self.errors:
            print(
                f"ingest[{source['label']}]: folders found: " + repr(sorted(found)[:50]),
                file=sys.stderr,
            )
            raise problem(
                source,
                "no folder matched sent_folders",
                "at least one matching folder; check sent_folders in config.toml",
                operator=True,
            )

    def folder_identity(self, path):
        return (
            "folder-" + hashlib.sha256(str(path.relative_to(self.root)).encode()).hexdigest()[:16]
        )

    def folder_error(self, path, exc):
        identifier = self.folder_identity(path)
        if any(f["name"] == identifier for f in self.errors):
            return
        # Folder names and exception filenames cannot enter reports.
        error = problem(
            self.source,
            f"read {identifier}: {type(exc).__name__}",
            "a readable selected folder",
            type(exc).__name__,
        )
        self.errors.append(
            {
                "name": identifier,
                "messages_seen": 0,
                "records": 0,
                "rejects": 0,
                "error": str(error),
            }
        )

    def harvest(self, config):
        values, names = [], set()
        for path in sorted(self.all_items):
            try:
                if self.pff:
                    message, mail = pst_pffexport.parse(path, "headers", headers_only=True)
                    values.extend(r.display_name for r in message.recipients)
                    values.append(message.sender_name)
                    names.update(scrub.harvest(mail, config["owner"]["names"], config["ingest"]))
                    # Preserve header names even when the full parse rejects a
                    # header-only or non-mail item, then harvest before stripping.
                    _, mail = pst_pffexport.parse(path, "harvest")
                    names.update(scrub.harvest(mail, config["owner"]["names"], config["ingest"]))
                else:
                    for index, raw in mbox.messages([path]):
                        message, mail = pst_readpst.parse(raw, "headers")
                        values.extend(r.display_name for r in message.recipients)
                        values.append(message.sender_name)
                        names.update(
                            scrub.harvest(mail, config["owner"]["names"], config["ingest"])
                        )
            except (OSError, ValueError, Rejected):
                # The selected parse pass records item rejects or folder errors.
                continue
        return names | scrub.name_tokens(values, config["owner"]["names"])

    def messages(self, paths=None, *, boundaries=False):
        # Folder paths are hashed, never correspondent values or raw folder names.
        # Keep the ordinary message-only iterator for header/body consumers.
        groups = {}
        for path in self.selected:
            groups.setdefault(path.parent, []).append(path)
        self.folders = []
        index = 0
        for folder, items in sorted(groups.items()):
            self.current_folder = {
                "name": self.folder_identity(folder),
                "messages_seen": 0,
                "records": 0,
                "rejects": 0,
                "error": None,
            }
            self.folders.append(self.current_folder)
            for message_index, value in self.folder_messages(items, index):
                yield message_index, value
                index = message_index + 1
            if boundaries:
                yield index, None

    def folder_messages(self, items, index):
        for path in items:
            if self.pff:
                try:
                    value = pst_pffexport.parse(path, f"pst:messages/{index}")
                except (OSError, ValueError) as exc:
                    value = Rejected("parse_error", exc)
                except Rejected as exc:
                    value = exc
                yield index, value
                index += 1
            else:
                try:
                    if not path.stat().st_mode & 0o444:
                        raise PermissionError("mbox mode has no read bits")
                    for _, raw in mbox.messages([path]):
                        try:
                            value = pst_readpst.parse(raw, f"pst:messages/{index}")
                            if any(
                                type(d).__name__ == "CloseBoundaryNotFoundDefect"
                                for part in value[1].walk()
                                for d in part.defects
                            ):
                                self.folder_error(
                                    path.parent, ValueError("truncated MIME boundary")
                                )
                                continue
                        except ValueError as exc:
                            value = Rejected("parse_error", exc)
                        yield index, value
                        index += 1
                except OSError as exc:
                    self.folder_error(path.parent, exc)
