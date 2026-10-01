import unittest

from ownvoice.config import DEFAULT_READER, validate_domain_map
from ownvoice.message import Message, Recipient
from ownvoice.readers.recipients import resolve


class RecipientCascadeTests(unittest.TestCase):
    def test_default_DD17(self):
        # Both PST readers were measured during design; pypff exposes no recipient table.
        self.assertEqual("pffexport", DEFAULT_READER)

    def test_F50_first_mapping_fallthrough_and_org_only(self):
        mapping = validate_domain_map(
            {
                "schema_version": 1,
                "addresses": {"first@sub.domain.example": "personal"},
                "domains": {"domain.example": "client", "sub.domain.example": "vendor"},
                "x500": {"ExAmPlEcOrP": "colleague"},
                "names": {"Known": "professional-warm"},
            }
        )
        message = Message(
            "synthetic",
            [
                Recipient("first@sub.domain.example", "Known", "to"),
                Recipient("second@sub.domain.example", "Known", "to"),
                Recipient("third@fallback.example", "Known", "to"),
                Recipient("/o=examplecorp/OU=Secret/CN=Hidden", "Known", "cc"),
                Recipient("/O=UnknownCorp/OU=Secret/CN=Hidden", "", "cc"),
                Recipient(None, "Unresolved", "bcc"),
                Recipient("last@unknown.example", "", "to"),
            ],
        )
        category, bucket, stages, domains, names, orgs = resolve(message, mapping)
        self.assertEqual(("group", "4+"), (category, bucket))
        self.assertEqual({"smtp": 2, "x500": 1, "names": 1, "unknown": 3}, stages)
        self.assertEqual(7, sum(stages.values()))
        self.assertEqual({"unknowncorp"}, orgs)
        self.assertEqual({"unknown.example"}, domains)
        self.assertEqual({"unresolved"}, names)
