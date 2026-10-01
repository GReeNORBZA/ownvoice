import math
import unittest
from unittest.mock import patch

from ownvoice.errors import DiagnosticError
from ownvoice.style.metrics import METRIC_IDS, distribution, measure
from ownvoice.style.ngrams import counts, keyness, ranked
from ownvoice.style.tables import frequencies
from ownvoice.style.tokenize import lexicon, sentences, words


class MetricTests(unittest.TestCase):
    def test_list_items_preserve_sentence_boundaries_and_metrics(self):
        for marker in ("-", "*", "+", "1.", "12."):
            for ending in (".", "?", "!"):
                with self.subTest(marker=marker, ending=ending):
                    item = "Could you possibly go? Stop! Go (now)" + ending
                    text = f"{marker} {item}\n{marker} The cat sat. Go now."
                    self.assertEqual([item, "The cat sat. Go now."], sentences(text))
                    values = measure(text)
                    expected = {
                        "words": 12,
                        "sentence_len": 6,
                        "paragraph_len": 2,
                        "question_softener_rate": 50 if ending == "?" else 0,
                        "question_rate": 50 if ending == "?" else 0,
                        "exclamation_rate": 50 if ending == "!" else 0,
                        "parenthetical_rate": 50,
                        "flesch_reading_ease": 206.835 - 1.015 * 6 - 84.6 * 14 / 12,
                    }
                    for metric, value in expected.items():
                        self.assertAlmostEqual(value, values[metric], msg=metric)

    def test_mixed_prose_lists_and_abbreviations(self):
        text = (
            "Dr. Smith paid 2.50. Go now!\n\n"
            "- Dr. Smith left. Come back!\n"
            "* First sentence. Second sentence.\n\n"
            "first line\ncontinues here. Next sentence?"
        )
        self.assertEqual(
            [
                "Dr. Smith paid 2.50.",
                "Go now!",
                "Dr. Smith left. Come back!",
                "First sentence. Second sentence.",
                "first line continues here.",
                "Next sentence?",
            ],
            sentences(text),
        )

    def test_every_metric_on_fresh_known_sentence(self):
        expected = dict.fromkeys(METRIC_IDS, 0)
        expected.update(
            words=6,
            sentence_len=6,
            paragraph_len=1,
            paragraphs=1,
            flesch_reading_ease=206.835 - 1.015 * 6 - 84.6,
        )
        self.assertEqual(expected, measure("The cat sat on the mat."))

    def test_apostrophes_masks_and_contractions(self):
        text = "I’m you’re weʼve they\x92ll don’t it's that's."
        self.assertEqual(7, measure(text)["words"])
        self.assertEqual(100, measure(text)["contraction_rate"])
        self.assertEqual(["[NAME]", "sent", "[NUM]"], words("[NAME] sent [NUM]."))
        self.assertEqual(0, measure("The cat's coat.")["contraction_rate"])

    def test_structure_exclusion_and_line_boundaries(self):
        result = measure(
            "Hi [NAME],\nCan you send it?\n\nKind regards,\nOwner", owner_names=["Owner"]
        )
        self.assertEqual(4, result["words"])
        self.assertEqual(4, result["sentence_len"])
        self.assertEqual(0, result["question_softener_rate"])
        self.assertEqual(1, result["greeting_share"])
        self.assertEqual(1, result["signoff_share"])
        self.assertEqual(["first line", "Second line"], sentences("first line\nSecond line"))
        self.assertEqual(["first line continues here"], sentences("first line\ncontinues here"))
        self.assertEqual(
            ["Dr. Smith paid 2.50.", "Go now!"], sentences("Dr. Smith paid 2.50. Go now!")
        )

    def test_questions_exclamations_and_per_email_means(self):
        result = measure("Could you possibly send it? Can you send it? Go!")
        self.assertEqual(10, result["words"])
        self.assertEqual(10 / 3, result["sentence_len"])
        self.assertEqual(100 / 3, result["question_softener_rate"])
        self.assertEqual(200 / 3, result["question_rate"])
        self.assertEqual(100 / 3, result["exclamation_rate"])
        self.assertEqual(1, result["exclamations_per_email"])
        self.assertEqual(0, measure("Could you possibly send it.")["question_softener_rate"])
        self.assertEqual(
            100,
            measure("Would you kindly send it?", softeners=["would you kindly"])[
                "question_softener_rate"
            ],
        )

    def test_punctuation_lists_headings_and_paragraphs(self):
        result = measure("one - two (three)...\n\nfour – five — six…")
        self.assertEqual(6, result["words"])
        self.assertEqual(2, result["paragraphs"])
        self.assertEqual(1, result["paragraph_len"])
        self.assertEqual(50, result["parenthetical_rate"])
        self.assertEqual(2000 / 6, result["ellipsis_rate"])
        self.assertEqual(500, result["spaced_dash_rate"])
        listed = measure("- one\n1. two")
        self.assertEqual(1, listed["list_use"])
        self.assertEqual(1, listed["sentence_len"])
        self.assertEqual(0, listed["spaced_dash_rate"])
        self.assertEqual(1, measure("# Heading\nText.")["heading_use"])
        self.assertEqual(1, measure("**Heading**\nText.")["heading_use"])
        self.assertEqual(0, measure("Some **bold** text.")["heading_use"])

    def test_pronouns_emoji_and_silent_e(self):
        result = measure("I me my mine you your yours.")
        self.assertEqual(400 / 7, result["first_person_rate"])
        self.assertEqual(300 / 7, result["second_person_rate"])
        self.assertEqual(5, measure("Fine 😀 :) ;) :-) :D")["emoji_rate"])
        self.assertEqual(
            206.835 - 1.015 * 3 - 84.6, measure("We make cake.")["flesch_reading_ease"]
        )

    def test_heading_representations_and_body_source(self):
        for text in (
            "# Update",
            "###### Update",
            "**Update**",
            "__Update__",
            "Update\n======",
            "Update\n------",
            "Update\n=",
            "Update\n-",
            "Update\r\n------",
            "  __Update__  ",
        ):
            with self.subTest(text=text):
                self.assertEqual(1, measure(text)["heading_use"])
        for text in (
            "*Update*",
            "_Update_",
            "Some **bold** text.",
            "Some __bold__ text.",
            "---",
            "===",
            "---\n---",
            "Update\n\n---",
            "- item\n---",
            "#hashtag",
            "####### Update",
        ):
            with self.subTest(text=text):
                self.assertEqual(0, measure(text)["heading_use"])
        self.assertEqual(1, measure("*Update*", body_source="html")["heading_use"])
        self.assertEqual(0, measure("Some *bold* text.", body_source="html")["heading_use"])

    def test_distributions_are_per_email_and_bands_gated(self):
        result = distribution([0, 10], [10], True)
        self.assertEqual(
            {
                "mean": 5,
                "p10": 1,
                "p25": 2.5,
                "p50": 5,
                "p75": 7.5,
                "p90": 9,
                "nonzero_share": 0.5,
                "lint_band": {
                    "p10": 10,
                    "p25": 10,
                    "p75": 10,
                    "p90": 10,
                    "n_gated": 1,
                    "fallback_global": True,
                },
            },
            result,
        )

    def test_keyness_and_function_mask_capital_filters(self):
        self.assertAlmostEqual(20 * math.log(2), keyness(5, 5, 0, 5))
        self.assertEqual({}, counts([{"text": "the and [NAME] [NUM]"}], 2))
        self.assertEqual({}, counts([{"text": "Zyxora sent"}], 2))
        rows = [{"text": "bright moon"}] * 5
        other = [{"text": "dark sky"}] * 5
        self.assertEqual([["bright moon", 5, 20 * math.log(2)]], ranked(rows, other)["bi"])
        self.assertEqual([], ranked(rows[:4], other)["bi"])

    def test_frequency_tables_and_dash_rates(self):
        row = {
            "text": "realise realize colour color i think — however – delve",
            "greeting": "Hi team,",
            "signoff": "regards",
        }
        result = frequencies([row], [row], ["delve", "robust"])
        self.assertEqual(
            {"ise": 1, "ize": 1, "our": 1, "or": 1},
            {k: result["spelling"][k] for k in ("ise", "ize", "our", "or")},
        )
        self.assertEqual({"em": 125, "en": 125}, result["dash_chars"])
        self.assertEqual(125, result["function_words"]["i"])
        self.assertEqual(125, result["hedges"]["i think"])
        self.assertEqual(125, result["discourse_markers"]["however"])
        self.assertEqual([["delve", 1]], result["llm_ism_hits"])
        self.assertEqual(["robust"], result["llm_ism_never_hit"])
        self.assertEqual(8, result["never_hit_basis_words"])
        self.assertEqual([{"form": "Hi team,", "count": 1, "share": 1}], result["greetings"])
        self.assertEqual([{"form": "regards", "count": 1, "share": 1}], result["signoffs"])

    def test_bundled_lexicon_diagnostic_preserves_cause(self):
        cause = OSError("synthetic read failure")
        with (
            patch("pathlib.Path.read_text", side_effect=cause),
            self.assertRaises(DiagnosticError) as caught,
        ):
            lexicon("missing-test-lexicon.txt")
        self.assertIs(cause, caught.exception.__cause__)
        for part in (
            "read bundled style lexicon",
            "missing-test-lexicon.txt",
            "synthetic read failure",
            "next step:",
        ):
            self.assertIn(part, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
