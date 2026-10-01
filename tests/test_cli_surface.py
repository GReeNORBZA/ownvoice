import argparse
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from ownvoice.cli import VerboseLogger, build_parser, main
from ownvoice.errors import DiagnosticError, ExitCode, internal_error

# Independent inventory transcribed from FRD section 6, including argparse help.
EXPECTED_FRD_COMMANDS = {
    "": {"--config", "--verbose", "--quiet", "-h", "--help"},
    "ingest": {
        "--only",
        "--restart",
        "--keep-extracted",
        "--reparse",
        "--source",
        "--label",
        "--owner",
        "-h",
        "--help",
    },
    "profile": {
        "--records",
        "--sources",
        "--allow-partial",
        "--allow-stale-dump",
        "--edit-delta",
        "--articles",
        "--out-dir",
        "-h",
        "--help",
    },
    "lint": {
        "--stats",
        "--register",
        "--medium",
        "--source",
        "--rules",
        "--format",
        "--out",
        "-h",
        "--help",
    },
    "edit-delta": {"--chains", "--out", "-h", "--help"},
    "edit-delta discover": {"--dir", "--git", "--out", "-h", "--help"},
    "edit-delta compare": {"--pairs", "--out", "-h", "--help"},
    "qual": {"-h", "--help"},
    "qual chunk": {
        "--records",
        "--articles",
        "--pass",
        "--sample-words",
        "--max-tokens",
        "--out",
        "-h",
        "--help",
    },
    "qual status": {"--manifest", "-h", "--help"},
    "qual ground": {"--manifest", "--findings", "--threshold", "--out", "-h", "--help"},
    "qual reconcile": {"--candidate", "--existing", "--out", "-h", "--help"},
    "qual merge": {"--existing", "--add", "--out", "-h", "--help"},
    "guard": {"--staged", "--tree", "--release", "--names-file", "-h", "--help"},
    "clean": {"--extracted", "--all", "--chunks", "-h", "--help"},
    "config": {"-h", "--help"},
    "config show": {"--format", "-h", "--help"},
}


class CliTests(unittest.TestCase):
    def test_lint_is_implemented(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                "/nonexistent/c9-config.toml",
                "lint",
                "draft.md",
                "--stats",
                "stats.json",
                "--register",
                "client",
                "--medium",
                "email",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("load TOML", result.stderr)
        self.assertNotIn("not implemented yet", result.stderr)

    def test_profile_is_implemented(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                "/nonexistent/c7-config.toml",
                "profile",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("load TOML", result.stderr)
        self.assertNotIn("not implemented yet", result.stderr)

    def test_guard_is_implemented(self):
        self.assertEqual(0, main(["guard", "--tree", "."]))

    def test_ingest_is_implemented(self):
        result = subprocess.run(
            [sys.executable, "-m", "ownvoice", "--config", "/nonexistent/c3-config.toml", "ingest"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("load TOML", result.stderr)
        self.assertNotIn("not implemented yet", result.stderr)

    def test_clean_is_implemented(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                "/nonexistent/c6-config.toml",
                "clean",
                "--all",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("load TOML", result.stderr)
        self.assertNotIn("not implemented yet", result.stderr)

    def test_exact_surface(self):
        actual = {}

        def visit(parser, prefix=""):
            actual[prefix] = {flag for action in parser._actions for flag in action.option_strings}
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, child in action.choices.items():
                        visit(child, (prefix + " " + name).strip())

        visit(build_parser())
        self.assertEqual(EXPECTED_FRD_COMMANDS, actual)
        parsed = build_parser().parse_args(
            [
                "lint",
                "draft.md",
                "--stats",
                "stats.json",
                "--register",
                "client",
                "--medium",
                "email",
            ]
        )
        self.assertEqual("draft.md", parsed.draft)
        parsed = build_parser().parse_args(
            ["ingest", "--owner", "one@example.com", "--owner", "two@example.com"]
        )
        self.assertEqual(["one@example.com", "two@example.com"], parsed.owner)

    def test_edit_delta_commands_are_implemented(self):
        commands = [
            ["edit-delta", "--chains", "chains.toml"],
            ["edit-delta", "discover", "--dir", "/nonexistent/c10-articles"],
            ["edit-delta", "compare", "--pairs", "ac14.toml", "--out", "ac14.json"],
        ]
        for args in commands:
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, "-m", "ownvoice", "--config", "/nonexistent/c10.toml", *args],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                for fragment in (
                    "load TOML",
                    "expected",
                    "next step:",
                ):
                    self.assertIn(fragment, result.stderr)
                self.assertNotIn("not implemented yet", result.stderr)

    def test_qual_commands_are_implemented(self):
        commands = [
            ["qual", "chunk", "--records", "r.jsonl", "--pass", "A", "--out", "m.json"],
            ["qual", "status", "--manifest", "m.json"],
            ["qual", "ground", "--manifest", "m.json", "--findings", "f.jsonl", "--out", "g.jsonl"],
            [
                "qual",
                "reconcile",
                "--candidate",
                "g.jsonl",
                "--existing",
                "f.json",
                "--out",
                "d.json",
            ],
            ["qual", "merge", "--existing", "f.json", "--add", "d.json", "--out", "f.json"],
            ["clean", "--chunks", "/nonexistent/c11-manifest.json"],
        ]
        for args in commands:
            with self.subTest(args=args):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ownvoice",
                        "--config",
                        "/nonexistent/c11-config.toml",
                        *args,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertIn(result.returncode, (2, 3), result.stderr)
                self.assertNotIn("not implemented yet", result.stderr)
                self.assertIn("expected", result.stderr)
                self.assertIn("next step:", result.stderr)

    def test_help_and_operator_errors(self):
        result = subprocess.run(
            [sys.executable, "-m", "ownvoice", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        for command in (key for key in EXPECTED_FRD_COMMANDS if key and " " not in key):
            self.assertIn(command, result.stdout)
        for args in (
            ["bogus"],
            ["edit-delta"],
            ["guard", "--tree", ".", "--staged"],
            ["clean", "--all", "--chunks", "m.json"],
        ):
            stream = io.StringIO()
            with redirect_stderr(stream):
                self.assertEqual(2, main(args))
            self.assertIn("parse command arguments", stream.getvalue())
            self.assertIn("next step:", stream.getvalue())

    def test_errors_preserve_cause_and_internal_bug_contract(self):
        cause = ValueError("specific underlying cause")
        error = internal_error("compute report", "record-42", cause)
        self.assertIs(cause, error.__cause__)
        for text in (
            "internal error (this is a bug)",
            "record-42",
            "expected",
            str(cause),
            "next step:",
        ):
            self.assertIn(text, str(error))
        stream = io.StringIO()
        with patch("ownvoice.commands.profile.run", side_effect=cause), redirect_stderr(stream):
            self.assertEqual(1, main(["profile"]))
        self.assertIn("ValueError: specific underlying cause", stream.getvalue())
        self.assertEqual(list(range(6)), [int(code) for code in ExitCode])

    def test_verbose_accepts_identifiers_only(self):
        stream = io.StringIO()
        logger = VerboseLogger(True, stream)
        logger.event(record_id="a" * 16, rule_id="T7")
        self.assertEqual("record_id=" + "a" * 16 + " rule_id=T7\n", stream.getvalue())
        for args, field in (
            ({"record_id": "secret@example.com", "rule_id": "T7"}, "record_id"),
            ({"record_id": "a" * 16, "rule_id": "secret@example.com"}, "rule_id"),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                logger.event(**args)
            self.assertIn(field, str(caught.exception))
            self.assertIn("next step:", str(caught.exception))
            self.assertNotIn("secret@example.com", str(caught.exception))

    def test_ci_gate_and_gitignore_contract(self):
        # YAML parsing is also performed as an explicit acceptance check with PyYAML.
        workflow = Path(".github/workflows/ci.yml").read_text()
        for required in (
            "if: always()",
            "needs: [test, guard]",
            "ruff format --check",
            "set -euo pipefail",
            "cancel-in-progress: true",
        ):
            self.assertIn(required, workflow)
        self.assertNotIn('"$code" -eq 5', workflow)
        ignores = Path(".gitignore").read_text().splitlines()
        for pattern in (
            "work/",
            "*.pst",
            "*.ost",
            "*.mbox",
            "mbox",
            "*.eml",
            "*.jsonl",
            "config.toml",
            "domain-map*.toml",
            "!tests/fixtures/**",
        ):
            self.assertIn(pattern, ignores)
