import json
import random
import subprocess
import sys
import unittest

from ownvoice.extract import dedup
from tests import test_ingest_cli
from tests.test_scrub import raw


class DedupTests(unittest.TestCase):
    def test_merge_templates_are_repeated_and_source_flags_independent(self):
        rows = [{"record_id": str(i), "text": "Please reply.", "template": False} for i in range(3)]
        for row in rows:
            dedup.templates([row])
        merged, n = dedup.merge(rows)
        self.assertEqual(0, n)
        self.assertTrue(all(r["template"] for r in merged))
        self.assertTrue(all(not r["template"] for r in rows))


class DedupIngestTests(unittest.TestCase):
    setUp = test_ingest_cli.IngestCliTests.setUp
    configure = test_ingest_cli.IngestCliTests.configure
    source = test_ingest_cli.IngestCliTests.source
    cli = test_ingest_cli.IngestCliTests.cli
    read_outputs = test_ingest_cli.IngestCliTests.read_outputs

    def test_fixed_seed_two_source_invariants_and_source_folder_order(self):
        rng = random.Random(2701)
        sampled = [[rng.randrange(60) for _ in range(100)] for _ in range(2)]
        sources = []
        for label, sample in zip(("first", "second"), sampled):
            path = self.root / label
            path.mkdir()
            for index, identity in enumerate(sample):
                # Sorted file order determines the winner of conflicting duplicate bodies.
                case = {
                    "id": f"random-{identity}",
                    "body": f"Please review item {identity} copy {index}.",
                }
                (path / f"{index:03}.eml").write_bytes(raw(case))
            sources.append(self.source(label, "eml", path))
        self.configure(sources)
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        for label, sample in zip(("first", "second"), sampled):
            records, rejects, report = self.read_outputs(label)
            self.assertEqual(len(sample), len(records) + len(rejects))
            self.assertEqual(len(set(sample)), len(records))
            self.assertEqual(len(sample) - len(set(sample)), report["duplicates"])
            self.assertTrue(all(r["reason"] == "duplicate" for r in rejects))
            for record, identity in zip(records, dict.fromkeys(sample)):
                self.assertEqual(
                    f"Please review item {identity} copy {sample.index(identity)}.", record["text"]
                )
        merged = [
            json.loads(line) for line in (self.work / "records.jsonl").read_text().splitlines()
        ]
        report = json.loads((self.work / "ingest-report.json").read_text())
        self.assertEqual(len(set(sampled[0]) | set(sampled[1])), len(merged))
        self.assertEqual(len(set(sampled[0]) & set(sampled[1])), report["cross_source_duplicates"])
        self.assertEqual(
            sum(report["sources"].values()) - report["cross_source_duplicates"], len(merged)
        )
        self.assertEqual(
            ["first"] * len(set(sampled[0])), [r["source"] for r in merged[: len(set(sampled[0]))]]
        )

    def test_corrupt_merge_subprocess_exits_internal_error(self):
        path = self.root / "one.eml"
        path.write_bytes(raw({"id": "one", "body": "Please reply."}))
        self.configure([self.source(kind="eml", path=path)])
        code = """import sys
from unittest.mock import patch
from ownvoice.cli import main
with patch('ownvoice.extract.dedup.merge', return_value=([], 0)):
    sys.exit(main(['--config', sys.argv[1], 'ingest']))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.config)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        for part in (
            "internal error (this is a bug)",
            "account for merged records",
            "ingest-report.json",
            "merged_records=0, expected=1",
            "ValueError",
            "next step:",
        ):
            self.assertIn(part, result.stderr)
        self.assertFalse((self.work / "records.jsonl").exists())
