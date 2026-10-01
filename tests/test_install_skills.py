import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        for directory in ("skills", "ownvoice", "scripts"):
            shutil.copytree(ROOT / directory, self.repo / directory)
        shutil.copyfile(ROOT / "pyproject.toml", self.repo / "pyproject.toml")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "pyproject.toml"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        skill = self.repo / "skills" / "sample"
        skill.mkdir()
        (skill / "PROMPT.md").write_text("neutral prompt")
        (skill / "contract.json").write_text("{}")
        for harness in ("claude", "codex"):
            adapter = self.repo / "adapters" / harness / "sample"
            adapter.mkdir(parents=True)
            (adapter / "SKILL.md").write_text(harness + " adapter")
        self.env = dict(os.environ)
        self.env.pop("OWNVOICE_CONFIG", None)
        self.env["HOME"] = str(self.base / "home")
        self.claude = self.base / "claude skills"
        self.codex = self.base / "codex skills"
        self.profile = self.base / "private profile"

    def run_install(self, *extra):
        return subprocess.run(
            [
                "bash",
                str(self.repo / "scripts" / "install-skills.sh"),
                "--claude-dir",
                str(self.claude),
                "--codex-dir",
                str(self.codex),
                "--profile-dir",
                str(self.profile),
                *extra,
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_diagnostic(self, result, code, identity, observed):
        self.assertEqual(result.returncode, code, result.stderr)
        for part in (identity, observed, "expected", "next step:"):
            self.assertIn(part, result.stderr)

    def test_copy_stamp_update_and_template_default(self):
        result = self.run_install("--verbose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.claude), result.stderr)
        sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
        ).strip()
        for harness, base in (("claude", self.claude), ("codex", self.codex)):
            target = base / "sample"
            self.assertEqual((target / "PROMPT.md").read_text(), "neutral prompt")
            self.assertEqual((target / "SKILL.md").read_text(), harness + " adapter")
            self.assertEqual(
                json.loads((target / ".ownvoice-installed").read_text()),
                {"tool_version": "1.0.0", "git_sha": sha},
            )
            self.assertFalse(any(p.is_symlink() for p in target.rglob("*")))
        self.assertEqual(
            (self.profile / "editorial-rules.md").read_bytes(),
            (self.repo / "skills/editorial-rules/editorial-rules.TEMPLATE.md").read_bytes(),
        )
        (self.repo / "skills/sample/PROMPT.md").write_text("updated")
        self.assertEqual((self.claude / "sample/PROMPT.md").read_text(), "neutral prompt")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.claude / "sample/PROMPT.md").read_text(), "updated")

    def test_unstamped_refusal_force_and_rules_never_overwritten(self):
        self.assertEqual(self.run_install("--rules", "owner").returncode, 0)
        rules = self.profile / "editorial-rules.md"
        self.assertEqual(
            rules.read_bytes(),
            (self.repo / "skills/editorial-rules/editorial-rules.md").read_bytes(),
        )
        rules.write_text("owner custom rules")
        before = hashlib.sha256(rules.read_bytes()).hexdigest()
        (self.codex / "sample/.ownvoice-installed").unlink()
        result = self.run_install()
        self.assert_diagnostic(
            result, 2, str(self.codex / "sample"), "existing unstamped directory"
        )
        self.assertIn("install skills", result.stderr)
        self.assertIn("--force", result.stderr)
        result = self.run_install("--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hashlib.sha256(rules.read_bytes()).hexdigest(), before)

    def test_configuration_destination_is_authoritative(self):
        config = self.base / "settings.toml"
        (self.base / "map.toml").write_text("schema_version = 1\n")
        config.write_text("""schema_version = 1
[owner]
addresses = ["owner@example.com"]
names = ["Example Owner"]
timezone = "UTC"
[paths]
work_dir = "work"
domain_map = "map.toml"
editorial_rules = "custom/rules.md"
[[source]]
label = "test"
kind = "eml"
path = "mail"
""")
        self.env["OWNVOICE_CONFIG"] = str(config)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.base / "custom/rules.md"
        self.assertTrue(target.is_file())
        self.assertFalse(self.profile.exists())
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(self.run_install("--rules", "owner", "--force").returncode, 0)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), before)

    def test_argument_config_filesystem_and_symlink_diagnostics(self):
        result = self.run_install("--rules", "other")
        self.assert_diagnostic(result, 2, "install-skills.sh", "invalid choice")
        self.env["OWNVOICE_CONFIG"] = str(self.base / "absent.toml")
        result = self.run_install()
        self.assert_diagnostic(result, 2, "absent.toml", "No such file")
        self.assertIn("caused by:", result.stderr)
        del self.env["OWNVOICE_CONFIG"]
        self.claude.write_text("not a directory")
        result = self.run_install()
        self.assert_diagnostic(result, 3, str(self.claude), "Not a directory")
        self.assertIn("caused by:", result.stderr)
        self.claude.unlink()
        self.claude.mkdir()
        (self.claude / "sample").symlink_to(self.profile, target_is_directory=True)
        result = self.run_install("--force")
        self.assert_diagnostic(result, 2, str(self.claude / "sample"), "symlink destination")

    def test_rules_overlap_refused_without_overwrite(self):
        self.profile = self.claude / "editorial-rules"
        self.profile.mkdir(parents=True)
        rules = self.profile / "editorial-rules.md"
        rules.write_text("custom rules")
        before = hashlib.sha256(rules.read_bytes()).hexdigest()
        result = self.run_install("--force")
        self.assert_diagnostic(result, 2, str(rules), "editorial rules overlap")
        self.assertEqual(hashlib.sha256(rules.read_bytes()).hexdigest(), before)
