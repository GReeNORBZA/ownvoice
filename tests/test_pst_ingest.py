import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ownvoice.config import load_config
from ownvoice.errors import ValidationErrors
from ownvoice.ingest.preflight import preflight
from ownvoice.schemas import extract_stamp, ingest_report, records, unmapped_domains
from tests.test_ingest_cli import IngestCliTests, assert_signature_outputs, signature_cases
from tests.test_ingest_extract import raw_message


def export_mail(root, reader, folder, mail, *, item="Message00001", body=True):
    """Write synthetic reader output, without invoking an external PST binary."""
    if reader == "pffexport":
        path = root / "pst.export" / folder / item
        path.mkdir(parents=True, exist_ok=True)
        (path / "InternetHeaders.txt").write_text(
            "\n".join(f"{key}: {value}" for key, value in mail.items()) + "\n\n"
        )
        if body:
            suffix = "html" if mail.get_content_type() == "text/html" else "txt"
            (path / f"Message.{suffix}").write_text(mail.get_content())
    else:
        path = root / folder
        path.mkdir(parents=True, exist_ok=True)
        with (path / "mbox").open("ab") as stream:
            stream.write(b"From owner@example.com Tue Jan 20 12:00:00 2026\n")
            stream.write(mail.as_bytes() + b"\n")


@pytest.fixture
def folder_ingest(tmp_path, monkeypatch, request, rejected_body):
    """Three synthetic selected folders, all below the checkpoint interval."""
    from ownvoice.ingest import checkpoint, pst, run

    reader = request.param
    helper = IngestCliTests()
    helper.setUp()
    request.addfinalizer(helper.doCleanups)
    source_path = helper.root / "mail.pst"
    source_path.write_bytes(b"!BDNsynthetic")
    helper.configure(
        [helper.source(kind="pst", path=source_path, reader=reader)],
        extra="\n[ingest]\ncheckpoint_every = 100\n",
    )
    config, domain_map = load_config(helper.config)
    root = tmp_path / "export"
    expected = []
    for folder, identifiers in (
        ("Sent Items", ["one", None]),
        ("Sent Items/Nested", ["two", "one", None]),
        ("Sent Items/Z-last", [None]),
    ):
        for index, identifier in enumerate(identifiers):
            mail = EmailMessage()
            mail["From"] = "Owner <owner@example.com>"
            mail["Message-ID"] = f"<{identifier or folder}@example.com>"
            mail.set_content("please review the proposed plan." if identifier else rejected_body)
            export_mail(root, reader, folder, mail, item=f"Message{index:05}")
        relative = Path("pst.export") / folder if reader == "pffexport" else Path(folder)
        expected.append(
            {
                "name": "folder-" + hashlib.sha256(str(relative).encode()).hexdigest()[:16],
                "messages_seen": len(identifiers),
                "records": 0 if folder.endswith("Z-last") else 1,
                "rejects": len(identifiers) - (0 if folder.endswith("Z-last") else 1),
                "error": None,
            }
        )
    monkeypatch.setenv("PATH", str(Path("tests/shims").resolve()) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(
        pst,
        "prepare",
        lambda source, *args: pst.Reader(source, root, {"elapsed_s": 0.0, "dump_bytes": 0}),
    )
    args = SimpleNamespace(
        source=None,
        label=None,
        owner=None,
        only=None,
        restart=None,
        reparse=None,
        quiet=False,
        verbose=False,
        keep_extracted=True,
        logger=SimpleNamespace(event=lambda **kw: None),
    )
    return SimpleNamespace(
        execute=lambda: run.run(config, domain_map, args),
        helper=helper,
        expected=expected,
        args=args,
        checkpoint=checkpoint,
        path=helper.work / "sources/synthetic/checkpoint.json",
        root=root,
        reader=reader,
    )


@pytest.fixture(params=["", "--\nOwner\nEngineer"])
def rejected_body(request):
    return request.param


@pytest.mark.parametrize("folder_ingest", ["pffexport", "readpst"], indirect=True)
@pytest.mark.parametrize("only_empty", [False, True])
def test_signature_final_text_pst_accounting(folder_ingest, only_empty):
    from ownvoice.readers.eml import parse

    case = folder_ingest
    shutil.rmtree(case.root)
    selected = [signature_cases()[10]] if only_empty else signature_cases()
    for i, message in enumerate(selected):
        _, mail = parse(raw_message(message), f"synthetic/{i}")
        export_mail(case.root, case.reader, "Sent Items", mail, item=f"Message{i:05}")
    if only_empty:
        with pytest.raises(ValidationErrors) as caught:
            case.execute()
        for part in ("ingest", "synthetic", "no owner-sent messages", "expected", "next step:"):
            assert part in str(caught.value)
    else:
        assert case.execute() == 0
    rows, rejects, report = case.helper.read_outputs()
    if only_empty:
        assert rows == []
        assert [r["reason"] for r in rejects] == ["empty_after_strip"]
        assert (report["status"], report["selected"]) == ("failed", 1)
    else:
        assert_signature_outputs(rows, rejects, report)
    folder = report["folders"][0]
    assert len(report["folders"]) == 1
    assert (folder["messages_seen"], folder["records"], folder["rejects"]) == (
        len(selected),
        len(rows),
        len(rejects),
    )
    state = json.loads(case.path.read_text())
    assert (state["message_index"], state["records"], state["rejects"]) == (
        len(selected),
        len(rows),
        len(rejects),
    )
    assert state["state"]["complete"] is not only_empty


@pytest.mark.parametrize("folder_ingest", ["pffexport", "readpst"], indirect=True)
def test_br008_folder_reports_checkpoints_progress(folder_ingest, monkeypatch, capsys):
    case = folder_ingest
    saved = []
    original = case.checkpoint.Journal.save

    def save(journal, *args, **kwargs):
        original(journal, *args, **kwargs)
        value = json.loads(case.path.read_text())
        saved.append(value)
        assert len(case.checkpoint.rows(journal.outputs["records"])) == value["records"]
        assert len(case.checkpoint.rows(journal.outputs["rejects"])) == value["rejects"]

    monkeypatch.setattr(case.checkpoint.Journal, "save", save)
    assert case.execute() == 0
    rows, rejects, report = case.helper.read_outputs()
    assert report["folders"] == case.expected
    assert (len(rows), len(rejects), report["messages_seen"]) == (2, 4, 6)
    for folder, end, records_count in zip(case.expected, [2, 5, 6], [1, 2, 2]):
        assert any(
            (s["folder"], s["message_index"], s["records"], s["rejects"])
            == (folder["name"], end, records_count, end - records_count)
            for s in saved
        )
    progress = capsys.readouterr().err
    for folder in case.expected:
        assert progress.count(f"folder {folder['name']}:") == 1
    assert "Sent Items" not in progress


@pytest.mark.parametrize("folder_ingest", ["pffexport", "readpst"], indirect=True)
@pytest.mark.parametrize("boundary", [2, 5, 6])
def test_br008_resume_at_folder_boundary(folder_ingest, monkeypatch, capsys, boundary):
    case = folder_ingest
    original = case.checkpoint.Journal.save

    def interrupt(journal, *args, **kwargs):
        original(journal, *args, **kwargs)
        state = json.loads(case.path.read_text())
        if state["message_index"] == boundary:
            raise KeyboardInterrupt

    monkeypatch.setattr(case.checkpoint.Journal, "save", interrupt)
    with pytest.raises(KeyboardInterrupt):
        case.execute()
    state = json.loads(case.path.read_text())
    assert state["message_index"] == boundary
    assert state["folder"] == case.expected[[2, 5, 6].index(boundary)]["name"]
    capsys.readouterr()
    monkeypatch.setattr(case.checkpoint.Journal, "save", original)
    assert case.execute() == 0
    resumed = case.helper.read_outputs()
    assert resumed[2]["folders"] == case.expected
    progress = capsys.readouterr().err
    for folder, end in zip(case.expected, [2, 5, 6]):
        assert progress.count(f"folder {folder['name']}:") == int(end > boundary)
    case.args.restart = "synthetic"
    assert case.execute() == 0
    fresh = case.helper.read_outputs()
    assert resumed[:2] == fresh[:2]
    assert resumed[2]["folders"] == fresh[2]["folders"]
    assert len({r["record_id"] for r in resumed[0]}) == len(resumed[0]) == 2


@pytest.mark.parametrize("reader", ["pffexport", "readpst"])
@pytest.mark.parametrize("folder", ["Sent Items", "Inbox"])
@pytest.mark.parametrize("subtype", ["plain", "html"])
@pytest.mark.parametrize("block", ["attribution", "forwarded"])
def test_br002_body_names_before_strip(tmp_path, reader, folder, subtype, block):
    from ownvoice.extract import scrub
    from ownvoice.extract.body import extract
    from ownvoice.ingest.pst import Reader

    config = {"extra_attribution_patterns": [], "mobile_footers": []}
    owner = EmailMessage()
    owner["From"] = "Owner <owner@example.com>"
    owner.set_content("please ask Will and Zorvyn to review this with Owner.")
    export_mail(tmp_path, reader, "Sent Items", owner)
    quote = (
        "On Tuesday, Will Zorvyn wrote:\n> quoted text"
        if block == "attribution"
        else "From: Will Zorvyn\nTo: Owner\nSubject: review\n> quoted text"
    )
    evidence = EmailMessage()
    evidence["From"] = "Owner <owner@example.com>"
    body = "please review the plan.\n\n" + quote
    if subtype == "html":
        body = "<div>" + body.replace("\n", "<br>") + "</div>"
    evidence.set_content(body, subtype=subtype)
    export_mail(tmp_path, reader, folder, evidence, item="Message00002")
    adapter = Reader(
        {"label": "synthetic", "reader": reader, "sent_folders": ["Sent Items"]},
        tmp_path,
        {},
    )
    names = adapter.harvest({"owner": {"names": ["Owner"]}, "ingest": config})
    assert {"Will", "Zorvyn"} <= names
    assert "Owner" not in names
    assert "will" in scrub.shipped("wordlist")
    _, (_, mail) = next(adapter.messages())
    text, stripped = extract(mail, config)
    masked, _, counts = scrub.scrub(text, names, ["Owner"])
    assert masked == "please ask [NAME] and [NAME] to review this with Owner."
    assert stripped["confidence"] == "high"
    assert counts["lexicon_names"] == 2
    assert counts["residual_capitalised"] == []


@pytest.mark.parametrize("reader", ["pffexport", "readpst"])
def test_br002_header_only_reply_to_and_non_mail(tmp_path, reader):
    from ownvoice.extract.body import Rejected, extract
    from ownvoice.ingest.pst import Reader

    mail = EmailMessage()
    mail["From"] = "Owner <owner@example.com>"
    mail["Reply-To"] = "Veltrix <reply@example.com>"
    export_mail(tmp_path, reader, "Sent Items", mail, body=False)
    calendar = EmailMessage()
    calendar["From"] = "Zorvyn <calendar@example.com>"
    calendar.set_content("calendar data", subtype="calendar")
    export_mail(tmp_path, reader, "Sent Items", calendar, item="Appointment00002")
    adapter = Reader(
        {"label": "synthetic", "reader": reader, "sent_folders": ["Sent Items"]},
        tmp_path,
        {},
    )
    config = {"extra_attribution_patterns": [], "mobile_footers": []}
    names = adapter.harvest({"owner": {"names": ["Owner"]}, "ingest": config})
    assert {"Veltrix", "Zorvyn"} <= names
    assert "Owner" not in names
    reasons = []
    for _, value in adapter.messages():
        if isinstance(value, Rejected):
            reasons.append(value.reason)
        else:
            with pytest.raises(Rejected) as caught:
                extract(value[1], config)
            reasons.append(caught.value.reason)
    assert sorted(reasons) == sorted(
        ["non_mail_item", "no_text_body" if reader == "pffexport" else "empty_after_strip"]
    )


class PstTests(unittest.TestCase):
    setUp = IngestCliTests.setUp
    configure = IngestCliTests.configure
    source = IngestCliTests.source

    def setup_pst(self, reader="pffexport", **options):
        path = self.root / "mail.pst"
        path.write_bytes(b"!BDNsynthetic")
        self.configure([self.source(kind="pst", path=path, reader=reader, **options)])
        (self.root / "domain-map.toml").write_text(
            'schema_version = 1\n[domains]\n"example.com" = "client"\n'
            '[x500]\n"ExampleCorp" = "colleague"\n[names]\n'
            '"Known Person" = "personal"\n"Jane Doe" = "professional-warm"\n'
        )

    def cli(self, command="ingest", *args, env=None):
        environment = {
            **os.environ,
            "PATH": str(Path("tests/shims").resolve()) + os.pathsep + os.environ["PATH"],
        }
        environment.update(env or {})
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                str(self.config),
                "--verbose",
                command,
                *args,
            ],
            check=False,
            env=environment,
            capture_output=True,
            text=True,
        )

    def outputs(self):
        root = self.work / "sources/synthetic"
        rows = [json.loads(line) for line in (root / "records.jsonl").read_text().splitlines()]
        rejects = [json.loads(line) for line in (root / "rejects.jsonl").read_text().splitlines()]
        report = json.loads((root / "ingest-report.json").read_text())
        ingest_report.validate(report)
        for row in rows:
            records.validate(row)
        self.assertEqual(len(rows) + len(rejects), report["messages_seen"])
        resolution = report["recipient_resolution"]
        self.assertEqual(
            resolution["recipients"],
            sum(resolution[k] for k in ("smtp", "x500", "names", "unknown")),
        )
        return rows, rejects, report

    def test_F47_F50_wiring_privacy_and_cleanup(self):
        self.setup_pst()
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, rejects, report = self.outputs()
        self.assertEqual(2, len(rows))
        self.assertEqual(["non_mail_item"], [r["reason"] for r in rejects])
        self.assertEqual(["plain", "html"], [r["strip"]["body_source"] for r in rows])
        self.assertEqual(2026, rows[0]["year"])
        self.assertEqual("reply", rows[1]["thread_position"])
        self.assertEqual("pffexport", report["reader"])
        self.assertEqual("20180714", report["reader_version"])
        self.assertEqual(
            {"smtp": 1, "x500": 1, "names": 2, "unknown": 3, "recipients": 7},
            report["recipient_resolution"],
        )
        self.assertEqual(1, report["skipped_folders"])
        self.assertFalse((self.work / "sources/synthetic/extract").exists())
        self.assertIn("later --reparse needs --restart", result.stderr)
        summary = json.loads((self.work / "unmapped-domains.json").read_text())
        unmapped_domains.validate(summary)
        self.assertEqual([{"org": "unknowncorp", "messages": 1}], summary["x500_orgs"])
        self.assertEqual(1, summary["unresolved_names"])
        self.assertIn("unmapped X.500 org unknowncorp: 1", result.stderr)
        for path in self.work.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text()
            for secret in (
                "SecretUnit",
                "SecretPerson",
                "HiddenUnit",
                "HiddenPerson",
                "PrivateFolder",
                "Sent Items",
            ):
                self.assertNotIn(secret, text, path)
            if path.name not in ("names.txt", "unmapped-domains.json"):
                for secret in (
                    "Jane",
                    "John",
                    "Known Person",
                    "unknowncorp",
                    "unmapped.example",
                    "jane@example.com",
                ):
                    self.assertNotIn(secret, text, path)
        names = (self.work / "names.txt").read_text()
        self.assertIn("Hidden", names)
        for secret in (
            "SecretUnit",
            "SecretPerson",
            "HiddenUnit",
            "HiddenPerson",
            "PrivateFolder",
            "Sent Items",
        ):
            self.assertNotIn(secret, result.stderr)

    def test_F26_F36_readpst_folder_only_and_names(self):
        self.setup_pst("readpst")
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        rows, rejects, report = self.outputs()
        self.assertEqual(2, len(rows))
        self.assertEqual([], rejects)
        self.assertEqual(
            {"smtp": 0, "x500": 0, "names": 2, "unknown": 2, "recipients": 4},
            report["recipient_resolution"],
        )
        self.assertEqual(1, report["skipped_messages"])
        self.assertTrue(all(r["recipient_class"] == "professional-warm" for r in rows))

    def test_F26_F47_keep_resume_reparse_restart_clean(self):
        for reader in ("pffexport", "readpst"):
            with self.subTest(reader=reader):
                self.setup_pst(reader)
                result = self.cli("ingest", "--restart", "synthetic", "--keep-extracted")
                self.assertEqual(0, result.returncode, result.stderr)
                root = self.work / "sources/synthetic/extract"
                stamp = root / ".done"
                extract_stamp.validate(json.loads(stamp.read_text()))
                before = stamp.stat().st_mtime_ns
                # Reparse must reuse the stamp even when invoking the binary would fail.
                result = self.cli(
                    "ingest", "--reparse", "synthetic", "--keep-extracted", env={"PST_FAIL": "1"}
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(before, stamp.stat().st_mtime_ns)
                self.assertIn("retained export [synthetic]", result.stderr)
                self.assertIn("bytes, age", result.stderr)
                # Completed source skips extraction entirely.
                result = self.cli(env={"PST_FAIL": "1"})
                self.assertEqual(0, result.returncode, result.stderr)
                result = self.cli("clean", "--extracted", "all")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(str(root), result.stdout)
                self.assertIn("bytes", result.stdout)
                self.assertFalse(root.exists())
                result = self.cli("ingest", "--reparse", "synthetic")
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("--restart synthetic re-exports", result.stderr)
                result = self.cli("ingest", "--restart", "synthetic", "--keep-extracted")
                self.assertEqual(0, result.returncode, result.stderr)
                result = self.cli("clean", "--all")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertFalse(root.exists())
        result = self.cli("clean", "--extracted", "absent")
        self.assertEqual(2, result.returncode)
        for part in (
            "clean extracted PST",
            "absent",
            "unknown source label",
            "expected",
            "next step",
        ):
            self.assertIn(part, result.stderr)

    def test_F28_partial_and_item_reject(self):
        for reader in ("pffexport", "readpst"):
            with self.subTest(reader=reader):
                self.setup_pst(reader)
                result = self.cli(
                    "ingest",
                    "--restart",
                    "synthetic",
                    env={"PST_FOLDER_ERROR": "1", "PST_ITEM_ERROR": "1"},
                )
                self.assertEqual(3, result.returncode, result.stderr)
                rows, rejects, report = self.outputs()
                self.assertEqual(2, len(rows))
                self.assertEqual("partial", report["status"])
                self.assertEqual(1, sum(f["error"] is not None for f in report["folders"]))
                self.assertNotIn("Unreadable", json.dumps(report))
                self.assertIn("unreadable selected folders", result.stderr)
                if reader == "pffexport":
                    self.assertIn("parse_error", [r["reason"] for r in rejects])

    def test_missing_binary_no_match_and_binary_failure(self):
        for reader, package in (("pffexport", "pff-tools"), ("readpst", "pst-utils")):
            with self.subTest(reader=reader):
                self.setup_pst(reader)
                result = self.cli(env={"PATH": ""})
                self.assertEqual(3, result.returncode, result.stderr)
                for part in (
                    reader + " not found on PATH",
                    f'reader = "{reader}"',
                    "mail.pst",
                    "apt install " + package,
                    "expected",
                    "next step",
                ):
                    self.assertIn(part, result.stderr)
                result = self.cli("ingest", "--restart", "synthetic", env={"PST_FAIL": "1"})
                self.assertEqual(3, result.returncode, result.stderr)
                for part in (
                    reader,
                    "exited 1",
                    "Error opening File",
                    "expected exit 0",
                    "OST renamed",
                    "--verbose",
                ):
                    self.assertIn(part, result.stderr)
                self.assertFalse((self.work / "sources/synthetic/extract/.done").exists())
                self.setup_pst(reader, sent_folders=["NoMatch"])
                result = self.cli("ingest", "--restart", "synthetic")
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("no folder matched sent_folders", result.stderr)
                self.assertIn("PrivateFolder", result.stderr)
                self.assertNotIn("PrivateFolder", result.stdout)
                for path in self.work.rglob("*.json"):
                    if "extract" not in path.parts:
                        self.assertNotIn("PrivateFolder", path.read_text())

    def test_F27_source_and_reader_problems_are_independent(self):
        for reader in ("pffexport", "readpst"):
            for defect in ("empty", "magic", "missing", "unreadable"):
                with self.subTest(reader=reader, defect=defect):
                    self.setup_pst(reader)
                    path = self.root / "mail.pst"
                    expected = {
                        "empty": "source is 0 bytes",
                        "magic": "content does not match kind",
                        "missing": "No such file or directory",
                        "unreadable": "source is unreadable",
                    }[defect]
                    if defect == "empty":
                        path.write_bytes(b"")
                    elif defect == "magic":
                        path.write_bytes(b"wrong magic")
                    elif defect == "missing":
                        path.unlink()
                    else:
                        path.chmod(0)
                    try:
                        result = self.cli(env={"PATH": ""})
                        self.assertEqual(2, result.returncode, result.stderr)
                        for part in (expected, reader + " not found on PATH", str(path)):
                            self.assertIn(part, result.stderr)
                        for line in result.stderr.splitlines():
                            self.assertIn("ingest", line)
                            self.assertIn("synthetic", line)
                            self.assertIn("expected", line)
                            self.assertIn("next step:", line)
                        self.assertFalse(self.work.exists())
                    finally:
                        if path.exists():
                            path.chmod(0o600)

    def test_disk_preflight_aggregate(self):
        self.setup_pst()
        config, _ = load_config(self.config)
        with (
            patch(
                "ownvoice.ingest.preflight.shutil.disk_usage",
                return_value=shutil._ntuple_diskusage(10, 10, 0),
            ),
            self.assertRaises(ValidationErrors) as caught,
        ):
            preflight(config, config["source"])
        for part in ("preflight ingest", str(self.work), "0 bytes free", "1.5 times", "next step"):
            self.assertIn(part, str(caught.exception))


class RealPstTests(unittest.TestCase):
    def real(self, reader, fixture, package):
        source = os.environ.get("OWNVOICE_TEST_PST")
        if not shutil.which(reader) or not source:
            reason = f"SKIP {fixture}: {reader} not on PATH (install {package}); PST path covered only by shim test"
            print(reason, file=sys.stderr)
            self.skipTest(reason)
        with tempfile.TemporaryDirectory(prefix="ownvoice-pst-real-") as directory:
            root = Path(directory)
            if reader == "pffexport":
                argv = [reader, "-m", "items", "-f", "text", "-q", "-t", str(root / "pst"), source]
            else:
                argv = [
                    reader,
                    "-r",
                    "-8",
                    "-b",
                    "-q",
                    "-j",
                    "0",
                    "-t",
                    "e",
                    "-o",
                    str(root),
                    source,
                ]
            result = subprocess.run(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
            )
            self.assertEqual(0, result.returncode, f"{fixture}: reader exit {result.returncode}")
            self.assertTrue(any(root.rglob("Recipients.txt" if reader == "pffexport" else "mbox")))

    def test_F26_real(self):
        self.real("readpst", "F26-real", "pst-utils")

    def test_F47_real(self):
        self.real("pffexport", "F47-real", "pff-tools")
