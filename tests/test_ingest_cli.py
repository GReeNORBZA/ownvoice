import copy
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ownvoice.cli import VerboseLogger
from ownvoice.config import load_config
from ownvoice.errors import DiagnosticError, ValidationErrors
from ownvoice.ingest.preflight import preflight
from ownvoice.ingest.run import process_source, rejection
from ownvoice.io import PRIVATE_KEY
from ownvoice.schemas import ingest_report, records, rejects, unmapped_domains
from tests.test_ingest_extract import cases, raw_message


def signature_cases():
    """A learned suffix, two empty outcomes, and both final-text confidence gates."""
    bodies = ["Please review the plan.\nThanks,\nOwner\nEngineer\nExample Company"] * 10
    bodies += [
        "--\nOwner\nEngineer",
        "Engineer\nExample Company",
        "The work is ready.\n--\n" + "word " * 3001,
        "The work is ready.\n--\nSubject: engineer",
        "word " * 3001 + "\n--\nEngineer",
        "Subject: review\nThe work is ready.\n--\nEngineer",
    ]
    return [{"id": f"signature-{i}", "body": body, "html": False} for i, body in enumerate(bodies)]


def assert_signature_outputs(rows, rejected, report):
    assert (len(rows), len(rejected), report["messages_seen"], report["selected"]) == (
        14,
        2,
        16,
        16,
    )
    assert [r["reason"] for r in rejected] == ["empty_after_strip"] * 2
    assert report["rejected_by_reason"] == {"empty_after_strip": 2}
    assert report["low_confidence"] == report["low_confidence_excluded"] == 2
    assert all(row["text"] and row["word_count"] for row in rows)
    assert all("signature-fingerprint" in row["strip"]["rules_fired"] for row in rows[:10])
    for row in rows[10:12]:
        assert row["text"] == "The work is ready."
        assert row["word_count"] == 4
        assert row["strip"]["confidence"] == "high"
        assert row["strip"]["flags"] == []
        assert "sig-dash" in row["strip"]["rules_fired"]
    for row, flag in zip(rows[12:], ("long_body", "residual_marker")):
        assert row["strip"]["flags"] == [flag]
        assert row["strip"]["confidence"] == "low"


class IngestCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / "work"
        self.config = self.root / "config.toml"
        (self.root / "domain-map.toml").write_text("schema_version = 1\n")
        (self.root / "rules.md").write_text("Synthetic editorial rules.\n")
        self.fixture_cases = {case["id"]: case for case in cases()}

    def configure(self, sources, work=None, extra=""):
        text = f"""schema_version = 1
[owner]
addresses = ["owner@example.com"]
names = ["Owner"]
timezone = "America/Edmonton"
[paths]
work_dir = {json.dumps(str(work or self.work))}
domain_map = "domain-map.toml"
editorial_rules = "rules.md"
"""
        for source in sources:
            text += "\n[[source]]\n"
            for key, value in source.items():
                text += key + " = " + json.dumps(value) + "\n"
        self.config.write_text(text + extra)

    def source(self, label="synthetic", kind="mbox", path=None, **extra):
        return {"label": label, "kind": kind, "path": str(path or self.root / "mail.mbox"), **extra}

    def mbox(self, selected):
        path = self.root / "mail.mbox"
        with path.open("wb") as out:
            for case in selected:
                out.write(b"From owner@example.com Tue Jan 20 01:30:00 2026\n")
                out.write(raw_message(case))
                out.write(b"\n")
        return path

    def cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                str(self.config),
                "--verbose",
                "ingest",
                *args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def read_outputs(self, label="synthetic"):
        folder = self.work / "sources" / label
        rows = [json.loads(line) for line in (folder / "records.jsonl").read_text().splitlines()]
        rejected = [
            json.loads(line) for line in (folder / "rejects.jsonl").read_text().splitlines()
        ]
        report = json.loads((folder / "ingest-report.json").read_text())
        ingest_report.validate(report)
        for row in rows:
            records.validate(row)
        for row in rejected:
            rejects.validate(row)
            for part in ("parse message", label, "expected", "next step:"):
                self.assertIn(part, row["detail"])
        for path in self.work.rglob("*"):
            self.assertEqual(0o700 if path.is_dir() else 0o600, path.stat().st_mode & 0o777, path)
            if path.suffix == ".jsonl":
                for line in path.read_text().splitlines():
                    self.assertEqual("private", json.loads(line)[PRIVATE_KEY])
        self.assertEqual(0o700, self.work.stat().st_mode & 0o777)
        return rows, rejected, report

    def test_randomized_mbox_conservation_privacy_progress_and_wiring(self):
        rng = random.Random(2700)
        candidates = [
            self.fixture_cases[x]
            for x in (
                "F01",
                "F02",
                "F08",
                "F16",
                "F17",
                "F22",
                "F23-partial",
                "F23-reject",
                "F25",
                "F42-Chat",
                "F42-Drafts",
                "F42-Spam",
                "F42-Trash",
            )
        ]
        selected = [copy.deepcopy(rng.choice(candidates)) for _ in range(270)]
        # Distinct messages keep this C3 extraction test independent of C4 dedup.
        for index, case in enumerate(selected):
            case["id"] += f"-{index}"
        stranger = copy.deepcopy(self.fixture_cases["F01"])
        stranger.update(sender="stranger@example.net", body="not owner sentinel")
        selected.append(stranger)
        self.mbox(selected)
        self.configure([self.source()])
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, rejected, report = self.read_outputs()
        self.assertEqual(len(selected), report["messages_seen"])
        self.assertEqual(len(selected), len(rows) + len(rejected))
        self.assertEqual(sum(c["reason"] is None for c in selected) - 1, len(rows))
        self.assertIn("250 messages", result.stderr)
        self.assertIn("record_id=", result.stderr)
        self.assertNotIn("not implemented yet", result.stderr)
        rejects_text = (self.work / "sources/synthetic/rejects.jsonl").read_text()
        for sentinel in (
            "secret quote",
            "calendar sentinel",
            "excluded sentinel",
            "not owner sentinel",
            "Owner note.",
            "owner@example.com",
            "stranger@example.net",
        ):
            self.assertNotIn(sentinel, rejects_text)
            self.assertNotIn(sentinel, result.stderr)
        self.assertTrue(any(row["text"] == "From the start we agreed." for row in rows))
        self.assertTrue(
            any("missing_date" in row["strip"]["flags"] and row["year"] is None for row in rows)
        )
        self.assertEqual(
            rows,
            [json.loads(line) for line in (self.work / "records.jsonl").read_text().splitlines()],
        )
        summary = json.loads((self.work / "unmapped-domains.json").read_text())
        unmapped_domains.validate(summary)
        self.assertEqual("example.net", summary["domains"][0]["domain"])

    def test_signature_final_text_gates_for_eml_and_mbox(self):
        for kind in ("eml", "mbox"):
            with self.subTest(kind=kind):
                self.work = self.root / f"work-{kind}"
                if kind == "mbox":
                    path = self.mbox(signature_cases())
                else:
                    path = self.root / "emls"
                    path.mkdir()
                    for i, case in enumerate(signature_cases()):
                        (path / f"{i:03}.eml").write_bytes(raw_message(case))
                self.configure([self.source(kind=kind, path=path)])
                result = self.cli()
                self.assertEqual(0, result.returncode, result.stderr)
                assert_signature_outputs(*self.read_outputs())

    def test_signature_only_source_refused_for_eml_and_mbox(self):
        for kind in ("eml", "mbox"):
            with self.subTest(kind=kind):
                self.work = self.root / f"empty-{kind}"
                case = signature_cases()[10]
                if kind == "mbox":
                    path = self.mbox([case])
                else:
                    path = self.root / "signature.eml"
                    path.write_bytes(raw_message(case))
                self.configure([self.source(kind=kind, path=path)])
                result = self.cli()
                self.assertEqual(2, result.returncode, result.stderr)
                for part in (
                    "ingest",
                    "synthetic",
                    "no owner-sent messages",
                    "expected",
                    "next step:",
                ):
                    self.assertIn(part, result.stderr)
                rows, rejected, report = self.read_outputs()
                self.assertEqual([], rows)
                self.assertEqual(["empty_after_strip"], [r["reason"] for r in rejected])
                self.assertEqual(
                    (1, 1, "failed"),
                    (report["messages_seen"], report["selected"], report["status"]),
                )
                state = json.loads((self.work / "sources/synthetic/checkpoint.json").read_text())
                self.assertEqual(
                    (1, 0, 1), (state["message_index"], state["records"], state["rejects"])
                )
                self.assertFalse(state["state"]["complete"])

    def test_signature_recheck_preserves_independent_confidence_evidence(self):
        directory = self.root / "emls"
        directory.mkdir()
        expected = [
            ("body_mismatch", "low"),
            ("inline_suspected", "low"),
            ("inline_html_suspected", "low"),
            ("decode_error_partial", "high"),
            ("missing_date", "high"),
        ]
        for i, (flag, _) in enumerate(expected):
            mail = EmailMessage()
            mail["From"] = "owner@example.com"
            mail["Message-ID"] = f"<evidence-{i}@example.com>"
            if flag != "missing_date":
                mail["Date"] = "Tue, 20 Jan 2026 01:30:00 +0000"
            body = "The work is ready.\n--\nSubject: engineer\n"
            if flag == "body_mismatch":
                mail.set_content("plain " * 100)
                mail.add_alternative(
                    "<p>" + "ready " * 12 + "</p><p>--</p><p>Subject: engineer</p>", subtype="html"
                )
            elif flag == "inline_html_suspected":
                mail.set_content(
                    "<p>The work is ready.</p><p>--</p><p>Subject: engineer</p><blockquote>quoted</blockquote><p>answer</p>",
                    subtype="html",
                )
            elif flag == "inline_suspected":
                mail.set_content(
                    "See my answers below.\n"
                    + body
                    + "-----Original Message-----\npossible owner answer"
                )
            elif flag == "decode_error_partial":
                mail.set_content(body + "bad byte \ufffd")
            else:
                mail.set_content(body)
            (directory / f"{i:03}.eml").write_bytes(mail.as_bytes())
        self.configure([self.source(kind="eml", path=directory)])
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, rejected, _ = self.read_outputs()
        self.assertEqual([], rejected)
        self.assertEqual(len(expected), len(rows))
        for row, (flag, confidence) in zip(rows, expected):
            self.assertEqual([flag], row["strip"]["flags"])
            self.assertEqual(confidence, row["strip"]["confidence"])

    def test_eml_directory_sorting_and_every_fixture_via_cli(self):
        directory = self.root / "emls"
        directory.mkdir()
        nested = directory / "nested"
        nested.mkdir()
        selected = [case for case in cases() if not case.get("mboxrd") and not case.get("patterns")]
        for i, case in enumerate(selected):
            (nested / f"{i:03}.eml").write_bytes(raw_message(case))
        self.configure([self.source(kind="eml", path=directory)])
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, _rejected, report = self.read_outputs()
        self.assertEqual(len(selected), report["messages_seen"])
        expected = [case for case in selected if not case["reason"]]
        self.assertEqual(len(expected), len(rows))
        for case, row in zip(expected, rows):
            self.assertEqual(
                case.get("scrubbed_expected", case["expected"]), row["text"], case["id"]
            )
            self.assertEqual(case["rules"], row["strip"]["rules_fired"], case["id"])
            self.assertEqual(case["thread"], row["thread_position"], case["id"])
            self.assertEqual(case["confidence"], row["strip"]["confidence"], case["id"])
        self.assertIn("excluded_label", report["rejected_by_reason"])

    def test_F27_aggregate_preflight_no_outputs(self):
        pst = self.root / "empty.pst"
        pst.touch()
        mbox = self.mbox([self.fixture_cases["F01"]])
        mbox.chmod(0)
        self.configure([self.source("empty", "pst", pst), self.source("unreadable", path=mbox)])
        with patch.dict(os.environ, {"PATH": ""}):
            result = self.cli()
        self.assertEqual(2, result.returncode, result.stderr)
        for part in (
            "pffexport not found on PATH",
            str(pst),
            str(mbox),
            "preflight ingest",
            "empty",
            "0 bytes",
            "unreadable",
            "expected",
            "next step:",
        ):
            self.assertIn(part, result.stderr)
        self.assertFalse(self.work.exists())

    def test_F31_git_boundaries_and_explicit_source_exception(self):
        tree = self.root / "tree"
        tree.mkdir()
        (tree / ".git").mkdir()
        source = self.mbox([self.fixture_cases["F01"]])
        self.configure([self.source(path=source)], work=tree / "private-output")
        result = self.cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("work_dir is inside a git working tree", result.stderr)
        self.assertFalse((tree / "private-output").exists())
        inside = tree / "mail.mbox"
        inside.write_bytes(source.read_bytes())
        self.configure([self.source(path=inside)])
        result = self.cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("source is inside a git working tree", result.stderr)
        self.assertFalse(self.work.exists())
        self.configure([self.source(path=inside, allow_inside_git_tree=True)])
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self.read_outputs()[2]["allow_inside_git_tree"])

    def test_zero_owner_wording_and_selection(self):
        case = copy.deepcopy(self.fixture_cases["F01"])
        case["sender"] = "stranger@example.net"
        self.mbox([case])
        self.configure([self.source()])
        result = self.cli()
        self.assertEqual(2, result.returncode)
        for part in (
            "no owner-sent messages",
            "0 of 1 messages matched owner_addresses or sent_folders",
            "expected at least 1",
            "Check the file copied completely and the addresses/folders in config.toml",
        ):
            self.assertIn(part, result.stderr)
        rows, rejected, _report = self.read_outputs()
        self.assertEqual([], rows)
        self.assertEqual("not_owner", rejected[0]["reason"])

    def test_source_order_only_ad_hoc_and_t7(self):
        first = self.mbox([self.fixture_cases["F01"]])
        second = self.root / "single.eml"
        second.write_bytes(raw_message(self.fixture_cases["F35"]))
        self.configure(
            [self.source("one", path=first)],
            extra='\n[ingest]\nextra_attribution_patterns = ["^Am .* schrieb jemand:$"]\n',
        )
        result = self.cli(
            "--source", "eml:" + str(second), "--label", "two", "--owner", "owner@example.com"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        merged = [
            json.loads(line) for line in (self.work / "records.jsonl").read_text().splitlines()
        ]
        self.assertEqual(["one", "two"], [r["source"] for r in merged])
        self.assertEqual(["T7"], merged[1]["strip"]["rules_fired"])
        self.configure([self.source("one", path=first), self.source("two", "eml", second)])
        result = self.cli("--only", "two")
        self.assertEqual(0, result.returncode, result.stderr)
        # Selection limits processing, while completed sources retain configured priority.
        self.assertEqual(
            ["one", "two"],
            [
                json.loads(line)["source"]
                for line in (self.work / "records.jsonl").read_text().splitlines()
            ],
        )

    def test_error_paths_operation_identity_next_step(self):
        valid = self.mbox([self.fixture_cases["F01"]])
        self.configure([self.source(path=valid)])
        for args, identity in [
            (["--only", "absent"], "--only"),
            (["--source", "bad"], "--source"),
            (["--owner", "owner@example.com"], "--source"),
            (["--restart", "absent"], "--restart"),
            (["--reparse", "absent"], "--reparse"),
            (
                ["--source", "eml:x", "--label", "synthetic", "--owner", "owner@example.com"],
                "--label",
            ),
        ]:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(2, result.returncode)
                for part in ("preflight ingest", identity, "expected", "next step:"):
                    self.assertIn(part, result.stderr)
                self.assertFalse(self.work.exists())
        for name, content in [
            ("missing.mbox", None),
            ("wrong.mbox", b"not a mailbox"),
            ("bad.ost", b"!BDNdata"),
        ]:
            path = self.root / name
            if content:
                path.write_bytes(content)
            self.configure([self.source(path=path)])
            result = self.cli()
            self.assertEqual(2, result.returncode)
            for part in ("preflight ingest", "synthetic", name, "expected", "next step:"):
                self.assertIn(part, result.stderr)
        self.configure([self.source(path=valid)], work=valid)
        self.assertIn("destination is not writable", self.cli().stderr)

    def test_io_and_rejection_diagnostics(self):
        valid = self.mbox([self.fixture_cases["F01"]])
        self.configure([self.source(path=valid)])
        config, domain_map = load_config(self.config)
        error = PermissionError("synthetic permission failure")
        args = SimpleNamespace(logger=VerboseLogger(), quiet=True)
        with (
            patch("ownvoice.readers.mbox.messages", side_effect=error),
            self.assertRaises(DiagnosticError) as caught,
        ):
            process_source(config, domain_map, config["source"][0], [valid], args)
        self.assertIs(error, caught.exception.__cause__)
        self.assertEqual(3, caught.exception.exit_code)
        for part in ("read ingest source", "synthetic", "expected", "next step:"):
            self.assertIn(part, str(caught.exception))
        source = copy.deepcopy(config["source"][0])
        source["path"] = str(self.root / "absent")
        with self.assertRaises(ValidationErrors) as caught:
            preflight(config, [source])
        self.assertIsInstance(caught.exception.errors[0].__cause__, FileNotFoundError)
        for reason in (
            "not_owner",
            "excluded_label",
            "empty_after_strip",
            "no_text_body",
            "encrypted",
            "non_mail_item",
            "parse_error",
            "decode_error",
            "out_of_range_year",
        ):
            detail = rejection(
                "eml:synthetic#messages/0", None, reason, "synthetic", ValueError("PRIVATE BODY")
            )["detail"]
            for part in ("parse message", "synthetic", reason, "expected", "next step:"):
                self.assertIn(part, detail)
            self.assertNotIn("PRIVATE BODY", detail)

    def test_era_warning_and_unknown_names_counts(self):
        case = copy.deepcopy(self.fixture_cases["F18"])
        raw = raw_message(case).replace(
            b"Other <other@example.net>", b"Unmapped Name <name@example.net>"
        )
        path = self.root / "single.eml"
        path.write_bytes(raw)
        self.configure([self.source(kind="eml", path=path)])
        result = self.cli()
        self.assertEqual(0, result.returncode)
        self.assertIn("low-confidence share exceeds 10%", result.stderr)
        self.assertIn("residual_marker", result.stderr)
        self.assertNotIn("Unmapped Name", result.stderr)
        config, domain_map = load_config(self.config)
        config["source"][0]["era"] = {"from_year": 2010, "to_year": 2019}
        with redirect_stderr(io.StringIO()):
            result = process_source(
                config,
                domain_map,
                config["source"][0],
                [path],
                SimpleNamespace(logger=VerboseLogger(), quiet=True),
            )
        self.assertEqual("out_of_range_year", result[1][0]["reason"])
