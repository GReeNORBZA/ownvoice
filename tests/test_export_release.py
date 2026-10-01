"""scripts/export-release.sh: fresh-history export without internal trees.

Runs against a synthetic clone of this checkout with a stub GitHub workflow.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/export-release.sh"
AUTHOR = "Example Release <release@example.com>"


def run(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)


class ExportReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        run("git", "clone", "-q", "--no-local", str(ROOT), str(self.source))
        # Make the clone's HEAD match the working tree under test.
        for path in (
            SCRIPT,
            ".release-exclude",
            "ownvoice/guard/__init__.py",
            "ownvoice/guard/rules.py",
        ):
            (self.source / path).write_bytes((ROOT / path).read_bytes())
        for internal in ("docs/frd", "docs/prompts", "docs/testing"):
            (self.source / internal).mkdir(parents=True, exist_ok=True)
            (self.source / internal / "note.md").write_text("internal\n")
        self.excluded = [
            line.strip()
            for line in (ROOT / ".release-exclude").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        for path in self.excluded:
            target = self.source / path
            if not path.startswith("docs/"):
                target.write_text("internal\n")
        # The export is checked on the package and docs; the test tree is not needed here.
        run("git", "rm", "-rq", "tests", cwd=self.source)
        workflow = self.source / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("name: CI\n")
        run("git", "add", "-A", cwd=self.source)
        run(
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qm",
            "synthetic",
            cwd=self.source,
        )
        self.names = self.base / "names.txt"
        self.names.write_text("Qorvexalunda\n")

    def export(self, *extra):
        out = self.base / "out"
        result = run(
            "bash",
            str(self.source / SCRIPT),
            "--out",
            str(out),
            "--names-file",
            str(self.names),
            "--author",
            AUTHOR,
            *extra,
            cwd=self.source,
            check=False,
        )
        return out, result

    def test_export_drops_internal_trees_and_history(self):
        out, result = self.export()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for internal in (*self.excluded, ".release-exclude"):
            self.assertFalse((out / internal).exists(), internal)
        self.assertTrue((out / ".github/workflows/ci.yml").is_file())
        log = run("git", "log", "--format=%an <%ae>", cwd=out).stdout.splitlines()
        self.assertEqual([AUTHOR], log)

    def test_deny_terms_fail_without_printing_the_term(self):
        deny = self.base / "deny.txt"
        deny.write_text("synthetic-internal-term\n")
        readme = self.source / "README.md"
        readme.write_text(readme.read_text() + "\nsynthetic-internal-term\n")
        run(
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qam",
            "term",
            cwd=self.source,
        )
        _, result = self.export("--deny-terms", str(deny))
        self.assertEqual(5, result.returncode)
        self.assertIn("deny-term hits: README.md" + ":1", result.stderr)
        self.assertNotIn("synthetic-internal-term", result.stdout + result.stderr)

    def test_missing_author_and_existing_out_are_diagnostics(self):
        result = run(
            "bash",
            str(self.source / SCRIPT),
            "--out",
            str(self.base / "o"),
            "--names-file",
            str(self.names),
            cwd=self.source,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("export release [--author]: missing", result.stderr)
        (self.base / "taken").mkdir()
        result = run(
            "bash",
            str(self.source / SCRIPT),
            "--out",
            str(self.base / "taken"),
            "--names-file",
            str(self.names),
            "--author",
            AUTHOR,
            cwd=self.source,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("already exists", result.stderr)


if __name__ == "__main__":
    unittest.main()
