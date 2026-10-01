import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ownvoice.style.rules_block import load

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "skills" / "editorial-rules"
HEADINGS = (
    "Voice and register",
    "Publishing tiers",
    "Open-source release gate",
    "Images and diagrams",
    "Process",
    "Inferred, unconfirmed",
)


class EditorialRulesTests(unittest.TestCase):
    def test_files_parse_and_headings(self):
        for name in ("editorial-rules.md", "editorial-rules.TEMPLATE.md"):
            with self.subTest(name=name):
                path = RULES / name
                text = path.read_text()
                self.assertTrue(text.startswith("# Editorial rules\n"))
                for heading in HEADINGS:
                    self.assertIn("## " + heading, text.splitlines())
                parsed = load(path)
                self.assertEqual(parsed["schema_version"], 1)
                if "TEMPLATE" in name:
                    self.assertEqual(parsed, {"schema_version": 1})
        owner = load(RULES / "editorial-rules.md")
        self.assertEqual(owner["limits"]["email"]["exclamations_max"], 1)
        self.assertFalse(owner["limits"]["email"]["headings_allowed"])
        self.assertEqual(owner["limits"]["email"]["registers"]["personal"]["emoji_max"], 1)

    def test_inferred_is_prose_only_and_release_gate_has_eight_conditions(self):
        text = (RULES / "editorial-rules.md").read_text()
        inferred = text.split("## Inferred, unconfirmed\n", 1)[1].split("\n## ", 1)[0]
        block = text.split("```ownvoice-rules\n", 1)[1].split("```", 1)[0]
        self.assertNotIn("```", inferred)
        for entry in re.findall(r"^- (.+)$", inferred, re.MULTILINE):
            self.assertNotIn(entry, block)
        gate = text.split("## Open-source release gate\n")[1].split("\n## ")[0]
        self.assertEqual(re.findall(r"^(\d)\. ", gate, re.MULTILINE), list("12345678"))

    def test_release_boundary(self):
        # The real correspondent lexicon is supplied privately during card validation.
        # Public tests carry only synthetic identities, never the private lexicon.
        with tempfile.TemporaryDirectory() as temporary:
            names = Path(temporary) / "names.txt"
            names.write_text("Synthetic Correspondent\n")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ownvoice",
                    "guard",
                    "--tree",
                    str(RULES),
                    "--release",
                    "--names-file",
                    str(names),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
