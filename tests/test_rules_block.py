import unittest

from ownvoice.errors import DiagnosticError, ValidationErrors
from ownvoice.style.rules_block import load, parse


def block(toml):
    return "# Editorial rules\n\n```ownvoice-rules\n" + toml + "\n```\n"


class RulesTests(unittest.TestCase):
    def test_template_and_all_errors(self):
        self.assertEqual({"schema_version": 1}, parse(block("schema_version = 1")))
        text = block("""schema_version = 9
spelling = "invalid"
[[ban]]
id = "broken"
kind = "regex"
pattern = "["
media = ["paper"]
severity = "fatal"
[limits.email]
emoji_max = -1
headings_allowed = 2
[swearing]
never = 42
""")
        with self.assertRaises(ValidationErrors) as caught:
            parse(text, "rules.md")
        message = str(caught.exception)
        for field in (
            "schema_version",
            "spelling",
            "pattern",
            "media",
            "severity",
            "message",
            "emoji_max",
            "headings_allowed",
            "never",
        ):
            self.assertIn(field, message)
        self.assertTrue(any(e.__cause__ for e in caught.exception.errors))
        for error in caught.exception.errors:
            for part in ("validate editorial rules", "rules.md:", "expected", "next step:"):
                self.assertIn(part, str(error))

    def test_boundaries(self):
        for text in (
            "no block",
            block("schema_version = 1") * 2,
            block("["),
            block("schema_version = true"),
            block("schema_version = 1\nban = 3"),
            block("schema_version = 1\nlimits = 3"),
            block("schema_version = 1\nswearing = 3"),
            block("schema_version = 1\nunknown = 3"),
        ):
            with self.subTest(text=text), self.assertRaises(ValidationErrors) as caught:
                parse(text, "bad.md")
            self.assertIn("bad.md", str(caught.exception))
            self.assertIn("next step:", str(caught.exception))
        with self.assertRaises(DiagnosticError) as caught:
            load("/nonexistent/c9-rules.md")
        self.assertIn("read editorial rules", str(caught.exception))
        self.assertIn("c9-rules.md", str(caught.exception))
        self.assertIsNotNone(caught.exception.__cause__)
