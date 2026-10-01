import json
import re
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from ownvoice.config import DEFAULTS
from ownvoice.errors import DiagnosticError
from ownvoice.extract import scrub
from ownvoice.io import PRIVATE_LINE
from tests import test_ingest_cli


def cases():
    path = Path(__file__).parent / "fixtures/scrub/cases.json"
    return json.loads(path.read_text())


def raw(case, index=0):
    mail = EmailMessage(policy=policy.default)
    mail["From"] = case.get("sender", "Owner <owner@example.com>")
    mail["To"] = "Jane <jane@example.net>"
    mail["Reply-To"] = "Roe <roe@example.net>"
    mail["Date"] = f"Tue, 20 Jan {case.get('year', 2026)} 01:30:00 +0000"
    if not case.get("no_id"):
        mail["Message-ID"] = f"<{case['id']}-{0 if case.get('same_id') else index}@example.com>"
    mail.set_content(case["body"])
    return mail.as_bytes()


def counts(**updates):
    return {
        **dict.fromkeys(
            ("greeting_names", "lexicon_names", "emails", "phones", "urls", "numbers"), 0
        ),
        "residual_capitalised": [],
        **updates,
    }


class ScrubTests(unittest.TestCase):
    def test_patterns_money_deny_and_owner(self):
        text = (
            "Owner can email Jane.Doe@example.net or use https://third.example.net/path. "
            "Please call +1 (780) 555-1234 with 123456 and keep $1234567 or CAD 7654321. "
            "Please ask Jane about Private Company."
        )
        result, greeting, actual = scrub.scrub(
            text, {"Jane", "Doe", "Owner"}, ["Owner"], deny_terms={"Private Company"}
        )
        self.assertEqual(
            "Owner can email [EMAIL] or use [URL]. Please call [PHONE] with [NUM] "
            "and keep $1234567 or CAD 7654321. Please ask [NAME] about [NAME].",
            result,
        )
        self.assertIsNone(greeting)
        self.assertEqual(
            counts(
                lexicon_names=2, emails=1, urls=1, phones=1, numbers=1, residual_capitalised=["CAD"]
            ),
            actual,
        )

    def test_harvest_headers_and_t4_t5_before_strip(self):
        mail = EmailMessage()
        mail["From"] = "Owner <owner@example.com>"
        mail["To"] = "Bill Grace <bg@example.net>"
        mail["Cc"] = "Rowan <rowan@example.net>"
        mail["Reply-To"] = "Jane <jane@example.net>"
        mail.set_content(
            "Owner note.\nFrom: Zella <zella@example.net>\n"
            "To: Quorra <quorra@example.net>\nSubject: Reply\n\n"
            "On Tuesday afternoon, Vesper <vesper@example.net> wrote:\nquoted\n"
            "On Tuesday afternoon, Sybilla wrote:\nquoted"
        )
        names = scrub.harvest(mail, ["Owner"], DEFAULTS["ingest"])
        self.assertEqual(
            {"Bill", "Grace", "Rowan", "Jane", "Zella", "Quorra", "Vesper", "Sybilla"}, names
        )

    def test_limits_and_allowlist(self):
        text, _, actual = scrub.scrub(
            "Bill can ask Bill about bill. Zorvyn uses ToolName.", {"Bill"}, allowlist={"ToolName"}
        )
        self.assertEqual("Bill can ask [NAME] about bill. Zorvyn uses ToolName.", text)
        self.assertEqual(counts(lexicon_names=1, residual_capitalised=["Bill", "Zorvyn"]), actual)

    def test_lexicon_extension_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "terms.txt"
            path.write_text("private project\n")
            terms, provenance = scrub.sensitive_terms(str(path))
            self.assertTrue(scrub.sensitive("A diagnosis for a private project.", terms))
            self.assertEqual("builtin+file", provenance["source"])
            self.assertEqual(64, len(provenance["sha256"]))
            for payload in (None, b"\xff"):
                if payload is None:
                    path.unlink()
                else:
                    path.write_bytes(payload)
                with self.assertRaises(DiagnosticError) as error:
                    scrub.read_terms(path)
                self.assertIsNotNone(error.exception.__cause__)
                for part in ("read scrub lexicon", str(path), "expected", "next step:"):
                    self.assertIn(part, str(error.exception))


class ScrubIngestTests(unittest.TestCase):
    # Reuse only the C3 harness methods, not its test methods.
    setUp = test_ingest_cli.IngestCliTests.setUp
    configure = test_ingest_cli.IngestCliTests.configure
    source = test_ingest_cli.IngestCliTests.source
    cli = test_ingest_cli.IngestCliTests.cli
    read_outputs = test_ingest_cli.IngestCliTests.read_outputs

    def fixture_sources(self):
        folder = self.root / "emls"
        folder.mkdir()
        expected = []
        for case in cases():
            for index in range(case.get("repeat", 1)):
                (folder / f"{len(list(folder.iterdir())):03}.eml").write_bytes(raw(case, index))
                if not case.get("same_id") or index == 0:
                    expected.append(case)
        # Non-owner folder headers must contribute to the lexicon too.
        header = {"id": "inbox", "sender": "Rowan Bill <rowan@example.net>", "body": "unused"}
        (folder / "zzz.eml").write_bytes(raw(header))
        other = self.root / "second.mbox"
        with other.open("wb") as stream:
            for case in cases():
                if case.get("cross_duplicate"):
                    stream.write(b"From owner@example.com Tue Jan 20 01:30:00 2026\n")
                    stream.write(raw({**case, "body": "Second source should lose."}))
                    stream.write(b"\n")
        self.configure([self.source("first", "eml", folder), self.source("second", "mbox", other)])
        return expected

    def test_all_card_fixtures_exact_and_AC3_scan(self):
        expected = self.fixture_sources()
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, _rejected, report = self.read_outputs("first")
        self.assertEqual(len(expected), len(rows))
        self.assertEqual({"duplicate": 1, "not_owner": 1}, report["rejected_by_reason"])
        self.assertEqual(1, report["duplicates"])
        for case, row in zip(expected, rows):
            with self.subTest(fixture=case["id"]):
                self.assertEqual(case["text"], row["text"])
                self.assertEqual(case.get("greeting"), row["greeting"])
                self.assertEqual(case.get("signoff"), row["signoff"])
                self.assertEqual(
                    counts(**case.get("counts", {}), residual_capitalised=case.get("residual", [])),
                    row["scrub"],
                )
                self.assertEqual(case.get("template", False), row["template"])
                self.assertEqual(case.get("sensitive", False), row["sensitive"])
                for rule in case.get("rules", []):
                    self.assertIn(rule, row["strip"]["rules_fired"])
        merged = json.loads((self.work / "ingest-report.json").read_text())
        self.assertEqual(2, merged["cross_source_duplicates"])
        self.assertEqual(len(rows), merged["merged_records"])
        self.assertEqual(
            rows,
            [json.loads(line) for line in (self.work / "records.jsonl").read_text().splitlines()],
        )
        self.assertEqual(sum(r["template"] for r in rows), report["templates"])
        self.assertEqual(1, report["sensitive"])
        second, second_rejects, second_report = self.read_outputs("second")
        self.assertEqual([], second_rejects)
        self.assertEqual(2, second_report["records_written"])
        for row in second:
            self.assertEqual("Second source should lose.", row["text"])
            self.assertEqual(counts(), row["scrub"])
            self.assertIsNone(row["greeting"])
            self.assertIsNone(row["signoff"])
            self.assertFalse(row["template"])
        names_path = self.work / "names.txt"
        self.assertEqual(PRIVATE_LINE, names_path.read_text().splitlines()[0])
        self.assertEqual(0o600, names_path.stat().st_mode & 0o777)
        names = names_path.read_text().splitlines()[1:]
        self.assertEqual(["Bill", "Jane", "Roe", "Rowan"], names)
        self.scan(names)
        # Demonstrate the scanner rejects a correspondent name without a residual entry.
        with self.assertRaises(AssertionError):
            self.scan_record({"text": "Jane", "scrub": {"residual_capitalised": []}}, names)

    def scan_record(self, record, names):
        residual = record.get("scrub", {}).get("residual_capitalised", [])
        for name in names:
            if re.search(r"\b" + re.escape(name) + r"\b", json.dumps(record)):
                self.assertIn(name, residual)

    def scan(self, names):
        for path in self.work.rglob("*"):
            if not path.is_file() or path.name in (
                "names.txt",
                "domain-map.toml",
                "unmapped-domains.json",
            ):
                continue
            text = path.read_text()
            self.assertNotRegex(text, r"[\w.+-]+@[\w.-]+\.[a-zA-Z]+")
            for domain in (
                "example.com",
                "example.net",
                "third.example.net",
                "private.example.net",
            ):
                self.assertNotIn(domain, text)
            if path.name in ("records.jsonl", "rejects.jsonl"):
                for line in text.splitlines():
                    self.scan_record(json.loads(line), names)
            else:
                for name in names:
                    self.assertNotRegex(text, r"\b" + re.escape(name) + r"\b")

    def test_empty_lexicon_always_written_and_sensitive_opt_out(self):
        path = self.root / "single.eml"
        payload = raw({"id": "empty", "body": "Please review the diagnosis."})
        payload = payload.replace(b"Jane <jane@example.net>", b"recipient@example.net")
        payload = payload.replace(b"Roe <roe@example.net>", b"recipient@example.net")
        path.write_bytes(payload)
        for extra, expected in (("", True), ('\n[ingest]\nsensitive_terms="none"\n', False)):
            self.configure([self.source(kind="eml", path=path)], extra=extra)
            result = self.cli("--reparse", "synthetic")
            self.assertEqual(0, result.returncode, result.stderr)
            rows, _, report = self.read_outputs()
            self.assertEqual(expected, rows[0]["sensitive"])
            self.assertEqual(
                "builtin" if expected else "none", report["lexicons"]["sensitive"]["source"]
            )
            self.assertEqual(PRIVATE_LINE + "\n", (self.work / "names.txt").read_text())

    def test_name_collection_io_diagnostic(self):
        from ownvoice.ingest.run import collect_names

        error = PermissionError("synthetic read denied")
        with (
            patch("ownvoice.readers.eml.messages", side_effect=error),
            self.assertRaises(DiagnosticError) as caught,
        ):
            collect_names({}, [{"label": "first", "kind": "eml"}], {"first": []})
        self.assertIs(error, caught.exception.__cause__)
        self.assertEqual(3, caught.exception.exit_code)
        for part in ("collect correspondent names", "first", "synthetic read denied", "next step:"):
            self.assertIn(part, str(caught.exception))
