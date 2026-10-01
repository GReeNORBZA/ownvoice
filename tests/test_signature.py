import unittest

from ownvoice.config import DEFAULTS
from ownvoice.extract import greeting, signature


class SignatureTests(unittest.TestCase):
    def test_F14_F44_window_learning_and_negatives(self):
        valedictions = DEFAULTS["ingest"]["valedictions"]
        body = "Please review this.\nRegards,\nOwner\nSenior Consultant\nPrivate Company"
        rows = [{"source": "one", "year": 2025, "text": body} for _ in range(12)]
        rows += [{"source": "one", "year": 2026, "text": body}]
        rows += [{"source": "two", "year": 2025, "text": body}]
        rows += [
            {"source": "one", "year": 2024, "text": "Please keep this owner sentence."}
            for _ in range(15)
        ]
        lexicons = signature.learn(rows, ["Owner"], valedictions)
        self.assertEqual({"Senior Consultant", "Private Company"}, lexicons["one", 2025])
        for window in (("one", 2026), ("two", 2025), ("one", 2024)):
            self.assertEqual(set(), lexicons[window])
        # Repeated prose after an anchor is not a signature, even with another line.
        for row in rows:
            row["text"] = (
                "Thanks\nPlease keep this owner sentence.\nPlease keep this other sentence."
            )
        self.assertTrue(
            all(not value for value in signature.learn(rows, ["Owner"], valedictions).values())
        )

    def test_learning_requires_cooccurrence_and_frequency(self):
        vals = DEFAULTS["ingest"]["valedictions"]
        rows = [
            {
                "source": "one",
                "year": 2025,
                "text": f"Reply\nThanks\nCommon Title\nDifferent Company {i}",
            }
            for i in range(12)
        ]
        self.assertEqual(set(), signature.learn(rows, ["Owner"], vals)["one", 2025])
        rows = [
            {"source": "one", "year": 2025, "text": "Thanks\nSame Title\nSame Company"}
            for _ in range(10)
        ]
        rows += [{"source": "one", "year": 2025, "text": "Unrelated body"} for _ in range(191)]
        self.assertEqual(set(), signature.learn(rows, ["Owner"], vals)["one", 2025])

    def test_sig_dash_valediction_metrics_and_contact_suffix(self):
        vals = DEFAULTS["ingest"]["valedictions"]
        text = "Hi [NAME],\nCan you send it?\nThanks!\nOwner\n-- \nPrivate contact"
        kept, signoff, rules = signature.strip(text, ["Owner"], vals)
        self.assertEqual("Hi [NAME],\nCan you send it?\nThanks!\nOwner", kept)
        self.assertEqual("thanks", signoff)
        self.assertEqual(["sig-dash"], rules)
        self.assertEqual(
            "Can you send it?", greeting.metric_text(kept, "Hi [NAME],", signoff, ["Owner"])
        )
        text = "Please reply.\nThanks\nOwner\nKnown Title\n+1 780 555 1234"
        kept, signoff, rules = signature.strip(text, ["Owner"], vals, {"Known Title"})
        self.assertEqual("Please reply.\nThanks\nOwner", kept)
        self.assertEqual("thanks", signoff)
        self.assertEqual(["signature-fingerprint"], rules)
