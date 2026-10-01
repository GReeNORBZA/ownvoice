"""install-skills.sh from a release tree: one harness is enough, git is optional."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_install_skills import InstallSkillsTests

ROOT = Path(__file__).resolve().parents[1]


class PortableInstallTests(unittest.TestCase):
    setUp = InstallSkillsTests.setUp
    assert_diagnostic = InstallSkillsTests.assert_diagnostic

    def install(self, *args, repo=None):
        return subprocess.run(
            ["bash", str((repo or self.repo) / "scripts" / "install-skills.sh"), *args],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_single_harness(self):
        result = self.install("--claude-dir", str(self.claude), "--profile-dir", str(self.profile))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("claude adapter", (self.claude / "sample" / "SKILL.md").read_text())
        self.assertFalse(self.codex.exists())

    def test_no_harness_is_a_diagnostic(self):
        result = self.install("--profile-dir", str(self.profile))
        self.assert_diagnostic(result, 2, "install-skills.sh", "no harness directory given")

    def test_tree_without_git_stamps_no_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            plain = Path(temporary) / "release"
            shutil.copytree(self.repo, plain, ignore=shutil.ignore_patterns(".git"))
            result = self.install(
                "--codex-dir", str(self.codex), "--profile-dir", str(self.profile), repo=plain
            )
            self.assertEqual(0, result.returncode, result.stderr)
            stamp = json.loads((self.codex / "sample" / ".ownvoice-installed").read_text())
            self.assertIsNone(stamp["git_sha"])


if __name__ == "__main__":
    unittest.main()
