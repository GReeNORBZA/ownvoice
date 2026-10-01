"""Article medium and bands, baseline cutoff, Subject skip, Tier A/B tells.

Synthetic fixtures only: no corpus text, drafts or names from any owner.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from ownvoice.config import MEDIA, load_config, validate_config
from ownvoice.errors import ValidationErrors
from ownvoice.provenance import config_digest
from ownvoice.schemas import exemplars as exemplar_schema
from ownvoice.style import tells
from ownvoice.style.lint import check, matches, without_subject
from ownvoice.style.rules_block import load, parse
from tests import test_profile
from tests.test_delta import manifest
from tests.test_lint import LONG
from tests.test_rules_block import block
from tests.test_write_in_voice_dryrun import brief, load_workflow

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills/editorial-rules/editorial-rules.ai-tells.example.md"
SENTENCE = "The team moved the files to the new server today."


def filler(sentences):
    return " ".join([SENTENCE] * sentences)


def long_email(index):
    """Two paragraphs of plain synthetic prose, about 110 words, 11 sentences."""
    first = " ".join(
        f"We checked item {word} on the list and it passed."
        for word in ("one", "two", "three", "four", "five")
    )
    second = " ".join(
        f"The report for batch {word} goes out on the usual day."
        for word in ("alpha", "beta", "gamma", "delta", "omega", "sigma")
    )
    # Distinct lengths keep the upper length tertile nonempty (ties go to the lower one).
    return f"{first} Note {index}.{' Extra.' * index}\n\n{second}"


class TellMetricTests(unittest.TestCase):
    def test_each_metric_fires_on_its_synthetic_pattern(self):
        long_text = filler(16)  # 160 words, uniform sentences
        cases = {
            "sentence_cv": (filler(8), 0.0),
            "ing_tail_rate": (
                "We shipped it, showing progress. One. Two here. Three now. Four done.",
                20.0,
            ),
            "tricolon_rate": (long_text + " We bought apples, pears, and plums.", 1000 / 166),
            "tricolon_paragraphs": ("We bought apples, pears, and plums. Red, green, or blue.", 1),
            "negation_contrast_rate": (long_text + " We chose speed rather than cost.", 1000 / 166),
            "ai_vocab_rate": (long_text + " It was a crucial step.", 500 / 165),
            "staccato_runs": ("It broke. We fixed it. It works now. Good.", 1),
            "anaphora_runs": ("Backups run nightly. Backups are kept. Backups are tested.", 1),
            "heading_density": ("# Plan\n\n" + long_text, 300 / 161),
            "bold_first_bullets": ("- **One**: a\n- **Two**: b\n- three c", 2 / 3),
            "connector_rate": (long_text + " Moreover, it worked.", 1000 / 163),
            "balanced_openers": (long_text + " While the plan was late, it shipped.", 1000 / 167),
            "magic_adverb_rate": (long_text + " It was deeply odd.", 1000 / 164),
            "hedge_stacks": ("This might potentially slip. It could possibly move.", 2),
            "service_phrases": ("Do not hesitate to call. Feel free to reach out.", 2),
        }
        for metric, (text, expected) in cases.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(expected, tells.measure(text)[metric], places=4)

    def test_pivot_and_aphorism_units(self):
        para = filler(3)  # 30 words
        text = f"{para}\n\nThat changed things.\n\n{para}"
        self.assertEqual(1, tells.measure(text)["pivot_paragraphs"])
        self.assertEqual(0, tells.measure(f"{para}\n\n{para}")["pivot_paragraphs"])
        sections = (
            "# One\n\nWe moved the job to March. Trust is the cost of good work.\n\n"
            "# Two\n\nThe second run passed on the third of May."
        )
        self.assertEqual(0.5, tells.measure(sections)["aphorism_ratio"])
        self.assertTrue(tells.aphoristic("In the end, clarity is what people value."))
        for sentence in (
            "It is about trust.",  # pronoun start
            "Trust is the cost of 3 days.",  # digit
            "Trust matters to Acme.",  # capitalised word after word one
            "Trust is how the work gets done?",  # not a full stop
        ):
            with self.subTest(sentence=sentence):
                self.assertFalse(tells.aphoristic(sentence))

    def test_short_texts_mark_length_gated_metrics_not_applicable(self):
        values = tells.measure("Short note. Nothing else.")
        for metric in (
            "sentence_cv",
            "ing_tail_rate",
            "tricolon_rate",
            "ai_vocab_rate",
            "heading_density",
            "bold_first_bullets",
        ):
            self.assertIsNone(values[metric], metric)
        self.assertEqual(set(tells.METRICS), set(values))
        self.assertEqual(set(tells.METRICS), set(tells.HINTS))
        # Parked metrics are declared, never silently measured.
        self.assertEqual({"syntactic_templates", "recap_overlap"}, set(tells.NOT_IMPLEMENTED))
        self.assertFalse(set(tells.NOT_IMPLEMENTED) & set(values))

    def test_subject_line_skip(self):
        self.assertEqual("Hi team,\nBody.", without_subject("Subject: Plan\n\n\nHi team,\nBody."))
        self.assertEqual("Hi team,\nBody.", without_subject("\nSubject: Plan\nHi team,\nBody."))
        self.assertEqual("Body.\nSubject: late", without_subject("Body.\nSubject: late"))
        self.assertEqual("", without_subject("Subject: only"))


class ProfileLintTests(unittest.TestCase):
    setUp = test_profile.ProfileTests.setUp
    configure = test_profile.ProfileTests.configure
    row = test_profile.ProfileTests.row
    inputs = test_profile.ProfileTests.inputs
    cli = test_profile.ProfileTests.cli
    outputs = test_profile.ProfileTests.outputs

    def cutoff(self, value='"2023-01-01"'):
        text = self.config.read_text().replace("[profile]", f"[profile]\nbaseline_before = {value}")
        self.config.write_text(text)

    def corpus(self, extra="", years=(2020,)):
        rows = []
        for i, year in enumerate(years * 4, start=1):
            rows.append(self.row(i, long_email(i) + extra, year=year))
            rows.append(self.row(100 + i, f"Short synthetic reply {i}.", year=year))
        return rows

    def profile(self, rows, *extra):
        self.inputs(rows)
        result = self.cli(*extra)
        self.assertEqual(0, result.returncode, result.stderr)
        self.stats_path = self.work / "profile/ownvoice/profile-stats.json"
        stats, _ = self.outputs()
        return stats, result

    def lint(self, text, *extra, rules="schema_version = 1"):
        draft = self.root / "draft.md"
        draft.write_text(text)
        (self.root / "rules.md").write_text(block(rules))
        return subprocess.run(
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
                *extra,
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_thresholds_come_from_each_profile_not_constants(self):
        plain, _ = self.profile(self.corpus())
        stacked, _ = self.profile(
            self.corpus(" It might potentially slip and could possibly move.")
        )
        for stats, expected in ((plain, 0), (stacked, 2)):
            row = stats["registers"]["_global"]["ai_tells"]["hedge_stacks"]
            self.assertEqual(
                {"direction": "max", "basis": "register"},
                {key: row[key] for key in ("direction", "basis")},
            )
            self.assertEqual(expected, row["threshold"])
        cv = plain["registers"]["_global"]["ai_tells"]["sentence_cv"]
        self.assertEqual("min", cv["direction"])
        # The definitional floor: one service phrase alone never warns.
        self.assertEqual(
            1, plain["registers"]["_global"]["ai_tells"]["service_phrases"]["threshold"]
        )
        # A thin register takes _global's threshold and says so.
        personal = plain["registers"]["personal"]["ai_tells"]["hedge_stacks"]
        self.assertEqual(("_global", 0), (personal["basis"], personal["threshold"]))

    def test_lint_warns_on_crossed_threshold_with_message_content(self):
        self.profile(self.corpus())
        result = self.lint(
            LONG + " It might potentially slip.", "--register", "client", "--medium", "email"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        finding = next(f for f in report["findings"] if f["rule_id"] == "ai.hedge_stacks")
        self.assertEqual(
            ("warn", "stats", 1), (finding["severity"], finding["check_kind"], finding["observed"])
        )
        self.assertRegex(finding["expected"], r"^at most 0(\.0)? \(p90, basis register, n 8\)$")
        self.assertEqual(tells.HINTS["hedge_stacks"], finding["fix_hint"])
        clean = json.loads(self.lint(LONG, "--register", "client", "--medium", "email").stdout)
        self.assertNotIn("ai.hedge_stacks", {f["rule_id"] for f in clean["findings"]})

    def test_legacy_profile_without_ai_tells_reports_info(self):
        stats, _ = self.profile(self.corpus())
        for register in stats["registers"].values():
            register.pop("ai_tells")
        findings = check(LONG, stats, {}, "client", "email", minimum=2)[3]
        info = next(f for f in findings if f["rule_id"] == "ai.not_profiled")
        self.assertEqual("info", info["severity"])
        self.assertIn("rerun ownvoice profile", info["fix_hint"])

    def test_subject_line_does_not_hide_greeting(self):
        self.configure(eligible=True)
        rows = [
            self.row(i, LONG + f" Note {i}.", greeting="Hi team,", year=2020) for i in (1, 2, 3)
        ]
        stats, _ = self.profile(rows)
        draft = "Subject: Weekly plan\n\nHi team,\n" + LONG
        ids = {f["rule_id"] for f in check(draft, stats, {}, "client", "email", minimum=2)[3]}
        self.assertNotIn("structure.greetings", ids)
        # Control: a genuinely missing greeting still warns after the subject line.
        missing = check("Subject: Weekly plan\n\n" + LONG, stats, {}, "client", "email", minimum=2)
        self.assertIn("structure.greetings", {f["rule_id"] for f in missing[3]})

    def test_article_medium_cli_rules_and_no_global_fallback(self):
        stats, _ = self.profile(self.corpus())
        article = stats["registers"]["article"]
        self.assertEqual("professional-warm", stats["baseline"]["article_basis"])
        self.assertTrue(
            all(not m["lint_band"]["fallback_global"] for m in article["metrics"].values())
        )
        self.assertEqual(
            ("article_shape", tells.ARTICLE_HEADING_DENSITY_MAX),
            (
                article["ai_tells"]["heading_density"]["basis"],
                article["ai_tells"]["heading_density"]["threshold"],
            ),
        )
        rules = (
            'schema_version = 1\n[[ban]]\nid = "long-form-only"\nkind = "phrase"\n'
            'pattern = "synthetic banned phrase"\nmedia = ["article"]\nseverity = "error"\n'
            'message = "remove it"\n'
        )
        text = "# Heading\n\n" + LONG + " A synthetic banned phrase."
        result = self.lint(text, "--register", "article", "--medium", "article", rules=rules)
        self.assertEqual(4, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("article", report["medium"])
        ids = {f["rule_id"] for f in report["findings"]}
        self.assertIn("rules.long-form-only", ids)
        self.assertIn("stats.article_shape", ids)
        self.assertNotIn("stats.fallback_global", ids)
        for metric in ("words", "paragraphs", "heading_use"):
            self.assertNotIn("stats." + metric, ids)
        blog = self.lint(text, "--register", "article", "--medium", "blog", rules=rules)
        self.assertEqual(0, blog.returncode, blog.stderr)
        invalid = self.lint(text, "--register", "article", "--medium", "essay")
        self.assertEqual(2, invalid.returncode)
        self.assertIn("essay", invalid.stderr)

    def test_legacy_article_band_copied_from_global_is_not_used(self):
        stats, _ = self.profile(self.corpus())
        for metric in stats["registers"]["article"]["metrics"].values():
            metric["lint_band"]["fallback_global"] = True
        findings = check(LONG, stats, {}, "article", "article", minimum=2)[3]
        ids = {f["rule_id"] for f in findings}
        self.assertIn("stats.insufficient_data", ids)
        self.assertNotIn("stats.fallback_global", ids)
        self.assertFalse(
            any(
                f["check_kind"] == "stats"
                and f["severity"] == "warn"
                and f["rule_id"].startswith("stats.")
                for f in findings
            )
        )

    def test_baseline_cutoff_filters_records_and_records_provenance(self):
        self.configure(eligible=True)
        self.cutoff()
        rows = self.corpus(years=(2020,))
        rows += [
            self.row(300 + i, "Later synthetic text " + str(i) + ".", year=2024) for i in (1, 2)
        ]
        rows += [self.row(400, "Undated synthetic text.", year=None)]
        stats, result = self.profile(rows)
        self.assertEqual(
            {
                "before": "2023-01-01",
                "granularity": "year",
                "excluded_after": 2,
                "excluded_undated": 1,
                "article_basis": "long_emails",
                "article_finals_excluded": False,
            },
            {
                key: stats["baseline"][key]
                for key in (
                    "before",
                    "granularity",
                    "excluded_after",
                    "excluded_undated",
                    "article_basis",
                    "article_finals_excluded",
                )
            },
        )
        self.assertEqual(8, stats["corpus"]["records"])
        self.assertEqual({"2020": 8}, stats["time"]["by_year"])
        self.assertIn("baseline_before 2023-01-01: kept 8 records", result.stderr)
        self.assertIn("excluded 2 from later years and 1 undated", result.stderr)
        retained = (self.work / "profile/ownvoice/profiled-records.jsonl").read_text()
        self.assertNotIn("Later synthetic", retained)
        self.assertNotIn("Undated synthetic", retained)
        article = stats["registers"]["article"]
        self.assertEqual(("_global", 3), (article["derived_from"], article["n"]))
        self.assertEqual(3, stats["baseline"]["long_emails"])

    def test_cutoff_excludes_article_finals_and_uses_long_email_paragraphs(self):
        self.configure(eligible=True)
        self.cutoff()
        chains = manifest(
            self,
            ["Draft words here.", "Published synthetic article paragraph with zebraword.\n\nMore."],
            "owner",
        )
        stats, _ = self.profile(self.corpus(), "--articles", str(chains))
        self.assertTrue(stats["baseline"]["article_finals_excluded"])
        self.assertEqual("long_emails", stats["baseline"]["article_basis"])
        self.assertEqual("_global", stats["registers"]["article"]["derived_from"])
        output = self.work / "profile/ownvoice"
        examples = exemplar_schema.validate(json.loads((output / "exemplars.json").read_text()))
        article = examples["registers"]["article"]
        self.assertEqual("long_email_paragraphs", article["selection"]["basis"])
        self.assertTrue(article["items"])
        texts = [item["text"] for item in article["items"]]
        self.assertFalse(any("zebraword" in text for text in texts))
        self.assertTrue(all(any(t in long_email(i) for i in range(1, 5)) for t in texts))
        self.assertNotIn("zebraword", (output / "profile-stats.json").read_text())
        # Finals still reach the qualitative pass, which the cutoff does not govern.
        self.assertIn("zebraword", (output / "profiled-articles.jsonl").read_text())

    def test_article_exemplar_shortfall_is_disclosed(self):
        self.configure(eligible=True)
        rows = [self.row(1, long_email(1), year=2020), self.row(2, "Short one.", year=2020)]
        rows[0]["text"] = rows[0]["text"].split("\n\n")[0]  # one paragraph only
        self.profile(rows)
        examples = json.loads((self.work / "profile/ownvoice/exemplars.json").read_text())
        selection = examples["registers"]["article"]["selection"]
        self.assertEqual({"wanted": 3, "selected": selection["selected"]}, selection["shortfall"])
        self.assertLess(selection["selected"], 3)

    def test_cutoff_that_excludes_everything_is_explained(self):
        self.cutoff('"2000-01-01"')
        self.inputs(self.corpus())
        result = self.cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("baseline_before 2000-01-01: kept 0 records", result.stderr)
        self.assertIn("excluded 8 from later years", result.stderr)
        self.assertIn("0 usable records", result.stderr)


class ConfigAndContractTests(unittest.TestCase):
    def base(self):
        return {
            "schema_version": 1,
            "owner": {"addresses": ["owner@example.com"], "names": ["Owner"], "timezone": "UTC"},
            "paths": {"work_dir": "w", "domain_map": "m.toml", "editorial_rules": "r.md"},
            "source": [{"label": "old", "kind": "mbox", "path": "old.mbox"}],
        }

    def test_baseline_before_validation_and_digest(self):
        for value in ("2023-13-01", "2023/01/01", "20230101", 20230101, ""):
            with self.subTest(value=value):
                data = self.base()
                data["profile"] = {"baseline_before": value}
                with self.assertRaises(ValidationErrors) as caught:
                    validate_config(data)
                message = str(caught.exception)
                self.assertIn("profile.baseline_before", message)
                self.assertIn("YYYY-MM-DD", message)
                self.assertIn("omit the key for no cutoff", message)
        unset = validate_config(self.base())
        self.assertNotIn("baseline_before", unset["profile"])
        data = self.base()
        data["profile"] = {"baseline_before": "2023-01-01"}
        cut = validate_config(data)
        self.assertEqual("2023-01-01", cut["profile"]["baseline_before"])

    def test_digest_changes_only_when_cutoff_is_set(self):
        fixture = test_profile.ProfileTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = config_digest(load_config(fixture.config)[0])
        self.assertEqual(before, config_digest(load_config(fixture.config)[0]))
        text = fixture.config.read_text().replace(
            "[profile]", '[profile]\nbaseline_before = "2023-01-01"'
        )
        fixture.config.write_text(text)
        self.assertNotEqual(before, config_digest(load_config(fixture.config)[0]))

    def test_media_contract_and_register_mapping(self):
        self.assertEqual(("email", "article", "blog", "linkedin", "doc", "proposal"), MEDIA)
        contract = json.loads((ROOT / "skills/write-in-voice/contract.json").read_text())
        self.assertEqual(list(MEDIA), contract["media"])
        workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        self.assertEqual("article", workflow.register_for(brief(medium="article")))
        self.assertEqual("article", workflow.register_for(brief(medium="blog")))
        rules = parse(block("schema_version = 1\n[limits.article]\nheadings_allowed = true"))
        self.assertTrue(rules["limits"]["article"]["headings_allowed"])
        with self.assertRaises(ValidationErrors) as caught:
            parse(block("schema_version = 1\n[limits.essay]\nemoji_max = 0"))
        self.assertIn("limits.essay", str(caught.exception))

    def test_write_in_voice_prompt_has_generic_ai_patterns_block(self):
        prompt = (ROOT / "skills/write-in-voice/PROMPT.md").read_text()
        block_text = prompt.split("## AI-writing patterns\n", 1)[1].split("\n## ", 1)[0]
        for phrase in ("Never invent first-person experience", "End once", "semicolon"):
            self.assertIn(phrase, block_text)
        self.assertNotRegex(block_text, r"\bIan\b")


# Synthetic positive per Tier A entry in the example pack.
POSITIVES = {
    "ait-a01-style-vocabulary": "Let us delve into it.",
    "ait-a02-participial-gloss": "Sales rose, highlighting demand.",
    "ait-a03-negative-parallelism": "It's not a bug, it's a feature.",
    "ait-a04-correlative-inflation": "It is not just fast but also cheap.",
    "ait-a05-significance-inflation": "The tool serves as a reminder of scale.",
    "ait-a05-this-highlights": "Costs fell. This highlights the gain.",
    "ait-a06-reversal-copula": "The fix isn't a patch. It's a rewrite.",
    "ait-a06-reversal-have": "You don't need more tools. You need fewer.",
    "ait-a06-reversal-the-real": "The problem isn't cost. The real problem is time.",
    "ait-a06-reversal-means": "This doesn't mean stop. It means slow down.",
    "ait-a07-chatbot-wrapper": "Great question about the renewal.",
    "ait-a07-chat-residue-long-form": "Certainly! The plan follows.",
    "ait-a08-summary-signpost": "Text here.\n\n## Conclusion\n",
    "ait-a09-em-dash": "It worked — mostly.",
    "ait-a09-double-hyphen": "It worked -- mostly.",
    "ait-a09-spaced-en-dash": "It worked – mostly.",
    "ait-a10-negation-countdown": "Not fast. Not cheap. Just late.",
    "ait-a11-throat-clearing": "In today's fast world, speed wins.",
    "ait-a12-pedagogical-run-up": "Let's dive in.",
    "ait-a13-false-suspense": "Here's the thing about backups.",
    "ait-a14-self-posed-question": "The result? Fewer alerts.",
    "ait-a15-worth-noting": "It's worth noting the date.",
    "ait-a16-promotional": "A true game changer for teams.",
    "ait-a17-authority-trope": "Make no mistake about the date.",
    "ait-a18-announced-candour": "To be honest, it failed.",
    "ait-a18-candour-adverb": "It ran. Frankly, it failed.",
    "ait-a19-vague-attribution": "Experts argue the date is wrong.",
    "ait-a20-despite-challenges": "Despite these challenges, it shipped.",
    "ait-a21-placeholder-residue": "Send it to [Your Name] today.",
    "ait-a22-formulaic-opener": "I hope this email finds you well.",
    "ait-a24-emoji-formatting": "## \U0001f680 Launch plan",
    "ait-a25-stock-pivot": "That being said, it shipped.",
    "ait-a26-colon-reveal": "The point is this: ship it.",
    "ait-a27-performed-hesitancy": "There are no easy answers here.",
    "ait-a28-performed-insight": "Let that sink in.",
    "ait-a28-call-it": "Don't call it a delay. Call it a reset.",
    "ait-a29-stock-metaphor": "It is a double-edged sword.",
    "ait-a30-quietly": "The change quietly spread.",
    "ait-a34-coined-label": "Beware the meeting trap.",
    "ait-a35-invented-aside": "I'll admit the first try failed.",
}
NEGATIVE = (
    "We moved the backup job to Tuesday. The restore test passed on 11 of 12 servers; "
    "the twelfth needs a reboot. Hope you are well. Feel free to call if needed."
)


class ExamplePackTests(unittest.TestCase):
    def test_pack_parses_and_every_entry_fires_on_its_synthetic_case(self):
        rules = load(EXAMPLE)
        ids = [ban["id"] for ban in rules["ban"]]
        self.assertEqual(sorted(POSITIVES), sorted(ids))
        for ban in rules["ban"]:
            with self.subTest(rule=ban["id"]):
                self.assertEqual("error", ban["severity"])
                self.assertTrue(set(ban["media"]) <= set(MEDIA))
                self.assertTrue(matches(POSITIVES[ban["id"]], ban["pattern"], ban["kind"]))
                self.assertFalse(matches(NEGATIVE, ban["pattern"], ban["kind"]))

    def test_case_sensitive_entries_and_dash_media(self):
        rules = {ban["id"]: ban for ban in load(EXAMPLE)["ban"]}
        lower = rules["ait-a05-this-highlights"]
        self.assertFalse(matches("costs fell. this highlights it.", lower["pattern"], "regex"))
        en_dash = rules["ait-a09-spaced-en-dash"]
        self.assertNotIn("email", en_dash["media"])
        self.assertIn("article", en_dash["media"])
        self.assertIn("email", rules["ait-a09-em-dash"]["media"])

    def test_pack_carries_no_owner_data(self):
        text = EXAMPLE.read_text()
        self.assertNotRegex(text, r"\bIan\b|per 1k|docs\)")
        self.assertEqual(1, len(re.findall(r"^```ownvoice-rules", text, re.MULTILINE)))


if __name__ == "__main__":
    unittest.main()
