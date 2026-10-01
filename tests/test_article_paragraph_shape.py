"""Article paragraph shape: fragmentation limits replace the email paragraph_len band.

Synthetic fixtures only: no corpus text, drafts or names from any owner.
"""

import unittest

from ownvoice.style import tells
from ownvoice.style.lint import ARTICLE_SHAPE_SKIPPED, check
from tests import test_ai_tells, test_profile

SENTENCE = test_ai_tells.SENTENCE
ONE = SENTENCE
THREE = " ".join([SENTENCE] * 3)


class ParagraphShapeTests(unittest.TestCase):
    def test_too_few_paragraphs_is_not_measured(self):
        self.assertIsNone(tells.paragraph_shape("\n\n".join([THREE] * 3)))

    def test_mean_and_single_sentence_share(self):
        self.assertEqual((3, 0), tells.paragraph_shape("\n\n".join([THREE] * 4)))
        average, single = tells.paragraph_shape("\n\n".join([THREE] * 4 + [ONE]))
        self.assertEqual(0.2, single)
        self.assertEqual(2.6, round(average, 4))

    def test_headings_and_bullets_are_not_paragraphs(self):
        text = "## Heading\n\n" + "\n\n".join([ONE] * 4) + "\n\n- one item\n- two item"
        self.assertEqual((1, 1), tells.paragraph_shape(text))


class ArticleLintTests(unittest.TestCase):
    # Reuse fixture builders, not ProfileLintTests inheritance (which would rerun its suite).
    setUp = test_profile.ProfileTests.setUp
    configure = test_profile.ProfileTests.configure
    row = test_profile.ProfileTests.row
    inputs = test_profile.ProfileTests.inputs
    cli = test_profile.ProfileTests.cli
    outputs = test_profile.ProfileTests.outputs
    corpus = test_ai_tells.ProfileLintTests.corpus
    profile = test_ai_tells.ProfileLintTests.profile

    def ids(self, stats, text, register="article", medium="article"):
        return {f["rule_id"] for f in check(text, stats, {}, register, medium, minimum=2)[3]}

    def test_fragmented_article_warns_and_dense_article_passes(self):
        stats, _ = self.profile(self.corpus())
        dense = "# Heading\n\n" + "\n\n".join([THREE] * 5)
        fragmented = "# Heading\n\n" + "\n\n".join([ONE] * 6 + [THREE] * 2)
        self.assertNotIn("structure.paragraph_fragmentation", self.ids(stats, dense))
        self.assertIn("structure.paragraph_fragmentation", self.ids(stats, fragmented))
        # A list after dense prose is not fragmentation.
        listed = dense + "\n\n- one item\n- two item\n- three item"
        self.assertNotIn("structure.paragraph_fragmentation", self.ids(stats, listed))

    def test_email_paragraph_band_is_not_compared_for_articles(self):
        self.assertIn("paragraph_len", ARTICLE_SHAPE_SKIPPED)
        stats, _ = self.profile(self.corpus())
        dense = "# Heading\n\n" + "\n\n".join([THREE] * 5)
        self.assertNotIn("stats.paragraph_len", self.ids(stats, dense))

    def test_email_drafts_are_unaffected(self):
        stats, _ = self.profile(self.corpus())
        fragmented = "\n\n".join([ONE] * 6 + [THREE] * 2)
        self.assertNotIn(
            "structure.paragraph_fragmentation", self.ids(stats, fragmented, "client", "email")
        )


if __name__ == "__main__":
    unittest.main()
