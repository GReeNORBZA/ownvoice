"""C5 acceptance: real process death and durable per-source replay boundaries."""

import ast
import copy
import json
import os
import select
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ownvoice.errors import DiagnosticError
from ownvoice.ingest import checkpoint
from ownvoice.ingest.run import fingerprint
from ownvoice.schemas import checkpoint as schema
from tests import test_ingest_cli as helpers


class ResumeTests(unittest.TestCase):
    setUp = helpers.IngestCliTests.setUp
    configure = helpers.IngestCliTests.configure
    source = helpers.IngestCliTests.source
    mbox = helpers.IngestCliTests.mbox
    cli = helpers.IngestCliTests.cli
    read_outputs = helpers.IngestCliTests.read_outputs

    def test_signature_rejections_resume_with_conserved_prefix(self):
        from ownvoice.cli import main

        self.mbox(helpers.signature_cases())
        self.configure([self.source()], extra="\n[ingest]\ncheckpoint_every = 4\n")
        folder = self.work / "sources/synthetic"
        original = checkpoint.Journal.save

        def interrupt(journal, *args, **kwargs):
            original(journal, *args, **kwargs)
            state = json.loads((folder / "checkpoint.json").read_text())
            if state["message_index"] == 12:
                raise KeyboardInterrupt

        with (
            patch.object(checkpoint.Journal, "save", interrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            main(["--config", str(self.config), "--quiet", "ingest"])
        state = json.loads((folder / "checkpoint.json").read_text())
        self.assertEqual((12, 10, 2), (state["message_index"], state["records"], state["rejects"]))
        self.success()
        resumed = self.read_outputs()
        helpers.assert_signature_outputs(*resumed)
        self.success("--restart", "synthetic")
        fresh = self.read_outputs()
        self.assertEqual(resumed[:2], fresh[:2])
        self.assertEqual(resumed[2]["folders"], fresh[2]["folders"])

    def test_scrub_policy_changes_refuse_complete_and_incomplete_reuse(self):
        for field in ("deny_terms_file", "sensitive_terms"):
            for complete in (True, False):
                with self.subTest(field=field, complete=complete):
                    self.work = self.root / f"work-{field}-{complete}"
                    terms = self.root / f"{field}.txt"
                    terms.write_text("unmatchedword\n")
                    case = copy.deepcopy(self.fixture_cases["F01"])
                    case["body"] = "The cat sat on the mat."
                    self.mbox([case])
                    self.configure(
                        [self.source(llm_eligible=True)],
                        extra=f'\n[ingest]\n{field} = "{terms}"\n[llm]\nprovider="synthetic"\nretention_terms="synthetic"\ntraining_use="none"\nattestation="2026-09-27 synthetic"\n',
                    )
                    self.success()
                    folder = self.work / "sources/synthetic"
                    state_path = folder / "checkpoint.json"
                    if not complete:
                        state = json.loads(state_path.read_text())
                        state["state"]["complete"] = False
                        state_path.write_text(json.dumps(state))
                    before = self.snapshot()
                    terms.write_text("cat\n")
                    result = self.cli()
                    self.assertEqual(2, result.returncode, result.stderr)
                    for part in (
                        "validate scrub policy",
                        "synthetic",
                        "expected",
                        "ownvoice ingest --reparse synthetic",
                    ):
                        self.assertIn(part, result.stderr)
                    self.assertEqual(before, self.snapshot())
                    self.success("--reparse", "synthetic")
                    rows, _, report = self.read_outputs()
                    if field == "deny_terms_file":
                        self.assertNotIn("cat", rows[0]["text"])
                    else:
                        self.assertTrue(rows[0]["sensitive"])
                    self.assertEqual(
                        report["scrub_digests"], json.loads(state_path.read_text())["scrub_digests"]
                    )
                    manifest = self.work / "qual/manifest.json"
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "ownvoice",
                            "--config",
                            str(self.config),
                            "qual",
                            "chunk",
                            "--records",
                            str(folder / "records.jsonl"),
                            "--pass",
                            "A",
                            "--out",
                            str(manifest),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    chunks = json.loads(manifest.read_text())["chunks"]
                    if field == "sensitive_terms":
                        self.assertEqual([], chunks)
                    else:
                        self.assertTrue(chunks)
                    for row in chunks:
                        self.assertNotIn("cat", Path(row["text_path"]).read_text())

    def prepare(self, count=40):
        cases = []
        for i in range(count):
            case = copy.deepcopy(self.fixture_cases["F01" if i % 7 else "F42-Spam"])
            case["id"] = f"resume-{i}"
            cases.append(case)
        cases.append(copy.deepcopy(cases[1]))  # dedup must remember the committed prefix
        self.mbox(cases)
        self.configure([self.source()], extra="\n[ingest]\ncheckpoint_every = 10\n")
        return self.work / "sources" / "synthetic"

    def success(self, *args):
        result = self.cli(*args)
        self.assertEqual(0, result.returncode, result.stderr)

    def snapshot(self):
        return {
            str(p.relative_to(self.work)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in self.work.rglob("*")
            if p.is_file()
        }

    def test_F29_sigkill_then_new_process_truncates_uncommitted_tail(self):
        folder = self.prepare()
        script = """
import signal
import sys
from ownvoice.cli import main
from ownvoice.ingest.checkpoint import Journal
original = Journal.append
def append(self, kind, value):
    original(self, kind, value)
    if self.outputs['checkpoint'].exists():
        print('uncommitted-row-written', flush=True)
        signal.pause()
Journal.append = append
sys.exit(main(sys.argv[1:]))
"""
        process = subprocess.Popen(
            [sys.executable, "-c", script, "--config", str(self.config), "--quiet", "ingest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 30)
            self.assertTrue(ready, "subprocess did not reach its first durable checkpoint")
            self.assertEqual("uncommitted-row-written", process.stdout.readline().strip())
            state = json.loads((folder / "checkpoint.json").read_text())
            schema.validate(state)
            self.assertEqual(10, state["message_index"])
            count = sum(
                len((folder / name).read_text().splitlines())
                for name in ("records.jsonl", "rejects.jsonl")
            )
            self.assertEqual(11, count)
            process.kill()
            process.communicate(timeout=10)
            self.assertEqual(-signal.SIGKILL, process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        with (folder / "records.jsonl").open("ab") as out:
            out.write(b'{"torn":')
        self.success()
        resumed = self.read_outputs()
        merged = (self.work / "records.jsonl").read_bytes()
        self.success("--restart", "synthetic")
        uninterrupted = self.read_outputs()
        self.assertEqual(resumed[:2], uninterrupted[:2])
        self.assertEqual(merged, (self.work / "records.jsonl").read_bytes())
        ids = [row["record_id"] for row in resumed[0]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(41, resumed[2]["messages_seen"])
        self.assertEqual(1, resumed[2]["duplicates"])

    def test_F48_domain_map_reparse_and_unchanged_noop(self):
        self.prepare()
        self.success()
        before = self.read_outputs()
        snapshot = self.snapshot()
        self.success()
        self.assertEqual(snapshot, self.snapshot())
        (self.root / "domain-map.toml").write_text(
            'schema_version = 1\n[domains]\n"example.net" = "client"\n'
        )
        self.success()
        self.assertEqual(snapshot, self.snapshot(), "map edits require explicit reparse")
        self.success("--reparse", "synthetic")
        after = self.read_outputs()
        self.assertEqual({"client"}, {r["recipient_class"] for r in after[0]})
        self.assertEqual([len(x) for x in before[:2]], [len(x) for x in after[:2]])
        self.assertEqual(before[2]["messages_seen"], after[2]["messages_seen"])
        merged = [
            json.loads(line) for line in (self.work / "records.jsonl").read_text().splitlines()
        ]
        self.assertEqual({"client"}, {r["recipient_class"] for r in merged})

    def test_fingerprint_hard_metadata_and_best_effort_edges(self):
        folder = self.prepare()
        self.success()
        source = self.root / "mail.mbox"
        original = source.stat()
        before = (folder / "checkpoint.json").read_bytes()
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns + 1000000))
        self.success()
        self.assertNotEqual(before, (folder / "checkpoint.json").read_bytes())
        previous = fingerprint([source])
        data = source.read_bytes().replace(b"New topic", b"New Topic")
        source.write_bytes(data)
        os.utime(source, ns=(original.st_atime_ns, previous["mtime_ns"]))
        current = fingerprint([source])
        self.assertEqual(previous["size"], current["size"])
        self.assertEqual(previous["mtime_ns"], current["mtime_ns"])
        self.assertNotEqual(previous["first_sha256"], current["first_sha256"])
        before = (folder / "checkpoint.json").read_bytes()
        self.success()
        self.assertNotEqual(before, (folder / "checkpoint.json").read_bytes())
        with patch("pathlib.Path.open", side_effect=PermissionError("edge unavailable")):
            self.assertIsNone(fingerprint([source])["first_sha256"])

    def test_unknown_reset_labels_and_unselected_target(self):
        self.prepare()
        for flag in ("--restart", "--reparse"):
            result = self.cli(flag, "absent")
            self.assertEqual(2, result.returncode)
            for part in ("preflight ingest", flag, "absent", "unknown", "expected", "next step:"):
                self.assertIn(part, result.stderr)
        self.assertFalse(self.work.exists())

    def test_merge_recovers_after_source_completion(self):
        self.prepare()
        self.success()
        expected = (self.work / "records.jsonl").read_bytes()
        (self.work / "merge-state.json").unlink()
        (self.work / "records.jsonl").write_text("interrupted merge")
        self.success()
        self.assertEqual(expected, (self.work / "records.jsonl").read_bytes())

    def prepare_merge_sources(self):
        from tests.test_ingest_extract import raw_message

        sources = []
        for label in ("one", "two"):
            directory = self.root / label
            directory.mkdir()
            for identifier in ("shared", label):
                case = copy.deepcopy(self.fixture_cases["F01"])
                case["id"] = identifier
                (directory / f"{identifier}.eml").write_bytes(
                    raw_message(case).replace(
                        b"other@example.net", f"other@{label}.example".encode()
                    )
                )
            sources.append(self.source(label, "eml", directory))
        self.configure(sources)
        return sources

    def merge_snapshot(self):
        return {
            name: (self.work / name).read_bytes()
            for name in (
                "records.jsonl",
                "ingest-report.json",
                "merge-state.json",
                "unmapped-domains.json",
            )
        }

    def test_only_preserves_completed_merge_and_fingerprints(self):
        self.prepare_merge_sources()
        self.success()
        expected = self.merge_snapshot()
        per_source = (self.work / "sources/two/records.jsonl").read_bytes()
        # Unselected inputs need not remain available to merge committed outputs.
        (self.root / "two").rename(self.root / "offline-two")
        self.success("--only", "one")
        self.assertEqual(expected, self.merge_snapshot())
        self.assertEqual(per_source, (self.work / "sources/two/records.jsonl").read_bytes())
        (self.work / "merge-state.json").unlink()
        self.success("--only", "one")
        rebuilt = self.merge_snapshot()
        self.assertEqual(expected["records.jsonl"], rebuilt["records.jsonl"])
        for name in ("ingest-report.json", "merge-state.json", "unmapped-domains.json"):
            before, after = json.loads(expected[name]), json.loads(rebuilt[name])
            before.pop("generated_at")
            after.pop("generated_at")
            self.assertEqual(before, after)

    def test_separate_only_runs_merge_in_configured_priority(self):
        from ownvoice.provenance import file_sha256

        sources = self.prepare_merge_sources()
        self.success("--only", "two")
        self.success("--only", "one")
        separate = self.merge_snapshot()
        rows = [json.loads(line) for line in separate["records.jsonl"].splitlines()]
        self.assertEqual(["one", "one", "two"], [row["source"] for row in rows])
        report = json.loads(separate["ingest-report.json"])
        self.assertEqual({"one": 2, "two": 2}, report["sources"])
        self.assertEqual(1, report["cross_source_duplicates"])
        self.assertEqual(3, report["merged_records"])
        for label in ("one", "two"):
            self.assertEqual(2, len(self.read_outputs(label)[0]))
        self.assertEqual(
            [{"domain": "one.example", "messages": 2}, {"domain": "two.example", "messages": 2}],
            json.loads(separate["unmapped-domains.json"])["domains"],
        )
        self.assertEqual(
            {
                label: file_sha256(self.work / "sources" / label / "ingest-report.json")
                for label in ("one", "two")
            },
            json.loads(separate["merge-state.json"])["sources"],
        )
        self.work = self.root / "full-work"
        self.configure(sources)
        self.success()
        self.assertEqual(separate["records.jsonl"], self.merge_snapshot()["records.jsonl"])

    def test_only_reports_and_excludes_uncompleted_sources(self):
        self.prepare_merge_sources()
        result = self.cli("--only", "one")
        self.assertEqual(0, result.returncode, result.stderr)
        for part in ("merge ingest source", "two", "excluded", "expected", "next step:"):
            self.assertIn(part, result.stderr)
        self.success("--only", "two")
        folder = self.work / "sources/two"
        state = json.loads((folder / "checkpoint.json").read_text())
        state["state"]["complete"] = False
        (folder / "checkpoint.json").write_text(json.dumps(state))
        result = self.cli("--only", "one")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("excluded", result.stderr)
        for name in ("ingest-report.json", "merge-state.json"):
            self.assertEqual({"one"}, set(json.loads((self.work / name).read_text())["sources"]))
        self.assertEqual(2, len(self.read_outputs("two")[0]))

    def test_restart_discards_corrupt_state_and_size_change_invalidates(self):
        folder = self.prepare()
        self.success()
        expected = (self.work / "records.jsonl").read_bytes()
        (folder / "checkpoint.json").write_text("broken checkpoint")
        self.success("--restart", "synthetic")
        self.assertEqual(expected, (self.work / "records.jsonl").read_bytes())
        source = self.root / "mail.mbox"
        before = source.stat()
        with source.open("ab") as stream:
            stream.write(b"\n")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.success()
        state = json.loads((folder / "checkpoint.json").read_text())
        self.assertEqual(before.st_size + 1, state["state"]["fingerprint"]["size"])

    def test_checkpoint_diagnostics_preserve_causes(self):
        folder = self.prepare()
        self.success()
        outputs = {
            k: folder / v
            for k, v in {
                "records": "records.jsonl",
                "rejects": "rejects.jsonl",
                "checkpoint": "checkpoint.json",
                "report": "ingest-report.json",
            }.items()
        }
        for action, operation, identity in (
            (lambda: checkpoint.read(folder / "missing.json"), "read ingest state", "missing.json"),
            (
                lambda: checkpoint.rows(outputs["records"], 999),
                "read ingest prefix",
                "records.jsonl",
            ),
        ):
            with self.assertRaises(DiagnosticError) as caught:
                action()
            for part in (operation, identity, "expected", "next step:"):
                self.assertIn(part, str(caught.exception))
            self.assertIsNotNone(caught.exception.__cause__)
        state = json.loads(outputs["checkpoint"].read_text())
        journal = checkpoint.Journal(
            outputs, state, state["state"]["fingerprint"], state["state"]["files"], state
        )
        # Journal takes provenance only, as the production caller supplies it.
        journal.provenance = {k: state[k] for k in schema.c.PROVENANCE}
        error = PermissionError("synthetic write denial")
        for target, action, operation in (
            ("pathlib.Path.open", lambda: journal.append("records", {}), "write private artefact"),
            ("os.fsync", lambda: journal.save(0, 0, {}, {}, set()), "flush ingest prefix"),
            ("pathlib.Path.unlink", lambda: checkpoint.reset(outputs), "reset ingest source"),
        ):
            with patch(target, side_effect=error), self.assertRaises(DiagnosticError) as caught:
                action()
            self.assertIs(error, caught.exception.__cause__)
            for part in (operation, str(folder), "expected", "next step:"):
                self.assertIn(part, str(caught.exception))

    def test_ingest_artifact_schema_coverage_after_subprocess(self):
        from ownvoice.schemas import (
            ingest_report,
            merge_state,
            names,
            records,
            rejects,
            unmapped_domains,
        )

        self.prepare()
        self.success()
        validators = {
            "records.jsonl": records.validate,
            "rejects.jsonl": rejects.validate,
            "checkpoint.json": schema.validate,
            "merge-state.json": merge_state.validate,
            "unmapped-domains.json": unmapped_domains.validate,
            "names.txt": names.validate,
        }
        for path in self.work.rglob("*"):
            if not path.is_file():
                continue
            with self.subTest(path=path.relative_to(self.work)):
                if path.name == "ingest-report.json":
                    validator = (
                        ingest_report.validate_merged
                        if path.parent == self.work
                        else ingest_report.validate
                    )
                else:
                    self.assertIn(path.name, validators)
                    validator = validators[path.name]
                if path.suffix == ".jsonl":
                    for line in path.read_text().splitlines():
                        validator(json.loads(line))
                elif path.suffix == ".json":
                    validator(json.loads(path.read_text()))
                else:
                    validator(path.read_text())
                self.assertEqual(0o600, path.stat().st_mode & 0o777)
                self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)

    def test_resume_preserves_more_than_fifty_unmapped_domains(self):
        from tests.test_ingest_extract import raw_message

        directory = self.root / "emls"
        directory.mkdir()
        for i in range(60):
            case = copy.deepcopy(self.fixture_cases["F01"])
            case["id"] = f"domains-{i}"
            (directory / f"{i:03}.eml").write_bytes(
                raw_message(case).replace(b"other@example.net", f"other@d{i}.example".encode())
            )
        self.configure([self.source(kind="eml", path=directory)])
        self.success()
        summary = json.loads((self.work / "unmapped-domains.json").read_text())
        source = self.work / "sources/synthetic"
        state = json.loads((source / "checkpoint.json").read_text())["state"]
        counts = checkpoint.domains({"checkpoint": source / "checkpoint.json"}, state)
        self.assertEqual(60, len(counts))
        self.assertEqual(50, len(summary["domains"]))
        (self.work / "merge-state.json").unlink()
        self.success()
        self.assertEqual(
            summary["domains"],
            json.loads((self.work / "unmapped-domains.json").read_text())["domains"],
        )

    def test_ingest_artifact_writes_are_owned_by_io(self):
        root = Path(__file__).resolve().parents[1] / "ownvoice"
        violations = []
        for folder in ("ingest", "readers", "extract"):
            for path in (root / folder).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    if not isinstance(node, ast.Call):
                        continue
                    name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                    direct = name in {"write", "writelines", "write_text", "write_bytes"}
                    if name == "open":
                        modes = [
                            a.value
                            for a in node.args
                            if isinstance(a, ast.Constant) and isinstance(a.value, str)
                        ]
                        modes += [
                            k.value.value
                            for k in node.keywords
                            if k.arg == "mode" and isinstance(k.value, ast.Constant)
                        ]
                        direct |= any(any(c in mode for c in "wax+") for mode in modes)
                    if direct:
                        violations.append(f"{path.relative_to(root)}:{node.lineno}")
        self.assertEqual([], violations)
