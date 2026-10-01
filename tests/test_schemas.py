import importlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from ownvoice.errors import ValidationErrors
from ownvoice.io import PRIVATE_KEY

PROVENANCE = {
    "schema_version": 1,
    "tool_version": "0.0.1",
    "generated_at": "2026-09-25T00:00:00Z",
    "config_digest": "1" * 64,
    "domain_map_digest": "2" * 64,
    "rules_sha256": "3" * 64,
    "readers": {"corporate": {"reader": "pffexport", "reader_version": "20180714"}},
}
FINGERPRINT = {"size": 1000, "mtime_ns": 123456, "first_sha256": "4" * 64, "last_sha256": None}
STAGES = {"smtp": 1, "x500": 0, "names": 0, "unknown": 0}
METRIC = {
    "mean": 2.0,
    "p10": 0,
    "p25": 1,
    "p50": 2,
    "p75": 3,
    "p90": 4,
    "nonzero_share": 0.5,
    "lint_band": {"p10": 0, "p25": 1, "p75": 3, "p90": 4, "n_gated": 5, "fallback_global": False},
}
REGISTER = {
    "n": 5,
    "low_confidence": True,
    "derived_from": None,
    "metrics": {"sentence_len": METRIC},
    "dash_chars": {"em": 0, "en": 0},
    "greetings": [{"form": "Hi [NAME],", "count": 1, "share": 0.2}],
    "signoffs": [],
    "spelling": {"ise": 1, "ize": 0, "our": 0, "or": 0, "top_pairs": [["realise", 1]]},
    "function_words": {"the": 3.0},
    "ngrams": {"bi": [["let me", 5, 1.5]], "tri": []},
    "discourse_markers": {},
    "hedges": {},
    "llm_ism_never_hit": ["delve"],
    "never_hit_basis_words": 50000,
    "llm_ism_hits": [["robust", 1]],
    "by_thread_position": {key: {"n": 0, "metrics": {}} for key in ("new", "reply", "forward")},
}
FINDING = {
    "dimension": "tone",
    "register": "client",
    "observation": "Use direct sentences.",
    "verbatim_quote": "Please send the report.",
    "record_id": "a" * 16,
    "chunk_id": "a-1",
    "confidence": "high",
}
CONTRAST = {
    "register": "client",
    "metric": "sentence_len",
    "p50_by_source": {"corporate": 2},
    "iqr_merged": 1,
    "status": "diverging",
    "default_source": "corporate",
}


def samples():
    """Independent nonempty examples transcribed from the FRD contracts."""
    return {
        "article_records": {
            "record_id": "a" * 16,
            "source": "articles",
            "recipient_class": "article",
            "year": None,
            "word_count": 2,
            "text": "synthetic words",
            "truncated": False,
        },
        "cross_register": {
            "groups": [
                {
                    "group_id": "a" * 64,
                    "dimension": "tone",
                    "registers": ["article", "client"],
                    "finding_ids": ["a", "b"],
                    "quotes": [
                        {
                            "register": "article",
                            "record_id": "a" * 16,
                            "verbatim_quote": "synthetic words",
                        },
                        {
                            "register": "client",
                            "record_id": "b" * 16,
                            "verbatim_quote": "synthetic words",
                        },
                    ],
                }
            ]
        },
        "records": {
            "record_id": "a" * 16,
            "source": "corporate",
            "era": "2010-2019",
            "source_kind": "pst",
            "year": 2015,
            "weekday": 1,
            "hour_bucket": "morning",
            "recipient_class": "colleague",
            "recipient_count_bucket": "1",
            "recipient_stages": STAGES,
            "thread_position": "reply",
            "word_count": 5,
            "text": "Please send the report today.",
            "greeting": None,
            "signoff": None,
            "strip": {
                "body_source": "html",
                "rules_fired": ["H1"],
                "inline_reply": False,
                "confidence": "high",
                "flags": [],
            },
            "scrub": {
                "greeting_names": 0,
                "lexicon_names": 0,
                "emails": 0,
                "phones": 0,
                "urls": 0,
                "numbers": 0,
                "residual_capitalised": [],
            },
            "template": False,
            "sensitive": False,
        },
        "rejects": {
            "source_locator": "pst:mail.pst#Sent/1",
            "record_id": None,
            "reason": "non_mail_item",
            "detail": "select message [corporate/1]: sharing item; expected mail; next step: skip item",
        },
        "ingest_report": {
            **PROVENANCE,
            "source": "corporate",
            "kind": "pst",
            "reader": "pffexport",
            "reader_version": "20180714",
            "path_basename": "mail.pst",
            "fingerprint": FINGERPRINT,
            "status": "complete",
            "llm_eligible": False,
            "allow_inside_git_tree": False,
            "folders": [
                {"name": "Sent", "messages_seen": 1, "records": 1, "rejects": 0, "error": None}
            ],
            "skipped_folders": 0,
            "skipped_messages": 0,
            "extract": {"elapsed_s": 1.5, "dump_bytes": 2000},
            "messages_seen": 1,
            "selected": 1,
            "records_written": 1,
            "rejected_by_reason": {},
            "recipient_resolution": {"recipients": 1, **STAGES},
            "unmapped": {"domains": 0, "x500_orgs": 0, "names": 0},
            "low_confidence": 0,
            "low_confidence_excluded": 0,
            "templates": 0,
            "duplicates": 0,
            "sensitive": 0,
            "rules_fired_counts": {"H1": 1},
            "invariant": "seen == records + rejects",
        },
        "profile_stats": {
            "profiled_articles": {"file": "profiled-articles.jsonl", "sha256": "a" * 64},
            **PROVENANCE,
            "current_source": "corporate",
            "corpus": {
                "records": 5,
                "rejected": 0,
                "low_confidence_excluded": 0,
                "span_years": [2010, 2019],
                "per_register": {"client": 5},
                "sources": {
                    "corporate": {
                        "records": 5,
                        "era": "2010-2019",
                        "status": "complete",
                        "llm_eligible": False,
                    }
                },
            },
            "by_source": {"corporate": {"registers": {"client": REGISTER}}},
            "lexicons": {
                key: {"source": "builtin", "sha256": "5" * 64} for key in ("llm_ism", "sensitive")
            },
            "contrast": [CONTRAST],
            "registers": {"client": REGISTER},
            "time": {"by_year": {"2015": 5}, "by_weekday": {}, "by_hour_bucket": {}},
        },
        "stats_llm": {
            **PROVENANCE,
            "registers": {
                "client": {
                    "n": 5,
                    "low_confidence": True,
                    "derived_from": None,
                    "metrics": {"sentence_len": {"p25": 1, "p50": 2, "p75": 3}},
                    "spelling": {"ise": 1, "ize": 0, "our": 0, "or": 0},
                    "llm_ism_hits": [],
                }
            },
            "contrast": [CONTRAST],
        },
        "exemplars": {
            **PROVENANCE,
            "registers": {
                "client": {
                    "selection": {
                        "criterion": "hash-spaced within length tertiles",
                        "status": "ok",
                        "strata": [{"boundaries": [1, 10], "eligible": 1, "eligibility_rate": 1.0}],
                        "coverage": "partial",
                        "eligible": 1,
                        "selected": 1,
                        "words": 4,
                        "by_source": {"corporate": 1},
                    },
                    "items": [
                        {
                            "record_id": "a" * 16,
                            "source": "corporate",
                            "stratum": 0,
                            "pick_rank": 0,
                            "word_count": 4,
                            "thread_position": "reply",
                            "year": 2015,
                            "text": "Please send the report.",
                        }
                    ],
                }
            },
        },
        "edit_delta": {
            **PROVENANCE,
            "chains": [{"id": "draft", "versions": [{"sha256": "5" * 64}]}],
            "pairs": 1,
            "aggregate": {"sentence_len": {"before": 2, "after": 3, "delta": 1}},
            "operations": {"join": 1, "split": 0, "replace": 0, "insert": 0, "delete": 0},
            "substitutions": [{"before": "do not", "after": "don't", "count": 2}],
            "examples": [
                {"chain_id": "draft", "before": "do not", "after": "don't", "tags": ["contraction"]}
            ],
        },
        "lint": {
            **PROVENANCE,
            "draft": "draft.md",
            "register": "client",
            "medium": "email",
            "word_count": 4,
            "sentences": 1,
            "rate_checks_enabled": False,
            "findings": [
                {
                    "rule_id": "L1",
                    "check_kind": "structure",
                    "severity": "info",
                    "metric": None,
                    "observed": 4,
                    "expected": 80,
                    "locations": [{"line": 1, "col": 1, "excerpt": "Please"}],
                    "fix_hint": "Rate checks disabled",
                }
            ],
            "summary": {"error": 0, "warn": 0, "info": 1},
        },
        "manifest": {
            **PROVENANCE,
            "pass": "A",
            "max_tokens": 10000,
            "sample_words": 5000,
            "chunks": [
                {
                    "chunk_id": "a-1",
                    "pass": "A",
                    "source": "corporate",
                    "registers": ["client"],
                    "record_ids": ["a" * 16],
                    "est_tokens": 50,
                    "text_path": "a-1.txt",
                    "status": "pending",
                    "attempts": 0,
                }
            ],
        },
        "finding": FINDING,
        "findings_set": {
            **PROVENANCE,
            "findings": [
                {
                    "finding_id": "f-1",
                    "dimension": "tone",
                    "register": "client",
                    "observation": "Use direct sentences.",
                    "confidence": "high",
                    "provenance": [
                        {
                            "record_id": "a" * 16,
                            "chunk_id": "a-1",
                            "verbatim_quote": "Please send the report.",
                        }
                    ],
                }
            ],
            "changelog": [
                {"pass": "A", "finding_id": "f-1", "action": "new", "record_ids": ["a" * 16]}
            ],
            "passes": ["A"],
            "residual": 1,
            "unresolved_failed": 0,
        },
        "unmapped_domains": {
            **PROVENANCE,
            "domains": [{"domain": "example.net", "messages": 1}],
            "x500_orgs": [{"org": "Example", "messages": 1}],
            "unresolved_names": 2,
        },
        "checkpoint": {
            **PROVENANCE,
            "folder": "Sent",
            "message_index": 1,
            "records": 1,
            "rejects": 0,
        },
        "extract_stamp": {**PROVENANCE, "fingerprint": FINGERPRINT},
        "merge_state": {**PROVENANCE, "sources": {"corporate": "a" * 64}},
        "chains": {
            "schema_version": 1,
            "chain": [{"id": "draft", "origin": "llm", "versions": ["old.md", "new.md"]}],
        },
        "ac14": {
            "schema_version": 1,
            "brief": [
                {
                    "id": "brief-1",
                    "old_draft": "a.md",
                    "new_draft": "b.md",
                    "old_final": "c.md",
                    "new_final": "d.md",
                }
            ],
        },
    }


class SchemaTests(unittest.TestCase):
    def test_every_schema_build_missing_field_and_enum(self):
        for name, fields in samples().items():
            module = importlib.import_module("ownvoice.schemas." + name)
            with self.subTest(schema=name):
                obj = module.build(**deepcopy(fields))
                self.assertEqual(obj, module.validate(obj))
                if name not in ("chains", "ac14"):
                    self.assertEqual("private", obj[PRIVATE_KEY])
                for field, spec in module.SCHEMA.items():
                    if isinstance(spec, tuple) and spec[0] == "optional":
                        continue
                    altered = deepcopy(obj)
                    del altered[field]
                    with self.assertRaises(ValidationErrors) as caught:
                        module.validate(altered)
                    for text in (field, "validate artefact", "expected", "next step:"):
                        self.assertIn(text, str(caught.exception))
                enum_field = "schema_version" if "schema_version" in obj else PRIVATE_KEY
                altered = deepcopy(obj)
                altered[enum_field] = "wrong-enum"
                with self.assertRaisesRegex(ValidationErrors, enum_field):
                    module.validate(altered)

    def test_nested_mutations_and_projection_privacy(self):
        cases = [
            ("records", ("strip", "confidence"), "medium"),
            ("records", ("recipient_class",), "typo"),
            ("records", ("weekday",), True),
            ("rejects", ("reason",), "typo"),
            ("ingest_report", ("status",), "typo"),
            ("profile_stats", ("contrast", 0, "status"), "typo"),
            ("stats_llm", ("contrast", 0, "status"), "same"),
            ("exemplars", ("registers", "client", "selection", "coverage"), "typo"),
            ("edit_delta", ("examples", 0, "tags", 0), "typo"),
            ("lint", ("findings", 0, "severity"), "critical"),
            ("manifest", ("chunks", 0, "status"), "typo"),
            ("finding", ("confidence",), "typo"),
            ("findings_set", ("changelog", 0, "action"), "typo"),
            ("unmapped_domains", ("domains", 0, "messages"), -1),
            ("checkpoint", ("message_index",), -1),
            ("extract_stamp", ("fingerprint", "size"), -1),
            ("merge_state", ("sources",), {"corporate": "invalid-digest"}),
            ("chains", ("chain", 0, "origin"), "typo"),
            ("ac14", ("brief", 0, "old_draft"), 1),
        ]
        for name, keys, bad in cases:
            with self.subTest(schema=name, keys=keys):
                module = importlib.import_module("ownvoice.schemas." + name)
                obj = module.build(**deepcopy(samples()[name]))
                parent = obj
                for key in keys[:-1]:
                    parent = parent[key]
                parent[keys[-1]] = bad
                with self.assertRaises(ValidationErrors) as caught:
                    module.validate(obj)
                field = next(str(key) for key in reversed(keys) if isinstance(key, str))
                self.assertIn(field, str(caught.exception))
        from ownvoice.schemas import stats_llm

        obj = stats_llm.build(**deepcopy(samples()["stats_llm"]))
        obj["by_source"] = {}
        with self.assertRaisesRegex(ValidationErrors, "unknown field"):
            stats_llm.validate(obj)
        del obj["by_source"]
        obj["registers"]["misspelled-register"] = obj["registers"].pop("client")
        with self.assertRaisesRegex(ValidationErrors, "registers.*unknown register key"):
            stats_llm.validate(obj)

    def test_conservation_and_limits(self):
        from ownvoice.schemas import edit_delta, finding, ingest_report, unmapped_domains

        report = deepcopy(samples()["ingest_report"])
        report["messages_seen"] = 2
        with self.assertRaisesRegex(ValidationErrors, "messages_seen"):
            ingest_report.build(**report)
        merged = ingest_report.build_merged(
            **PROVENANCE,
            sources={"one": 3, "two": 2},
            merged_records=4,
            cross_source_duplicates=1,
            invariant="merged_records == sum source records - cross_source_duplicates",
        )
        self.assertEqual(merged, ingest_report.validate_merged(merged))
        quote = deepcopy(FINDING)
        quote["verbatim_quote"] = "word " * 26
        with self.assertRaisesRegex(ValidationErrors, "verbatim_quote"):
            finding.build(**quote)
        delta = deepcopy(samples()["edit_delta"])
        delta["examples"][0]["before"] = "word " * 61
        with self.assertRaisesRegex(ValidationErrors, "before"):
            edit_delta.build(**delta)
        unmapped = deepcopy(samples()["unmapped_domains"])
        unmapped["x500_orgs"][0]["org"] = "Example/OU=private"
        with self.assertRaisesRegex(ValidationErrors, "org"):
            unmapped_domains.build(**unmapped)

    def test_manifest_loaders_and_all_boundary_errors(self):
        from ownvoice.schemas import ac14, chains

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "chains.toml"
            path.write_text(
                'schema_version = 1\n[[chain]]\nid="example"\norigin="owner"\ngit={repo="~/repo",path="draft.md",follow=true}\n'
            )
            self.assertEqual("owner", chains.load(path)["chain"][0]["origin"])
            path.write_text(
                '[[brief]]\nid="one"\nold_draft="a"\nnew_draft="b"\nold_final="c"\nnew_final="d"\n'
            )
            self.assertEqual("one", ac14.load(path)["brief"][0]["id"])
        with self.assertRaises(ValidationErrors) as caught:
            chains.build(schema_version=1, chain=[{"id": "", "origin": "llm", "versions": []}])
        self.assertEqual(2, len(caught.exception.errors))
        with self.assertRaisesRegex(ValidationErrors, "exactly one"):
            chains.build(schema_version=1, chain=[{"id": "one", "origin": "llm"}])
        with self.assertRaisesRegex(ValidationErrors, "old_draft"):
            ac14.build(
                brief=[
                    {
                        "id": "one",
                        "old_draft": "",
                        "new_draft": "b",
                        "old_final": "c",
                        "new_final": "d",
                    }
                ]
            )

    def test_names_text_contract(self):
        from ownvoice.schemas import names

        value = names.build(["Synthetic Name"])
        self.assertEqual(value, names.validate(value))
        with self.assertRaisesRegex(ValidationErrors, "names.marker"):
            names.validate("Synthetic Name\n")
        with self.assertRaisesRegex(ValidationErrors, "names.lines"):
            names.validate(value.rstrip())

    def test_source_identity_counts_are_complete_but_merged_summary_is_bounded(self):
        from ownvoice.schemas import unmapped_domains

        fields = deepcopy(samples()["unmapped_domains"])
        fields["domains"] = [{"domain": f"d{i}.example", "messages": i} for i in range(60)]
        unmapped_domains.validate(unmapped_domains.build(**fields, source="corporate"))
        with self.assertRaisesRegex(ValidationErrors, "domains.*50"):
            unmapped_domains.build(**fields)
