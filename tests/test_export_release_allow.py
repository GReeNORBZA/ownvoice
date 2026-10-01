"""export-release.sh --release-allow drops reviewed tokens from the release names check only."""

import unittest

from tests.test_export_release import ExportReleaseTests, run


class ReleaseAllowTests(unittest.TestCase):
    setUp = ExportReleaseTests.setUp
    export = ExportReleaseTests.export

    def commit_word(self, word):
        readme = self.source / "README.md"
        readme.write_text(readme.read_text() + f"\n{word} appears here.\n")
        run(
            "git",
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qam",
            "word",
            cwd=self.source,
        )
        self.names.write_text(f"Qorvexalunda\n{word}\n")

    def test_listed_token_passes_and_the_names_file_is_untouched(self):
        self.commit_word("Brindlemoor")
        _, blocked = self.export()
        self.assertEqual(5, blocked.returncode)
        self.assertIn("[README.md]: rule 4 violation", blocked.stderr)
        allow = self.base / "release-allow.txt"
        allow.write_text("# reviewed\nbrindlemoor\n")
        (self.base / "out").rename(self.base / "out-blocked")
        _, passed = self.export("--release-allow", str(allow))
        self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)
        self.assertEqual("Qorvexalunda\nBrindlemoor\n", self.names.read_text())

    def test_owner_names_allow_still_applies(self):
        self.commit_word("Brindlemoor")
        (self.names.parent / "names-allow.txt").write_text("Brindlemoor\n")
        _, result = self.export()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
