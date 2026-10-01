import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from email.message import EmailMessage
from pathlib import Path

from ownvoice import provenance
from ownvoice.config import DEFAULTS, load_config
from ownvoice.extract.body import extract
from ownvoice.ingest.report import build as build_report
from ownvoice.io import PRIVATE_KEY, write_json, write_jsonl
from ownvoice.schemas import extract_stamp, profile_stats, records, stats_llm
from ownvoice.style.metrics import METRIC_IDS


class ProfileTests(unittest.TestCase):
    def test_extracted_html_heading_profile_uses_body_source(self):
        for tag, inline, expected in (("b", False, 1), ("strong", False, 1), ("b", True, 0)):
            with self.subTest(tag=tag, inline=inline):
                message = EmailMessage()
                heading = f"<{tag}>Update</{tag}>"
                if inline:
                    heading = "Some " + heading + " text."
                message.set_content(f"<p>{heading}</p><p>The cat sat.</p>", subtype="html")
                text, strip = extract(message, DEFAULTS["ingest"])
                self.assertEqual("html", strip["body_source"])
                self.inputs(
                    [
                        self.row(1, text, strip=strip),
                        self.row(2, text, source="current"),
                    ]
                )
                result = self.cli()
                self.assertEqual(0, result.returncode, result.stderr)
                stats, _ = self.outputs()
                for source, value in (("old", expected), ("current", 0)):
                    metrics = stats["by_source"][source]["registers"]["_global"]["metrics"]
                    self.assertEqual(value, metrics["heading_use"]["mean"])
                self.assertEqual(
                    expected / 2, stats["registers"]["_global"]["metrics"]["heading_use"]["mean"]
                )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "work"
        self.config = self.root / "config.toml"
        (self.root / "map.toml").write_text("schema_version = 1\n")
        (self.root / "rules.md").write_text("Synthetic rules\n")
        self.configure()

    def test_file_input_digests_bind_content_without_paths(self):
        config, _ = load_config(self.config)
        for section, field in (
            ("ingest", "deny_terms_file"),
            ("ingest", "sensitive_terms"),
            ("ingest", "softeners"),
            ("profile", "llm_ism_lexicon"),
        ):
            with self.subTest(field=field):
                original = self.root / f"private-{field}.txt"
                moved = self.root / f"moved-{field}.txt"
                original.write_text("first\n")
                moved.write_text("first\n")
                cfg = deepcopy(config)
                cfg[section][field] = str(original)
                before = provenance.config_digest(cfg)
                self.assertEqual(before, provenance.config_digest(cfg))
                cfg[section][field] = str(moved)
                self.assertEqual(before, provenance.config_digest(cfg))
                moved.write_text("second\n")
                self.assertNotEqual(before, provenance.config_digest(cfg))

    def test_stale_scrub_reports_refuse_profile_chunk_and_dispatch(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from ownvoice.errors import DiagnosticError
        from ownvoice.io import write_marked_text
        from ownvoice.qual.dispatch import build, load_inputs

        self.configure(eligible=True)
        for field in ("deny_terms_file", "sensitive_terms"):
            terms = self.root / f"{field}.txt"
            terms.write_text("unmatchedword\n")
            self.configure(eligible=True)
            self.config.write_text(self.config.read_text() + f'\n[ingest]\n{field} = "{terms}"\n')
            self.inputs([self.row(1), self.row(2, source="current")])
            result = self.cli()
            self.assertEqual(0, result.returncode, result.stderr)
            write_marked_text(self.work / "names.txt", "")
            before = {str(p): p.read_bytes() for p in self.work.rglob("*") if p.is_file()}
            terms.write_text("cat\n")
            result = self.cli()
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("ownvoice ingest --reparse", result.stderr)
            manifest = self.work / "chunks/manifest.json"
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
                    str(self.work / "records.jsonl"),
                    "--pass",
                    "A",
                    "--out",
                    str(manifest),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("ownvoice ingest --reparse", result.stderr)
            self.assertFalse(manifest.parent.exists())
            config, _ = load_config(self.config)
            with self.assertRaisesRegex(DiagnosticError, "ownvoice ingest --reparse"):
                load_inputs(config, self.work / "profile/ownvoice")
            with patch("ownvoice.qual.dispatch.invoke") as invoke:
                with self.assertRaisesRegex(DiagnosticError, "ownvoice ingest --reparse"):
                    build(SimpleNamespace(config=self.config, profile_dir=None))
                invoke.assert_not_called()
            self.assertEqual(
                before, {str(p): p.read_bytes() for p in self.work.rglob("*") if p.is_file()}
            )

    def test_measurement_changes_refuse_profile_reuse_until_rebuilt(self):
        from ownvoice.errors import DiagnosticError
        from ownvoice.qual.dispatch import load_inputs

        for section, field in (("ingest", "softeners"), ("profile", "llm_ism_lexicon")):
            terms = self.root / f"{field}.txt"
            terms.write_text("perhaps\n")
            self.configure()
            text = self.config.read_text()
            text = (
                text.replace("[profile]", f'[profile]\n{field} = "{terms}"')
                if section == "profile"
                else text + f'\n[ingest]\n{field} = "{terms}"\n'
            )
            self.config.write_text(text)
            self.inputs([self.row(1), self.row(2, source="current")])
            self.assertEqual(0, self.cli().returncode)
            terms.write_text("perhaps\nmaybe\n")
            config, _ = load_config(self.config)
            with self.assertRaisesRegex(DiagnosticError, "ownvoice profile"):
                load_inputs(config, self.work / "profile/ownvoice")
            draft = self.root / "draft.txt"
            draft.write_text("The cat sat on the mat.")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ownvoice",
                    "--config",
                    str(self.config),
                    "lint",
                    str(draft),
                    "--register",
                    "client",
                    "--medium",
                    "email",
                    "--stats",
                    str(self.work / "profile/ownvoice/profile-stats.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("ownvoice profile", result.stderr)
            self.assertFalse((self.root / "lint.json").exists())
            result = self.cli()
            self.assertEqual(0, result.returncode, result.stderr)
            load_inputs(config, self.work / "profile/ownvoice")
            for path in self.work.rglob("*"):
                if path.is_file():
                    self.assertNotIn(str(terms), path.read_text())

    def configure(self, eligible=False):
        self.config.write_text(f'''schema_version = 1
[owner]
addresses = ["owner@example.com"]
names = ["Owner"]
timezone = "UTC"
[paths]
work_dir = "{self.work}"
domain_map = "map.toml"
editorial_rules = "rules.md"
[profile]
thin_register_min = 2
never_hit_min_words = 10
[[source]]
label = "old"
kind = "mbox"
path = "old.mbox"
llm_eligible = {str(eligible).lower()}
[[source]]
label = "current"
kind = "mbox"
path = "current.mbox"
[llm]
provider = "synthetic"
retention_terms = "synthetic"
training_use = "none"
attestation = "2026-09-25 synthetic"
''')

    def row(self, index, text="The cat sat on the mat.", source="old", **changes):
        value = records.build(
            record_id=f"{index:016x}",
            source=source,
            era=None,
            source_kind="mbox",
            year=2026,
            weekday=4,
            hour_bucket="morning",
            recipient_class="client",
            recipient_count_bucket="1",
            recipient_stages={"smtp": 1, "x500": 0, "names": 0, "unknown": 0},
            thread_position="new",
            word_count=len(text.split()),
            text=text,
            greeting=None,
            signoff=None,
            strip={
                "body_source": "plain",
                "rules_fired": [],
                "inline_reply": False,
                "confidence": "high",
                "flags": [],
            },
            scrub={
                "greeting_names": 0,
                "lexicon_names": 0,
                "emails": 0,
                "phones": 0,
                "urls": 0,
                "numbers": 0,
                "residual_capitalised": [],
            },
            template=False,
            sensitive=False,
        )
        value.update(changes)
        return value

    def inputs(self, rows, partial=False):
        config, _ = load_config(self.config)
        prov = provenance.build(
            config, self.root / "map.toml", self.root / "rules.md", timestamp="2026-09-25T00:00:00Z"
        )
        fingerprint = {"size": 0, "mtime_ns": 0, "first_sha256": None, "last_sha256": None}
        for source in config["source"]:
            selected = [r for r in rows if r["source"] == source["label"]]
            report = build_report(
                source,
                prov,
                fingerprint,
                selected,
                [],
                len(selected),
                {
                    "recipients": len(selected),
                    "smtp": len(selected),
                    "x500": 0,
                    "names": 0,
                    "unknown": 0,
                },
                {},
                set(),
            )
            report["status"] = "complete"
            if partial and source["label"] == "old":
                report["status"] = "partial"
                report["folders"][0]["error"] = "synthetic folder read failure"
            write_json(self.work / "sources" / source["label"] / "ingest-report.json", report)
            write_jsonl(self.work / "sources" / source["label"] / "records.jsonl", selected)
        write_jsonl(self.work / "records.jsonl", rows)
        return prov, fingerprint

    def cli(self, *extra):
        return subprocess.run(
            [sys.executable, "-m", "ownvoice", "--config", str(self.config), "profile", *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def outputs(self):
        root = self.work / "profile" / "ownvoice"
        output = []
        for name, schema in (("profile-stats.json", profile_stats), ("stats-llm.json", stats_llm)):
            path = root / name
            value = json.loads(path.read_text())
            schema.validate(value)
            self.assertEqual("private", value[PRIVATE_KEY])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
            output.append(value)
        return output

    def test_subprocess_determinism_all_metrics_and_contracts(self):
        self.inputs([self.row(1), self.row(2, source="current")])
        first = self.cli()
        self.assertEqual(0, first.returncode, first.stderr)
        stats, projection = self.outputs()
        for registers in [
            stats["registers"],
            *(s["registers"] for s in stats["by_source"].values()),
        ]:
            for register in registers.values():
                self.assertEqual(set(METRIC_IDS), set(register["metrics"]))
        self.assertEqual("professional-warm", stats["registers"]["article"]["derived_from"])
        paths = list((self.work / "profile/ownvoice").glob("*.json"))
        before = {p.name: p.read_bytes() for p in paths}
        second = self.cli()
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in paths})
        self.assertNotIn("by_source", projection)
        for register in projection["registers"].values():
            for key in ("greetings", "signoffs", "ngrams", "discourse_markers", "hedges"):
                self.assertNotIn(key, register)

    def test_contrast_and_thin_source(self):
        rows = [self.row(i) for i in range(1, 7)] + [
            self.row(i, "I'm ready.", "current") for i in (7, 8)
        ]
        self.inputs(rows)
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        stats, projection = self.outputs()
        row = next(
            r
            for r in stats["contrast"]
            if r["register"] == "client" and r["metric"] == "contraction_rate"
        )
        self.assertEqual("diverging", row["status"])
        self.assertEqual("current", row["default_source"])
        self.assertIn(row, projection["contrast"])
        self.assertTrue(
            all(
                r["status"] == "insufficient_data"
                for r in stats["contrast"]
                if r["register"] == "personal"
            )
        )

    def test_eligible_only_phrases_sensitive_and_residual_filters(self):
        self.configure(eligible=True)
        rows = [self.row(i, "bright moon", greeting="Hi team,") for i in range(1, 7)]
        rows += [
            self.row(i, "secretquartz secretopal", "current", greeting="secretgreeting")
            for i in range(7, 13)
        ]
        rows += [self.row(i, "sensitivemoon sensitiveopal", sensitive=True) for i in range(13, 19)]
        residual = self.row(19)["scrub"]
        residual["residual_capitalised"] = ["Zyxora"]
        rows += [self.row(i, "residualmoon residualopal", scrub=residual) for i in range(19, 25)]
        # Repeated phrases in distinct messages must survive the merge template pass.
        for index, row in enumerate(rows):
            row["text"] += f" sample {index}"
            row["word_count"] = len(row["text"].split())
        self.inputs(rows)
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        _, projection = self.outputs()
        text = json.dumps(projection)
        for token in (
            "secretquartz",
            "secretopal",
            "secretgreeting",
            "sensitivemoon",
            "sensitiveopal",
            "residualmoon",
            "residualopal",
        ):
            self.assertNotIn(token, text)
        self.assertIn("bright moon", text)
        self.assertIn("Hi team,", text)

    def test_empty_partial_stale_refusals_and_overrides(self):
        self.inputs([])
        result = self.cli()
        self.assert_refusal(result, "records.jsonl", "0 usable records")
        prov, fingerprint = self.inputs([self.row(1)], partial=True)
        result = self.cli()
        self.assert_refusal(result, "old", "failed folders: messages")
        self.assertEqual(0, self.cli("--allow-partial").returncode)
        self.inputs([self.row(1)])
        prov["generated_at"] = "2000-01-01T00:00:00Z"
        write_json(
            self.work / "sources/old/extract/.done",
            extract_stamp.build(**prov, fingerprint=fingerprint),
        )
        result = self.cli()
        self.assert_refusal(result, "old", "ownvoice clean --extracted old")
        allowed = self.cli("--allow-stale-dump")
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def assert_refusal(self, result, identity, detail):
        self.assertEqual(2, result.returncode, result.stderr)
        for part in ("compute profile", identity, detail, "expected", "next step:"):
            self.assertIn(part, result.stderr)

    def test_templates_confidence_gated_fallback_and_time(self):
        long = " ".join(["The cat sat on the mat and the dog sat on the rug near me."] * 6)
        rows = [self.row(1, long), self.row(2, long), self.row(3, recipient_class="personal")]
        rows.extend(self.row(i, "template text", template=True) for i in (4, 5, 6))
        low = self.row(7)
        low["strip"]["confidence"] = "low"
        rows.append(low)
        self.inputs(rows)
        result = self.cli()
        self.assertEqual(0, result.returncode, result.stderr)
        stats, projection = self.outputs()
        self.assertEqual(4, stats["corpus"]["records"])
        self.assertEqual(1, stats["corpus"]["low_confidence_excluded"])
        band = stats["registers"]["personal"]["metrics"]["words"]["lint_band"]
        self.assertTrue(band["fallback_global"])
        self.assertEqual(2, band["n_gated"])
        self.assertEqual(90, band["p10"])
        self.assertEqual({"2026": 4}, stats["time"]["by_year"])
        self.assertIn("llm_ism_never_hit", projection["registers"]["_global"])
        self.assertNotIn("llm_ism_never_hit", projection["registers"]["personal"])

    def test_sources_and_custom_records(self):
        self.inputs([self.row(1), self.row(2, source="current")])
        custom = self.root / "custom.jsonl"
        write_jsonl(custom, [self.row(3, source="current")])
        result = self.cli("--sources", "current", "--records", str(custom))
        self.assertEqual(0, result.returncode, result.stderr)
        stats, _ = self.outputs()
        self.assertEqual(["current"], list(stats["by_source"]))
        self.assertEqual(1, stats["corpus"]["records"])

    def test_eligible_sources_limited_to_selection(self):
        self.configure(eligible=True)
        self.config.write_text(
            self.config.read_text().replace(
                'path = "current.mbox"', 'path = "current.mbox"\nllm_eligible = true'
            )
        )
        self.inputs([self.row(1), self.row(2, source="current")])
        result = self.cli("--sources", "old")
        self.assertEqual(0, result.returncode, result.stderr)
        stats, _ = self.outputs()
        self.assertEqual({"old"}, set(stats["corpus"]["sources"]))
        self.assertTrue(stats["corpus"]["sources"]["old"]["llm_eligible"])

    def test_duplicate_sources_ingest_and_profile(self):
        self.config.write_text(
            self.config.read_text().replace("old", "one").replace("current", "two")
        )
        bodies = {"one": "The cat sat on the mat.", "two": "The dog ran."}
        for label, body in bodies.items():
            (self.root / f"{label}.mbox").write_text(
                "From owner@example.com Fri Sep 25 10:00:00 2026\n"
                "From: owner@example.com\nTo: friend@example.net\n"
                "Message-ID: <shared@example.com>\n"
                "Date: Fri, 25 Sep 2026 10:00:00 +0000\n"
                f"Content-Type: text/plain\n\n{body}\n\n"
            )
        ingested = subprocess.run(
            [sys.executable, "-m", "ownvoice", "--config", str(self.config), "ingest"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, ingested.returncode, ingested.stderr)
        for selected in (None, "one", "two", "two,one"):
            with self.subTest(selected=selected):
                result = self.cli(*(["--sources", selected] if selected else []))
                self.assertEqual(0, result.returncode, result.stderr)
                stats, _ = self.outputs()
                labels = selected.split(",") if selected else list(bodies)
                self.assertEqual(1, stats["corpus"]["records"])
                self.assertEqual(set(labels), set(stats["by_source"]))
                for label in labels:
                    self.assertEqual(1, stats["corpus"]["sources"][label]["records"])
                    register = stats["by_source"][label]["registers"]["_global"]
                    self.assertEqual(1, register["n"])
                    self.assertEqual(
                        len(bodies[label].split()), register["metrics"]["words"]["p50"]
                    )
                winner = "one" if "one" in labels else "two"
                self.assertEqual(
                    len(bodies[winner].split()),
                    stats["registers"]["_global"]["metrics"]["words"]["p50"],
                )

    def test_records_override_remains_authoritative(self):
        self.inputs([self.row(1), self.row(2, source="current")])
        custom = self.root / "custom.jsonl"
        write_jsonl(custom, [self.row(3, "A short note.", source="current")])
        for path in (self.work / "sources").glob("*/records.jsonl"):
            path.unlink()
        result = self.cli("--records", str(custom))
        self.assertEqual(0, result.returncode, result.stderr)
        stats, _ = self.outputs()
        self.assertEqual(1, stats["corpus"]["records"])
        self.assertEqual(0, stats["by_source"]["old"]["registers"]["_global"]["n"])
        self.assertEqual(3, stats["registers"]["_global"]["metrics"]["words"]["p50"])
        result = self.cli("--records", str(custom), "--sources", "old")
        self.assert_refusal(result, "custom.jsonl", "0 usable records")

    def test_input_diagnostics_and_git_write_refusal(self):
        self.inputs([self.row(1)])
        invalid = self.cli("--sources", "missing")
        self.assertEqual(2, invalid.returncode)
        for part in ("select profile sources", "--sources", "expected", "next step:"):
            self.assertIn(part, invalid.stderr)
        missing = self.cli("--records", str(self.root / "absent.jsonl"))
        self.assertEqual(3, missing.returncode)
        for part in ("read profile input", "absent.jsonl", "caused by:", "next step:"):
            self.assertIn(part, missing.stderr)
        output = self.root / "repo"
        (output / ".git").mkdir(parents=True)
        refused = self.cli("--out-dir", str(output))
        self.assertEqual(2, refused.returncode)
        self.assertIn("write private artefact", refused.stderr)
        self.assertFalse((output / "profile-stats.json").exists())

    def test_unknown_record_source_failed_and_mismatched_reports(self):
        self.inputs([self.row(1)])
        write_jsonl(self.work / "sources/old/records.jsonl", [self.row(1, source="unconfigured")])
        result = self.cli()
        self.assertEqual(2, result.returncode)
        for part in ("validate profile sources", "records.jsonl", "next step:"):
            self.assertIn(part, result.stderr)
        self.inputs([self.row(1)])
        path = self.work / "sources/old/ingest-report.json"
        report = json.loads(path.read_text())
        report["status"] = "failed"
        write_json(path, report)
        self.assert_refusal(self.cli(), "old", "status=failed")
        report["status"] = "complete"
        report["source"] = "current"
        write_json(path, report)
        result = self.cli()
        self.assertEqual(2, result.returncode)
        for part in ("validate profile report", "old", "next step:"):
            self.assertIn(part, result.stderr)

    def test_configured_lexicon_diagnostic(self):
        self.inputs([self.row(1)])
        text = self.config.read_text().replace(
            "[profile]", '[profile]\nllm_ism_lexicon = "absent-terms.txt"'
        )
        self.config.write_text(text)
        result = self.cli()
        self.assertEqual(2, result.returncode)
        for part in ("read profile lexicon", "absent-terms.txt", "caused by:", "next step:"):
            self.assertIn(part, result.stderr)


if __name__ == "__main__":
    unittest.main()
