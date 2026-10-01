import json
import subprocess
import sys
import unittest

from ownvoice.errors import ValidationErrors
from ownvoice.io import PRIVATE_KEY
from ownvoice.schemas import lint as lint_schema
from ownvoice.style.lint import check
from ownvoice.style.rules_block import parse
from tests import test_profile
from tests.test_rules_block import block

LONG = " ".join(["The cat sat on the mat and the dog sat on the rug near me."] * 6)
CONTRACTED = " ".join(["I'm sure it's good and we're ready to see the cat on the rug near me."] * 6)


class LintTests(unittest.TestCase):
    # Reuse fixture builders, not ProfileTests inheritance (which would rerun its suite).
    setUp = test_profile.ProfileTests.setUp
    configure = test_profile.ProfileTests.configure
    row = test_profile.ProfileTests.row
    inputs = test_profile.ProfileTests.inputs

    def profile(self, rows=None, eligible=False):
        self.configure(eligible)
        self.inputs(rows if rows is not None else [self.row(1, LONG), self.row(2, LONG)])
        result = test_profile.ProfileTests.cli(self)
        self.assertEqual(0, result.returncode, result.stderr)
        self.stats_path = self.work / "profile/ownvoice/profile-stats.json"
        self.stats = json.loads(self.stats_path.read_text())

    def run_lint(self, text, rules="schema_version = 1", *extra):
        draft = self.root / "draft.md"
        draft.write_text(text)
        (self.root / "rules.md").write_text(block(rules))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ownvoice",
                "--config",
                str(self.config),
                "lint",
                str(draft),
                "--stats",
                str(self.stats_path),
                "--register",
                "client",
                "--medium",
                "email",
                *extra,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result

    def report(self):
        path = self.root / "lint.json"
        value = lint_schema.validate(json.loads(path.read_text()))
        self.assertEqual("private", value[PRIVATE_KEY])
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        return value

    def test_list_heavy_draft_matches_profile_sentence_metrics(self):
        item = (
            "The cat sat on the mat. The dog ran to the gate! "
            "Please bring the bag. Could you possibly go?"
        )
        text = "\n".join(f"{marker} {item}" for marker in ("-", "*", "+", "1.", "2."))
        self.profile([self.row(1, text), self.row(2, text)])
        metrics = self.stats["registers"]["client"]["metrics"]
        expected = {
            "sentence_len": 20,
            "paragraph_len": 5,
            "question_rate": 100,
            "question_softener_rate": 100,
            "exclamation_rate": 0,
            "parenthetical_rate": 0,
            "flesch_reading_ease": round(206.835 - 1.015 * 20 - 84.6 * 22 / 20, 4),
        }
        for metric, value in expected.items():
            self.assertEqual(value, metrics[metric]["mean"], metric)
        result = self.run_lint(text)
        self.assertEqual(0, result.returncode, result.stderr)
        report = self.report()
        self.assertEqual(100, report["word_count"])
        self.assertEqual(5, report["sentences"])
        self.assertTrue(report["rate_checks_enabled"])
        self.assertFalse(any(f["check_kind"] == "stats" for f in report["findings"]))
        # Force bands away from the measured values to expose lint's observations.
        for metric, value in expected.items():
            band = metrics[metric]["lint_band"]
            for percentile in ("p10", "p25", "p75", "p90"):
                band[percentile] = value + 1
        self.stats_path.write_text(json.dumps(self.stats))
        result = self.run_lint(text)
        self.assertEqual(0, result.returncode, result.stderr)
        observed = {
            f["metric"]: f["observed"] for f in self.report()["findings"] if f["metric"] in expected
        }
        self.assertEqual(expected, observed)

    def test_ban_kinds_subprocess_exit_and_summary(self):
        self.profile()
        rules = """schema_version = 1
[[ban]]
id = "no-em-dash"
kind = "char"
pattern = "—"
media = ["email"]
severity = "error"
message = "use a comma"
"""
        result = self.run_lint("Hello\nFresh — text.", rules)
        self.assertEqual(4, result.returncode, result.stderr)
        report = self.report()
        finding = next(f for f in report["findings"] if f["rule_id"] == "rules.no-em-dash")
        self.assertEqual([{"line": 2, "col": 7, "excerpt": "—"}], finding["locations"])
        self.assertIn("(register client, medium email,", result.stdout)
        self.assertIn("1 error, 0 warnings", result.stdout)
        self.assertIn("line 2 col 7:", result.stdout)
        self.assertIn("→ use a comma", result.stdout)
        for kind, pattern, text in (
            ("word", "odd", "odd oddly ODD"),
            ("phrase", "very odd", "very odd indeed"),
            ("regex", "o.d", "odd old"),
        ):
            with self.subTest(kind=kind):
                changed = (
                    rules.replace('kind = "char"', f'kind = "{kind}"')
                    .replace('pattern = "—"', f'pattern = "{pattern}"')
                    .replace('severity = "error"', 'severity = "warn"')
                )
                result = self.run_lint(text, changed)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertGreater(self.report()["summary"]["warn"], 0)

    def test_heading_forms_cli_limits_and_locations(self):
        self.profile()
        rules = "schema_version = 1\n[limits.email]\nheadings_allowed = false"
        for heading in ("# Update", "**Update**", "__Update__", "Update\n===", "Update\n---"):
            with self.subTest(heading=heading):
                result = self.run_lint("Intro.\n\n" + heading + "\nBody.", rules)
                self.assertEqual(4, result.returncode, result.stderr)
                findings = {f["rule_id"]: f for f in self.report()["findings"]}
                for rule_id in ("rules.headings_allowed", "structure.heading"):
                    self.assertEqual(
                        [{"line": 3, "col": 1, "excerpt": ""}], findings[rule_id]["locations"]
                    )
        for text in (
            "*Update*",
            "_Update_",
            "Some **bold** text.",
            "Some __bold__ text.",
            "---",
            "Update\n\n---",
        ):
            with self.subTest(text=text):
                result = self.run_lint(text, rules)
                self.assertEqual(0, result.returncode, result.stderr)
                ids = {f["rule_id"] for f in self.report()["findings"]}
                self.assertNotIn("rules.headings_allowed", ids)
                self.assertNotIn("structure.heading", ids)

    def test_ac3_excerpts_do_not_publish_draft_identities(self):
        self.profile()
        rules = """schema_version = 1
[[ban]]
id = "review-text"
kind = "regex"
pattern = ".+"
media = ["email"]
severity = "error"
message = "revise this line"
[limits.email]
headings_allowed = false
"""
        text = "# Zorvyn zorvyn@example.net example.net\n**Zorvyn +1 780 555 0123 123456789**"
        for output_format in ("text", "json"):
            with self.subTest(output_format=output_format):
                result = self.run_lint(text, rules, "--format", output_format)
                self.assertEqual(4, result.returncode, result.stderr)
                report = self.report()
                for output in ((self.root / "lint.json").read_text(), result.stdout):
                    for identity in (
                        "Zorvyn",
                        "zorvyn@example.net",
                        "example.net",
                        "+1 780 555 0123",
                        "123456789",
                    ):
                        self.assertNotIn(identity.casefold(), output.casefold())
                findings = {f["rule_id"]: f for f in report["findings"]}
                for rule_id in ("rules.review-text", "rules.headings_allowed"):
                    self.assertEqual(
                        [
                            {"line": 1, "col": 1, "excerpt": ""},
                            {"line": 2, "col": 1, "excerpt": ""},
                        ],
                        findings[rule_id]["locations"],
                    )
                self.assertEqual("revise this line", findings["rules.review-text"]["fix_hint"])

    def test_limits_overrides_media_carveouts_spelling_swearing(self):
        self.profile()
        rules = parse(
            block("""schema_version = 1
spelling = "en-GB-ise"
[limits.email]
exclamations_max = 0
emoji_max = 0
headings_allowed = false
em_dashes_max = 0
[limits.email.registers.personal]
emoji_max = 2
[swearing]
blog = ["damn"]
never = ["curses"]
""")
        )
        text = "# Heading\n" + LONG.replace(".", "!") + " 😀 — color damn curses"
        findings = check(text, self.stats, rules, "client", "email", minimum=2)[3]
        ids = {f["rule_id"] for f in findings}
        for name in (
            "exclamations_max",
            "emoji_max",
            "headings_allowed",
            "em_dashes_max",
            "spelling",
            "swearing",
        ):
            self.assertIn("rules." + name, ids)
        for name in ("exclamation_rate", "exclamations_per_email", "emoji_rate", "heading_use"):
            self.assertNotIn("stats." + name, ids)
        personal = check("😀", self.stats, rules, "personal", "email", minimum=2)[3]
        self.assertNotIn("rules.emoji_max", {f["rule_id"] for f in personal})
        blog = check("damn", self.stats, rules, "client", "blog", minimum=2)[3]
        self.assertNotIn("rules.swearing", {f["rule_id"] for f in blog})
        self.assertIn(
            "rules.swearing",
            {f["rule_id"] for f in check("curses", self.stats, rules, "client", "blog")[3]},
        )
        no_limits = check(text, self.stats, {}, "client", "email", minimum=2)[3]
        self.assertIn("stats.exclamation_rate", {f["rule_id"] for f in no_limits})

    def test_gate_fallback_and_thin_global(self):
        self.profile()
        for text in ("Short draft.", " ".join(["word"] * 90) + "."):
            words, count, enabled, findings = check(
                text, self.stats, {}, "client", "email", minimum=2
            )
            self.assertFalse(enabled)
            finding = next(f for f in findings if f["rule_id"] == "stats.short_draft")
            self.assertIn(str(words), finding["observed"])
            self.assertIn(str(count), finding["observed"])
            self.assertEqual("info", finding["severity"])
        findings = check(LONG, self.stats, {}, "personal", "email", minimum=2)[3]
        self.assertIn("stats.fallback_global", {f["rule_id"] for f in findings})
        self.assertFalse(
            any(f["severity"] == "warn" and f["check_kind"] == "stats" for f in findings)
        )
        _, _, enabled, findings = check(LONG, self.stats, {}, "client", "email", minimum=3)
        self.assertFalse(enabled)
        self.assertIn("stats.insufficient_data", {f["rule_id"] for f in findings})

    def test_current_source_and_explicit_source_subprocess(self):
        self.profile(
            [self.row(i, LONG) for i in range(1, 7)]
            + [self.row(i, CONTRACTED, "current") for i in (7, 8)]
        )
        row = next(
            r
            for r in self.stats["contrast"]
            if r["register"] == "client" and r["metric"] == "contraction_rate"
        )
        self.assertEqual("diverging", row["status"])
        default = self.run_lint(LONG)
        self.assertEqual(0, default.returncode, default.stderr)
        finding = next(
            f for f in self.report()["findings"] if f["rule_id"] == "stats.contraction_rate"
        )
        self.assertIn("source current", finding["expected"])
        explicit = self.run_lint(LONG, "schema_version = 1", "--source", "old")
        self.assertEqual(0, explicit.returncode, explicit.stderr)
        self.assertNotIn(
            "stats.contraction_rate", {f["rule_id"] for f in self.report()["findings"]}
        )

    def test_never_hit_threshold_and_observed_lexicon(self):
        self.profile([self.row(1, LONG + " robust"), self.row(2, LONG)])
        basis = self.stats["registers"]["_global"]["never_hit_basis_words"]
        for threshold, severity in ((basis, "error"), (basis + 1, "warn")):
            findings = check(
                "delve robust", self.stats, {}, "client", "email", never_min=threshold
            )[3]
            hits = {f["observed"]: f["severity"] for f in findings if f["check_kind"] == "lexicon"}
            self.assertEqual({"delve": severity, "robust": "warn"}, hits)

    def test_email_structure_uses_profile_forms(self):
        self.profile(
            [self.row(i, LONG, greeting="Hi team,", signoff="Thanks,") for i in (1, 2)],
            eligible=True,
        )
        findings = check("# Heading\n" + LONG, self.stats, {}, "client", "email", minimum=2)[3]
        structure = {f["rule_id"]: f for f in findings if f["check_kind"] == "structure"}
        self.assertEqual(
            {"structure.heading", "structure.greetings", "structure.signoffs"}, set(structure)
        )
        self.assertIn("Hi team,", structure["structure.greetings"]["fix_hint"])
        findings = check("# Heading\n" + LONG, self.stats, {}, "client", "blog", minimum=2)[3]
        self.assertFalse(any(f["check_kind"] == "structure" for f in findings))

    def test_errors_formats_and_rules_override(self):
        self.profile()
        for option, value in (("--register", "missing"), ("--source", "missing")):
            result = self.run_lint("Text.", "schema_version = 1", option, value)
            self.assertEqual(2, result.returncode, result.stderr)
            for fragment in ("select lint", "missing", "available:", "next step:"):
                self.assertIn(fragment, result.stderr)
        result = self.run_lint(
            "Text.", "schema_version = 1", "--stats", str(self.root / "absent.json")
        )
        self.assertEqual(3, result.returncode)
        for fragment in ("read lint input", "absent.json", "caused by:", "next step:"):
            self.assertIn(fragment, result.stderr)
        self.stats_path.write_text("{")
        result = self.run_lint("Text.")
        self.assertEqual(2, result.returncode)
        self.assertIn("parse lint statistics", result.stderr)
        self.assertIn("caused by:", result.stderr)

    def test_rules_validation_with_real_profile_and_json_output(self):
        self.profile()
        result = self.run_lint("Text.", 'schema_version = 2\nspelling = "invalid"')
        self.assertEqual(2, result.returncode)
        self.assertIn("schema_version", result.stderr)
        self.assertIn("spelling", result.stderr)
        alternate = self.root / "alternate.md"
        alternate.write_text(block("schema_version = 1"))
        result = self.run_lint("Text.", "invalid", "--rules", str(alternate), "--format", "json")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.report(), json.loads(result.stdout))
        with self.assertRaises(ValidationErrors):
            parse(block("schema_version = 9"))
