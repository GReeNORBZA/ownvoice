"""Thin argparse surface, command dispatch and diagnostic reporting."""

import argparse
import importlib
import os
import re
import sys
import traceback

from ownvoice.config import MEDIA
from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors, internal_error


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DiagnosticError(
            "parse command arguments",
            self.prog,
            message,
            "arguments matching --help",
            None,
            f"run {self.prog} --help",
        )


class VerboseLogger:
    """Only opaque record IDs and rule IDs enter verbose event output."""

    def __init__(self, enabled=False, stream=None):
        self.enabled = enabled
        self.stream = stream if stream is not None else sys.stderr

    def event(self, *, record_id, rule_id):
        if not isinstance(record_id, str) or not re.fullmatch(r"[a-f0-9]{16}", record_id):
            raise DiagnosticError(
                "log record event",
                "record_id",
                "invalid identifier",
                "16 hex characters",
                None,
                "pass the hashed record id, never message content",
            )
        if not isinstance(rule_id, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]{0,63}", rule_id
        ):
            raise DiagnosticError(
                "log rule event",
                "rule_id",
                "invalid identifier",
                "an opaque rule id",
                None,
                "pass a rule id, never message content",
            )
        if self.enabled:
            print(f"record_id={record_id} rule_id={rule_id}", file=self.stream)


def build_parser():
    parser = Parser(prog="ownvoice", description="Private, deterministic owner voice pipeline")
    parser.add_argument(
        "--config", default=os.environ.get("OWNVOICE_CONFIG", "~/.config/ownvoice/config.toml")
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Extract scrubbed owner messages")
    for flag in ("only", "restart", "reparse", "source", "label"):
        ingest.add_argument("--" + flag)
    ingest.add_argument("--keep-extracted", action="store_true")
    ingest.add_argument("--owner", action="append")
    profile = commands.add_parser("profile", help="Compute statistics and exemplars")
    for flag in ("records", "sources", "edit-delta", "articles", "out-dir"):
        profile.add_argument("--" + flag)
    for flag in ("allow-partial", "allow-stale-dump"):
        profile.add_argument("--" + flag, action="store_true")
    lint = commands.add_parser("lint", help="Lint a draft against its register")
    lint.add_argument("draft")
    for flag in ("stats", "register"):
        lint.add_argument("--" + flag, required=True)
    lint.add_argument("--medium", required=True, choices=MEDIA)
    for flag in ("source", "rules", "out"):
        lint.add_argument("--" + flag)
    lint.add_argument("--format", choices=("json", "text"), default="text")
    delta = commands.add_parser("edit-delta", help="Measure changes across draft versions")
    delta.add_argument("--chains")
    delta.add_argument("--out")
    delta_commands = delta.add_subparsers(dest="delta_command")
    discover = delta_commands.add_parser("discover")
    discover.add_argument("--dir", required=True)
    discover.add_argument("--git", action="store_true")
    discover.add_argument("--out")
    compare = delta_commands.add_parser("compare")
    compare.add_argument("--pairs", required=True)
    compare.add_argument("--out", required=True)
    qual = commands.add_parser("qual", help="Run qualitative-pass helpers")
    qual_commands = qual.add_subparsers(dest="qual_command", required=True)
    chunk = qual_commands.add_parser("chunk")
    chunk.add_argument("--records", required=True)
    chunk.add_argument("--articles")
    chunk.add_argument("--pass", dest="pass_name", choices=("A", "B"), required=True)
    chunk.add_argument("--sample-words", type=int)
    chunk.add_argument("--max-tokens", type=int, default=10000)
    chunk.add_argument("--out", required=True)
    status = qual_commands.add_parser("status")
    status.add_argument("--manifest", required=True)
    ground = qual_commands.add_parser("ground")
    for flag in ("manifest", "findings", "out"):
        ground.add_argument("--" + flag, required=True)
    ground.add_argument("--threshold", type=float, default=0.85)
    reconcile = qual_commands.add_parser("reconcile")
    for flag in ("candidate", "existing", "out"):
        reconcile.add_argument("--" + flag, required=True)
    merge = qual_commands.add_parser("merge")
    for flag in ("existing", "add", "out"):
        merge.add_argument("--" + flag, required=True)
    guard = commands.add_parser("guard", help="Check the publish boundary")
    selection = guard.add_mutually_exclusive_group()
    selection.add_argument("--staged", action="store_true")
    selection.add_argument("--tree")
    guard.add_argument("--release", action="store_true")
    guard.add_argument("--names-file")
    clean = commands.add_parser("clean", help="Delete retained private intermediates")
    targets = clean.add_mutually_exclusive_group(required=True)
    targets.add_argument("--extracted")
    targets.add_argument("--all", action="store_true")
    targets.add_argument("--chunks")
    config = commands.add_parser("config", help="Validate configuration and show resolved paths")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--format", choices=("json",), default=None)
    return parser


def main(argv=None):
    args = None
    try:
        args = build_parser().parse_args(argv)
        if args.command == "edit-delta" and not args.delta_command and not args.chains:
            raise DiagnosticError(
                "parse command arguments",
                "edit-delta --chains",
                "no chains supplied",
                "--chains PATH or discover/compare subcommand",
                None,
                "run ownvoice edit-delta --help",
            )
        args.logger = VerboseLogger(args.verbose and not args.quiet)
        module = importlib.import_module("ownvoice.commands." + args.command.replace("-", "_"))
        return module.run(args)
    except (DiagnosticError, ValidationErrors) as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # noqa: BLE001 - final CLI boundary renders the bug contract and traceback
        error = internal_error("run command", args.command if args else "ownvoice", exc)
        print(str(error), file=sys.stderr)
        traceback.print_exception(exc, file=sys.stderr)
        return int(ExitCode.INTERNAL)
