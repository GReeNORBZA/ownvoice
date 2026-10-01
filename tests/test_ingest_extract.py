import copy
import json
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path

from ownvoice.config import DEFAULTS, validate_domain_map
from ownvoice.extract import classify
from ownvoice.extract.body import Rejected, extract, word_count
from ownvoice.ingest.run import record_id
from ownvoice.readers.eml import parse

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


def cases():
    return [
        json.loads(p.read_text())
        for p in sorted(FIXTURES.glob("*/case.json"))
        if p.parent.name not in ("F27", "F31")
    ]


def raw_message(case):
    message = EmailMessage(policy=policy.default)
    message["From"] = case.get("sender", "owner@example.com")
    message["To"] = "Other <other@example.net>"
    message["Subject"] = case.get("subject", "New topic")
    message["Message-ID"] = "<" + case["id"] + "@example.com>"
    if not case.get("missing_date"):
        message["Date"] = "Tue, 20 Jan 2026 01:30:00 +0000"
    if case.get("labels"):
        message["X-Gmail-Labels"] = case["labels"]
    if case.get("mime"):
        message.set_content(case["body"], subtype="calendar")
    elif case.get("nested_calendar"):
        message.set_content("Owner note.")
        message.add_alternative(case["body"], subtype="calendar")
    else:
        message.set_content(case["body"], subtype="html" if case["html"] else "plain")
    if case.get("bad_bytes") or case.get("latin"):
        body = (
            case["body"].encode("cp1252")
            if case.get("latin")
            else case["body"].replace("\ufffd", "\x00").encode().replace(b"\x00", b"\xff")
        )
        message.replace_header(
            "Content-Type",
            "text/plain; charset=" + ("iso-8859-1" if case.get("latin") else "utf-8"),
        )
        message.replace_header("Content-Transfer-Encoding", "8bit")
        message.set_payload(body)
    return message.as_bytes()


class ExtractionTests(unittest.TestCase):
    def test_inline_cue_matches_only_kept_owner_lines(self):
        cue = "See my comments below in red."
        for rule, cut in (
            ("T1", "-----Original Message-----"),
            ("T4", "From: Earlier sender\nSent: Earlier date\nTo: Recipient"),
        ):
            for location in ("quoted", "footer", "owner"):
                with self.subTest(rule=rule, location=location):
                    config = copy.deepcopy(DEFAULTS["ingest"])
                    config["mobile_footers"] = [cue] if location == "footer" else []
                    cue_line = "> " + cue if location == "quoted" else cue
                    message = EmailMessage()
                    message.set_content(f"Owner note.\n{cue_line}\n{cut}\nEarlier unquoted body.")
                    text, strip = extract(message, config)
                    self.assertEqual(
                        "Owner note." + ("\n" + cue if location == "owner" else ""), text
                    )
                    self.assertEqual(
                        [rule] + (["mobile-footer"] if location == "footer" else []),
                        strip["rules_fired"],
                    )
                    self.assertEqual(
                        ["inline_suspected"] if location == "owner" else [], strip["flags"]
                    )
                    self.assertEqual("low" if location == "owner" else "high", strip["confidence"])
                    self.assertEqual(location == "quoted", strip["inline_reply"])

    def test_F51_inline_cue_contract(self):
        for path in sorted(FIXTURES.glob("F51*/case.json")):
            case = json.loads(path.read_text())
            with self.subTest(fixture=case["id"]):
                _, mail = parse(raw_message(case), "eml:synthetic#messages/0")
                text, strip = extract(mail, DEFAULTS["ingest"])
                self.assertEqual(case["expected"], text)
                self.assertEqual(case["rules"], strip["rules_fired"])
                self.assertEqual(case["flags"], strip["flags"])
                self.assertEqual(case["confidence"], strip["confidence"])
                self.assertFalse(strip["inline_reply"])

    def test_html_bold_format_and_outlook_header_cut_remain_compatible(self):
        for tag in ("b", "strong"):
            with self.subTest(tag=tag):
                message = EmailMessage()
                message.set_content(
                    f"<p><{tag}>Update</{tag}></p><p>Owner note.</p>"
                    f"<p><{tag}>From:</{tag}> Other</p>"
                    f"<p><{tag}>To:</{tag}> Owner</p>"
                    f"<p><{tag}>Subject:</{tag}> Earlier</p><p>&gt; Quoted body.</p>",
                    subtype="html",
                )
                text, strip = extract(message, DEFAULTS["ingest"])
                self.assertEqual("*Update*\nOwner note.", text)
                self.assertEqual("html", strip["body_source"])
                self.assertEqual(["T4"], strip["rules_fired"])
                self.assertEqual("high", strip["confidence"])

    def test_fixture_exact_outputs(self):
        for case in cases():
            with self.subTest(fixture=case["id"]):
                config = copy.deepcopy(DEFAULTS["ingest"])
                config["extra_attribution_patterns"] = case.get("patterns", [])
                message, mail = parse(raw_message(case), "eml:synthetic#messages/0")
                # Selection fixtures are exercised through the real CLI as well.
                if case["reason"] == "excluded_label":
                    continue
                if case["reason"]:
                    with self.assertRaises(Rejected) as error:
                        extract(mail, config, mboxrd=case.get("mboxrd", False))
                    self.assertEqual(case["reason"], error.exception.reason)
                    continue
                text, strip = extract(mail, config, mboxrd=case.get("mboxrd", False))
                self.assertEqual(case["expected"], text)
                self.assertEqual(case["rules"], strip["rules_fired"])
                self.assertEqual(case["confidence"], strip["confidence"])
                self.assertEqual(
                    case["thread"], classify.thread_position(message, strip["rules_fired"], config)
                )
                self.assertEqual(case.get("inline", False), strip["inline_reply"])
                if case.get("bad_bytes"):
                    self.assertIn("decode_error_partial", strip["flags"])
                if case.get("missing_date"):
                    self.assertEqual(
                        (None, None, None), classify.date_fields(message, {"timezone": "UTC"})
                    )

    def test_mismatch_cap_mime_and_decode_rejections(self):
        message = EmailMessage()
        message.set_content(" ".join(["plain"] * 40))
        message.add_alternative("<p>" + " ".join(["html"] * 12) + "</p>", subtype="html")
        text, strip = extract(message, DEFAULTS["ingest"])
        self.assertEqual(" ".join(["html"] * 12), text)
        self.assertIn("body_mismatch", strip["flags"])
        self.assertEqual("low", strip["confidence"])
        message = EmailMessage()
        message.set_content("word " * 3001)
        self.assertIn("long_body", extract(message, DEFAULTS["ingest"])[1]["flags"])
        for kind, reason in [
            ("application/pkcs7-mime", "encrypted"),
            ("application/octet-stream", "no_text_body"),
            ("multipart/report", "non_mail_item"),
        ]:
            message = EmailMessage()
            message["Content-Type"] = kind
            with self.assertRaises(Rejected) as caught:
                extract(message, DEFAULTS["ingest"])
            self.assertEqual(reason, caught.exception.reason)
        message = EmailMessage()
        message.set_content("unknown charset text")
        message.replace_header("Content-Type", "text/plain; charset=not-a-codec")
        with self.assertRaises(Rejected) as caught:
            extract(message, DEFAULTS["ingest"])
        self.assertIsInstance(caught.exception.__cause__, LookupError)
        self.assertEqual("decode_error", caught.exception.reason)
        self.assertEqual(3, word_count("don't count 123 twice"))

    def test_classification_dates_ids(self):
        raw = b"From: owner@example.com\nTo: Friend <friend@sub.client.example>, Named <fallback@other.example>\nBcc: Cold <cold@example.org>\nDate: Tue, 20 Jan 2026 01:30:00 +0000\nIn-Reply-To: <parent>\n\nOwner note."
        message, _ = parse(raw, "eml:source#messages/0")
        domain_map = validate_domain_map(
            {
                "schema_version": 1,
                "domains": {"client.example": "vendor", "sub.client.example": "client"},
                "addresses": {"cold@example.org": "cold"},
                "names": {"Named": "personal"},
            }
        )
        result = classify.recipients(message, domain_map)
        self.assertEqual(
            ("cold", "2-3", {"smtp": 2, "x500": 0, "names": 1, "unknown": 0}), result[:3]
        )
        domain_map["group_threshold"] = 3
        self.assertEqual("group", classify.recipients(message, domain_map)[0])
        source = {"label": "one", "timezone": "America/Edmonton"}
        self.assertEqual((2026, 0, "evening"), classify.date_fields(message, source))
        self.assertEqual("reply", classify.thread_position(message, [], DEFAULTS["ingest"]))
        first = record_id(message, source, "Owner note.")
        message.source_locator = "eml:source#messages/1"
        self.assertNotEqual(first, record_id(message, source, "Owner note."))
        message.message_id = "<fixed@example.com>"
        self.assertEqual(record_id(message, source), record_id(message, {"label": "two"}))
        message.subject = "Fwd: topic"
        self.assertEqual("forward", classify.thread_position(message, [], DEFAULTS["ingest"]))
