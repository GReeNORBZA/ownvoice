import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from ownvoice.config import (
    llm_completeness,
    load_config,
    read_toml,
    validate_config,
    validate_domain_map,
)
from ownvoice.errors import ValidationErrors
from ownvoice.provenance import build as provenance
from ownvoice.provenance import config_digest, file_sha256

CONFIG = """schema_version = 1
[owner]
addresses = ["owner@example.com"]
names = ["Ada"]
timezone = "America/Edmonton"
[paths]
work_dir = "work"
domain_map = "domain-map.toml"
editorial_rules = "rules.md"
[[source]]
label = "corporate"
kind = "pst"
path = "mail.pst"
owner_addresses = ["alias@example.org"]
llm_eligible = false
[llm]
"""


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.toml"
        self.path.write_text(CONFIG)
        (self.root / "domain-map.toml").write_text(
            'schema_version = 1\n[addresses]\n"friend@example.net" = "personal"\n'
        )
        (self.root / "rules.md").write_text("Editorial rules\n")

    def run_config(self, text=CONFIG):
        self.path.write_text(text)
        return subprocess.run(
            [sys.executable, "-m", "ownvoice", "config", "show", "--format", "json"],
            env={**os.environ, "OWNVOICE_CONFIG": str(self.path)},
            check=False,
            capture_output=True,
            text=True,
        )

    def test_three_errors_exactly_with_lines(self):
        text = (
            CONFIG.replace("America/Edmonton", "America/Edmontn")
            .replace('label = "corporate"', 'label = "BAD LABEL"')
            .replace("llm_eligible = false", "llm_eligible = true")
        )
        result = self.run_config(text)
        self.assertEqual(2, result.returncode)
        lines = result.stderr.splitlines()
        self.assertEqual(3, len(lines), result.stderr)
        for message, key, line in zip(
            lines, ("owner.timezone", "source[0].label", "llm"), (5, 11, 16)
        ):
            for fragment in ("validate config", key, f"line {line}", "expected", "next step:"):
                self.assertIn(fragment, message)
        self.assertEqual("", result.stdout)

    def test_subprocess_paths_and_no_addresses(self):
        result = self.run_config()
        self.assertEqual(0, result.returncode, result.stderr)
        paths = json.loads(result.stdout)
        self.assertEqual(
            {
                "work_dir",
                "profile_dir",
                "profile_stats",
                "stats_llm",
                "exemplars",
                "editorial_rules",
                "names",
            },
            set(paths),
        )
        self.assertEqual(str(self.root / "work"), paths["work_dir"])
        self.assertEqual(str(self.root / "rules.md"), paths["editorial_rules"])
        self.assertTrue(all(Path(value).is_absolute() for value in paths.values()))
        for address in ("owner@example.com", "alias@example.org", "friend@example.net"):
            self.assertNotIn(address, result.stdout + result.stderr)
        self.assertFalse((self.root / "work").exists(), "config show is read-only")

    def test_defaults_and_complete_llm(self):
        config, domain_map = load_config(self.path)
        self.assertEqual("pffexport", config["source"][0]["reader"])
        self.assertEqual("corporate", config["profile"]["current_source"])
        self.assertEqual("builtin", config["ingest"]["sensitive_terms"])
        self.assertFalse(config["source"][0]["llm_eligible"])
        self.assertIn("colleague", domain_map["classes"])
        llm = {
            "provider": "example",
            "retention_terms": "private",
            "training_use": "none",
            "attestation": "2026-09-25 owner confirms processing",
        }
        self.assertEqual([], llm_completeness(llm))
        llm["attestation"] = "2026-02-30 invalid date"
        self.assertEqual(["attestation"], llm_completeness(llm))
        self.assertEqual(4, len(llm_completeness(None)))

    def test_config_error_matrix(self):
        data, _ = read_toml(self.path)
        cases = [
            (("schema_version",), True),
            (("owner", "addresses"), "private@example.com"),
            (("owner", "names"), []),
            (("owner", "timezone"), 9),
            (("paths", "work_dir"), ""),
            (("paths", "domain_map"), 1),
            (("paths", "editorial_rules"), False),
            (("source",), []),
            (("source", 0, "label"), "../bad"),
            (("source", 0, "kind"), "ost"),
            (("source", 0, "path"), ""),
            (("source", 0, "reader"), "pypff"),
            (("source", 0, "allow_inside_git_tree"), "yes"),
            (("source", 0, "llm_eligible"), 1),
            (("source", 0, "timezone"), "Not/AZone"),
            (("source", 0, "owner_addresses"), 3),
            (("source", 0, "sent_folders"), []),
            (("source", 0, "era"), {"from_year": 2020, "to_year": 2010}),
            (("ingest", "checkpoint_every"), 0),
            (("ingest", "readpst_jobs"), -1),
            (("ingest", "sent_folders"), []),
            (("ingest", "extra_attribution_patterns"), ["("]),
            (("ingest", "sensitive_terms"), ""),
            (("ingest", "deny_terms_file"), 2),
            (("profile", "token_budget"), False),
            (("profile", "qual_retries"), -1),
            (("profile", "current_source"), "missing"),
            (("profile", "exemplars_max"), 1),
            (("llm", "provider"), 42),
        ]
        for keys, invalid in cases:
            with self.subTest(keys=keys):
                value = deepcopy(data)
                parent = value
                for key in keys[:-1]:
                    parent = parent.setdefault(key, {}) if isinstance(parent, dict) else parent[key]
                parent[keys[-1]] = invalid
                with self.assertRaises(ValidationErrors) as caught:
                    validate_config(value, text=CONFIG)
                message = str(caught.exception)
                for part in ("validate config", str(keys[-1]), "line", "expected", "next step:"):
                    self.assertIn(part, message)
                self.assertNotIn("private@example.com", message)

    def test_domain_map_errors_and_no_private_keys(self):
        data = {
            "schema_version": 1,
            "addresses": {"friend@example.net": "typo"},
            "domains": {"client.example": "typo"},
            "x500": {"Private Org": "typo"},
            "names": {"Private Name": "typo"},
            "precedence": ["wrong"],
            "group_threshold": 0,
        }
        with self.assertRaises(ValidationErrors) as caught:
            validate_domain_map(data)
        self.assertEqual(6, len(caught.exception.errors))
        for message in map(str, caught.exception.errors):
            for part in ("validate config", "line", "expected", "next step:"):
                self.assertIn(part, message)
            for private in ("friend@example.net", "Private Org", "Private Name", "client.example"):
                self.assertNotIn(private, message)
        for key, invalid in (
            ("schema_version", 2),
            ("classes", ["unknown"]),
            ("classes", 1),
            ("precedence", "unknown"),
            ("names", []),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValidationErrors, key):
                validate_domain_map({"schema_version": 1, key: invalid})
        with self.assertRaisesRegex(ValidationErrors, "duplicate"):
            validate_domain_map(
                {"schema_version": 1, "names": {"Ada": "personal", "ADA": "personal"}}
            )

    def test_file_errors_and_combined_boundaries(self):
        self.path.write_text(CONFIG.replace("America/Edmonton", "Bad/Zone"))
        (self.root / "domain-map.toml").write_text(
            'schema_version = 1\n[names]\n"Private Name" = "typo"\n'
        )
        with self.assertRaises(ValidationErrors) as caught:
            load_config(self.path)
        self.assertEqual(2, len(caught.exception.errors))
        for text in ("not = [ valid", None):
            if text is None:
                self.path.unlink()
            else:
                self.path.write_text(text)
            with self.assertRaises(ValidationErrors) as caught:
                read_toml(self.path)
            self.assertIsNotNone(caught.exception.__cause__)
            self.assertIn("load TOML", str(caught.exception))
            self.assertIn(str(self.path), str(caught.exception))
            self.assertIn("next step:", str(caught.exception))

    def test_provenance_excludes_paths_addresses_but_tracks_behavior(self):
        config, _ = load_config(self.path)
        other = deepcopy(config)
        other["paths"]["work_dir"] = "/different/private/place"
        other["owner"]["addresses"] = ["another@example.net"]
        other["source"][0]["owner_addresses"] = ["other@example.org"]
        other["source"][0]["path"] = "/different/mail.pst"
        self.assertEqual(config_digest(config), config_digest(other))
        other["source"][0]["llm_eligible"] = True
        self.assertNotEqual(config_digest(config), config_digest(other))
        result = provenance(
            config,
            self.root / "domain-map.toml",
            self.root / "rules.md",
            timestamp="2026-09-25T00:00:00Z",
        )
        self.assertEqual(file_sha256(self.root / "rules.md"), result["rules_sha256"])
        self.assertEqual("2026-09-25T00:00:00Z", result["generated_at"])
