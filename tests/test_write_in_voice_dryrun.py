"""AC-15 scripted harness stand-ins, using installed skills and real lint processes."""

import importlib.util
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ownvoice.errors import DiagnosticError, ValidationErrors
from ownvoice.io import has_private_marker, write_marked_text
from ownvoice.qual import dispatch, synthesis_check
from tests import test_profile
from tests.test_lint import LONG
from tests.test_rules_block import block

ROOT = Path(__file__).resolve().parents[1]


def load_workflow(path):
    spec = importlib.util.spec_from_file_location("writing_workflow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def brief(**changes):
    return {
        "audience": {"text": "A synthetic client", "recipient_class": "client"},
        "medium": "email",
        "formality": 3,
        "length": "short",
        "purpose": "Confirm the meeting",
        "facts": ["Meeting confirmed"],
        "must_include": [],
        "must_avoid": [],
        **changes,
    }


class BriefSectionsTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        self.core = "## Core voice\n\nShared synthetic pattern."
        self.delta = "## 3. Edit-delta tendencies\n\nShorten prose.\n### Detail\nKeep this detail."
        self.anti = "## 5. Anti-patterns\n\nAvoid padding.\n### Detail\nKeep this too."
        self.registers = {
            name: f"### {name}\n\nSynthetic {name} guidance."
            for name in ("client", "cold", "article")
        }
        self.profile = "\n\n".join(
            [
                "# Synthetic profile",
                "## 0. Metadata\nExcluded metadata.",
                "## 1. Precedence and use\nExcluded precedence.",
                self.core,
                "## 2. Per register",
                *self.registers.values(),
                "### Per-source contrast\nExcluded contrast-table text.",
                self.delta,
                "## 4. Phrase tables\nExcluded phrases.",
                self.anti,
                "## 6. Provenance\nExcluded provenance.",
                "### client\nExcluded misplaced register.",
            ]
        )

    def test_f53_exact_sections_for_each_register(self):
        for register, section in self.registers.items():
            with self.subTest(register=register):
                self.assertEqual(
                    f"{self.core}\n\n{section}\n\n{self.delta}\n\n{self.anti}\n",
                    self.workflow.brief_sections(self.profile, register),
                )

    def test_section_boundaries_include_children_and_end_at_parent(self):
        profile = self.profile.replace(
            "## 4. Phrase tables", "# Parent boundary\nExcluded parent.\n## 4. Phrase tables"
        )
        result = self.workflow.brief_sections(profile, "client")
        self.assertIn(self.delta, result)
        self.assertIn(self.anti, result)
        self.assertNotIn("Excluded", result)

    def test_indented_atx_boundaries_and_starts_preserve_exact_sections(self):
        boundaries = (
            "## 2. Per register",
            "### cold",
            "### Per-source contrast",
            "## 3. Edit-delta tendencies",
            "## 4. Phrase tables",
            "## 6. Provenance",
        )
        expected = "\n\n".join([self.core, self.registers["client"], self.delta, self.anti]) + "\n"
        for indent, boundary in itertools.product(range(1, 4), boundaries):
            with self.subTest(indent=indent, boundary=boundary):
                profile = self.profile.replace(boundary, " " * indent + boundary)
                self.assertEqual(expected, self.workflow.brief_sections(profile, "client"))
        # Normal ATX spelling applies to starts and ends alike, including closing hashes.
        for indent in range(4):
            with self.subTest(all_headings_indented=indent):
                profile = "\n".join(
                    " " * indent + line + " ###" if line.startswith("#") else line
                    for line in self.profile.splitlines()
                )
                result = self.workflow.brief_sections(profile, "client")
                normalized = (
                    "\n".join(
                        line.strip().removesuffix(" ###") if line.lstrip().startswith("#") else line
                        for line in result.splitlines()
                    )
                    + "\n"
                )
                self.assertEqual(expected, normalized)

    def test_duplicate_required_headings_fail_closed(self):
        for heading, indent in itertools.product(
            (
                "## Core voice",
                "## 2. Per register",
                "### client",
                "## 3. Edit-delta tendencies",
                "## 5. Anti-patterns",
            ),
            range(4),
        ):
            with self.subTest(heading=heading, indent=indent):
                profile = self.profile.replace(
                    heading + "\n",
                    " " * indent + heading + "\nAmbiguous guidance.\n" + heading + "\n",
                    1,
                )
                with self.assertRaises(ValidationErrors) as caught:
                    self.workflow.brief_sections(profile, "client")
                for part in (
                    "extract writing brief",
                    heading,
                    "duplicate heading: 2 occurrences",
                    "expected one heading",
                    "next step:",
                ):
                    self.assertIn(part, str(caught.exception))

    def test_synthesis_approved_embedded_register_heading_is_rejected(self):
        response = {
            "1": "Rules first.",
            "2": {
                "article": "Article-only guidance.\n### client\nArticle-only continuation.",
                "client": "Actual client guidance.",
            },
            "3": "Delta guidance.",
            "5": "Anti guidance.",
        }
        sections = dispatch.parse_sections(json.dumps(response), ["article", "client"])
        profile = dispatch.assemble(
            sections, {"profile_mode": "qualitative profile"}, [], "Rules.", {}
        )
        with tempfile.TemporaryDirectory() as directory:
            names = Path(directory) / "names.txt"
            names.write_text("")
            synthesis_check.check(
                profile,
                names,
                [],
                quoted_text="\n".join(
                    [sections["1"], *sections["2"].values(), sections["3"], sections["5"]]
                ),
            )
        self.assertEqual(
            list(range(7)),
            [
                int(line[3])
                for line in profile.splitlines()
                if line.startswith("## ") and line[3].isdigit()
            ],
        )
        with self.assertRaises(ValidationErrors) as caught:
            self.workflow.brief_sections(profile, "client")
        for part in (
            "extract writing brief",
            "### client",
            "duplicate heading: 2 occurrences",
            "next step:",
        ):
            self.assertIn(part, str(caught.exception))

    def test_missing_register_container_and_excluded_contrast_fail_closed(self):
        for profile, register, heading in (
            (
                self.profile.replace("## 2. Per register", "## Other section"),
                "client",
                "## 2. Per register",
            ),
            (self.profile, "Per-source contrast", "### Per-source contrast"),
        ):
            with self.subTest(heading=heading):
                with self.assertRaises(ValidationErrors) as caught:
                    self.workflow.brief_sections(profile, register)
                for part in (
                    "extract writing brief",
                    heading,
                    "missing heading",
                    "expected",
                    "next step:",
                ):
                    self.assertIn(part, str(caught.exception))

    def test_duplicate_heading_cli_returns_no_partial_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.md"
            path.write_text(self.profile + "\n" + self.core)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "skills/write-in-voice/workflow.py"),
                    "brief-sections",
                    "--profile",
                    str(path),
                    "--register",
                    "client",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertEqual("", result.stdout)
            for part in (
                "extract writing brief",
                "## Core voice",
                "duplicate heading: 2 occurrences",
                "next step:",
            ):
                self.assertIn(part, result.stderr)

    def test_legacy_core_note_and_required_heading_diagnostics(self):
        legacy = self.profile.replace(self.core + "\n\n", "")
        self.assertEqual(
            "Core voice: not in this profile; rebuild it with voice-profile-build.\n\n"
            + "\n\n".join([self.registers["client"], self.delta, self.anti])
            + "\n",
            self.workflow.brief_sections(legacy, "client"),
        )
        for section in (self.registers["client"], self.delta, self.anti):
            heading = section.splitlines()[0]
            with self.subTest(heading=heading):
                with self.assertRaises((DiagnosticError, ValidationErrors)) as caught:
                    self.workflow.brief_sections(self.profile.replace(section, ""), "client")
                for part in (
                    "extract writing brief",
                    heading,
                    "missing",
                    "expected",
                    "next step:",
                ):
                    self.assertIn(part, str(caught.exception))

    def test_brief_sections_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.md"
            path.write_text(self.profile)
            command = [
                sys.executable,
                str(ROOT / "skills/write-in-voice/workflow.py"),
                "brief-sections",
                "--profile",
                str(path),
                "--register",
                "client",
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(self.workflow.brief_sections(self.profile, "client"), result.stdout)
            path.write_text(self.profile.replace(self.delta, ""))
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(2, result.returncode)
            self.assertIn("## 3. Edit-delta tendencies", result.stderr)
            self.assertEqual("", result.stdout)
            path.unlink()
            result = subprocess.run(
                command + ["--verbose"], capture_output=True, text=True, check=False
            )
            self.assertEqual(3, result.returncode)
            for part in ("read writing profile", str(path), "expected", "caused by:", "next step:"):
                self.assertIn(part, result.stderr)
            self.assertIn("No such file or directory", result.stderr)


class WriteInVoiceDryRunTests(unittest.TestCase):
    setUp = test_profile.ProfileTests.setUp
    configure = test_profile.ProfileTests.configure
    row = test_profile.ProfileTests.row
    inputs = test_profile.ProfileTests.inputs

    def install(self):
        env = {**os.environ, "OWNVOICE_CONFIG": str(self.config)}
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/install-skills.sh"),
                "--claude-dir",
                str(self.root / "claude"),
                "--codex-dir",
                str(self.root / "codex"),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for adapter in ("claude", "codex"):
            for skill in ("voice-profile-build", "write-in-voice"):
                target = self.root / adapter / skill
                self.assertEqual(
                    (ROOT / "adapters" / adapter / skill / "SKILL.md").read_bytes(),
                    (target / "SKILL.md").read_bytes(),
                )
                for name in ("PROMPT.md", "contract.json", ".ownvoice-installed"):
                    self.assertTrue((target / name).is_file())
            self.assertIn(
                "workflow.py", (self.root / adapter / "write-in-voice/SKILL.md").read_text()
            )

    def profile(self, severity="error"):
        self.inputs([self.row(1, LONG), self.row(2, LONG)])
        result = test_profile.ProfileTests.cli(self)
        self.assertEqual(0, result.returncode, result.stderr)
        profile = self.work / "profile/ownvoice"
        write_marked_text(
            profile / "voice-profile.md",
            "## Core voice\n\nShared synthetic pattern.\n\n"
            "## 2. Per register\n\n"
            "### client\n\nUse measured direct prose.\n\n"
            "### cold\n\nUNRELATED REGISTER MUST NOT REACH MODEL\n\n"
            "## 3. Edit-delta tendencies\n\nShorten prose.\n\n"
            "## 5. Anti-patterns\n\nAvoid padding.\n",
        )
        for path in profile.iterdir():
            self.assertTrue(has_private_marker(path), path)
        (self.root / "rules.md").write_text(
            block(f'''schema_version = 1
[[ban]]
id = "meeting-word"
kind = "word"
pattern = "prohibitedtoken"
media = ["email"]
severity = "{severity}"
message = "remove the synthetic prohibited word"
''')
        )
        return profile

    def context(self, profile, workflow):
        # Scripted adapter follows PROMPT's heading boundary and stats-only rule.
        text = (profile / "voice-profile.md").read_text()
        selected = workflow.brief_sections(text, "client")
        examples = json.loads((profile / "exemplars.json").read_text())
        return {
            "register": selected,
            "rules": (self.root / "rules.md").read_text(),
            "exemplars": workflow.select_exemplars(
                examples["registers"]["client"], "short", stats_only=True
            ),
        }

    def test_each_installed_adapter_fixes_error_or_stops_at_three(self):
        profile = self.profile()
        self.install()
        for adapter, fixes in itertools.product(("claude", "codex"), (True, False)):
            with self.subTest(adapter=adapter, fixes=fixes):
                workflow = load_workflow(self.root / adapter / "write-in-voice/workflow.py")
                context = self.context(profile, workflow)
                calls = []

                def model(input_brief, selected, findings, calls=calls, fixes=fixes):
                    self.assertEqual(input_brief, brief())
                    self.assertNotIn("UNRELATED", str(selected))
                    self.assertEqual([], selected["exemplars"])
                    calls.append(findings)
                    if len(calls) > 1:
                        self.assertIn("rules.meeting-word", {f["rule_id"] for f in findings})
                    return {
                        "draft": "Meeting confirmed."
                        + (" prohibitedtoken" if len(calls) == 1 or not fixes else "")
                    }

                session = self.root / f"session-{adapter}-{fixes}"
                result = workflow.run_loop(
                    brief(), context, model, config=self.config, session_dir=session
                )
                self.assertEqual(2 if fixes else 3, result["iterations"])
                self.assertEqual(result["iterations"], len(calls))
                report_path = Path(result["report_path"])
                report = json.loads(report_path.read_text())
                self.assertTrue(has_private_marker(report_path))
                self.assertEqual(0o700, session.stat().st_mode & 0o777)
                for path in session.iterdir():
                    self.assertEqual(0o600, path.stat().st_mode & 0o777)
                self.assertEqual(result["draft"], (session / "draft.md").read_text())
                self.assertEqual(0 if fixes else 1, report["summary"]["error"])
                self.assertEqual(
                    "lint: 0 errors, 0 warnings"
                    if fixes
                    else "lint: 1 errors, 0 warnings (rules.meeting-word)",
                    result["lint_result"],
                )
                self.assertEqual(
                    [] if fixes else ["rules.meeting-word"],
                    [f["rule_id"] for f in result["remaining_findings"]],
                )
                self.assertIn("stats.short_draft", {f["rule_id"] for f in result["info"]})
                self.assertTrue(all(f["fix_hint"] for f in result["remaining_findings"]))

    def test_complete_medium_formality_recipient_mapping(self):
        workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        classes = (
            "personal",
            "professional-warm",
            "colleague",
            "client",
            "vendor",
            "cold",
            "group",
            "unknown",
        )
        for medium, formality, recipient in itertools.product(
            ("email", "blog", "linkedin", "doc", "proposal"), range(1, 6), classes
        ):
            with self.subTest(medium=medium, formality=formality, recipient=recipient):
                value = brief(
                    medium=medium,
                    formality=formality,
                    audience={"text": "Reader", "recipient_class": recipient},
                )
                expected = (
                    "article"
                    if medium != "email"
                    else (
                        ("personal", "professional-warm", "client", "cold", "cold")[formality - 1]
                        if recipient == "unknown"
                        else recipient
                    )
                )
                self.assertEqual(expected, workflow.register_for(value))

    def test_boundary_validation_collects_all_errors(self):
        workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        for value in ({}, brief(formality=True, length=False, facts="wrong"), []):
            with self.assertRaises(ValidationErrors) as caught:
                workflow.validate_brief(value)
            for error in caught.exception.errors:
                for part in ("validate writing brief", error.identity, "expected", "next step:"):
                    self.assertIn(part, str(error))
            self.assertEqual(
                9 if value == {} else 1 if value == [] else 3, len(caught.exception.errors)
            )

    def test_tertile_selection_and_stats_only(self):
        workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        register = {
            "selection": {
                "status": "ok",
                "strata": [
                    {"boundaries": [0, 10]},
                    {"boundaries": [10, 20]},
                    {"boundaries": [20, 30]},
                ],
            },
            "items": [
                {"stratum": s, "text": f"Synthetic {s}/{i}"} for s in range(3) for i in range(6)
            ],
        }
        for length, expected in (
            ("short", 0),
            ("medium", 1),
            ("long", 2),
            (10, 0),
            (11, 1),
            (20, 1),
            (21, 2),
        ):
            chosen = workflow.select_exemplars(register, length, stats_only=False)
            self.assertEqual(5, len(chosen))
            self.assertEqual({expected}, {item["stratum"] for item in chosen})
        self.assertEqual([], workflow.select_exemplars(register, 10, stats_only=True))
        register["items"] = register["items"][:2]
        self.assertEqual(2, len(workflow.select_exemplars(register, 10, stats_only=False)))
        register["selection"]["status"] = "no_llm_eligible_source"
        self.assertEqual([], workflow.select_exemplars(register, 10, stats_only=False))

    def test_warnings_fixed_unless_justified_and_cli_errors_stop(self):
        profile = self.profile(severity="warn")
        workflow = load_workflow(ROOT / "skills/write-in-voice/workflow.py")
        for justify in (True, False):
            calls = []

            def model(value, context, findings, calls=calls, justify=justify):
                calls.append(findings)
                return {
                    "draft": "prohibitedtoken" if len(calls) == 1 else "Meeting confirmed.",
                    "justified_warnings": {"rules.meeting-word": "Brief requires the term"}
                    if justify
                    else {},
                }

            result = workflow.run_loop(
                brief(must_include=["prohibitedtoken"] if justify else []),
                self.context(profile, workflow),
                model,
                config=self.config,
                session_dir=self.root / f"warnings-{justify}",
            )
            self.assertEqual(1 if justify else 2, result["iterations"])
            self.assertEqual(justify, bool(result["justified_warnings"]))
            self.assertEqual([], result["remaining_findings"])
        (profile / "profile-stats.json").unlink()
        with self.assertRaises(DiagnosticError) as caught:
            workflow.run_loop(
                brief(), {}, model, config=self.config, session_dir=self.root / "broken"
            )
        for part in (
            "run writing subprocess",
            str(self.config),
            "lint exit 3",
            "profile-stats.json",
            "caused by:",
            "next step:",
        ):
            self.assertIn(part, str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, subprocess.CalledProcessError)
