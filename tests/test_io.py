import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ownvoice.errors import DiagnosticError
from ownvoice.io import (
    PRIVATE_KEY,
    PRIVATE_LINE,
    append_jsonl,
    has_private_marker,
    inside_git_worktree,
    write_json,
    write_jsonl,
    write_marked_text,
    write_marked_toml,
)
from ownvoice.layout import Layout


class IoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_private_writes_markers_and_modes(self):
        for name, writer, payload in (
            ("object.json", write_json, {"value": 42}),
            ("rows.jsonl", write_jsonl, [{"value": 1}, {"value": 2}]),
            ("profile.md", write_marked_text, "hello"),
            ("names.txt", write_marked_text, "Synthetic Name"),
            ("ordinary.toml", write_marked_toml, "schema_version = 1\n"),
        ):
            with self.subTest(name=name):
                path = self.root / "private" / "nested" / name
                writer(path, payload)
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
                for directory in (path.parent, path.parent.parent):
                    self.assertEqual(0o700, stat.S_IMODE(directory.stat().st_mode))
                self.assertTrue(has_private_marker(path))
        rows = (self.root / "private/nested/rows.jsonl").read_text().splitlines()
        self.assertTrue(all(json.loads(row)[PRIVATE_KEY] == "private" for row in rows))

    def test_marker_is_structural_not_substring(self):
        path = self.root / "renamed"
        for text, expected in (
            (json.dumps({"nested": {PRIVATE_KEY: "private"}}), False),
            ("preface\n" + PRIVATE_LINE, False),
            ("prefix " + PRIVATE_LINE + " suffix", False),
            (json.dumps({"text": PRIVATE_LINE}), False),
            (json.dumps({PRIVATE_KEY: "altered"}), True),
            ("{}\n" + json.dumps({PRIVATE_KEY: "private"}), True),
            (f'{PRIVATE_KEY} = "private"\n', True),
            (f'[nested]\n{PRIVATE_KEY} = "private"\n', False),
            ("schema_version = 1\n", False),
        ):
            path.write_text(text)
            self.assertEqual(expected, has_private_marker(path), text)

    def test_atomic_journal_append_and_failure_preserves_prefix(self):
        path = self.root / "journal" / "records.jsonl"
        write_jsonl(path, [{"value": 1}])
        append_jsonl(path, {"value": 2})
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([1, 2], [row["value"] for row in rows])
        self.assertTrue(all(row[PRIVATE_KEY] == "private" for row in rows))
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        original = path.read_bytes()
        cause = OSError("synthetic append rename denial")
        with (
            patch("ownvoice.io.os.replace", side_effect=cause),
            self.assertRaises(DiagnosticError) as caught,
        ):
            append_jsonl(path, {"value": 3})
        self.assertIs(cause, caught.exception.__cause__)
        for part in ("write private artefact", str(path), str(cause), "expected", "next step:"):
            self.assertIn(part, str(caught.exception))
        self.assertEqual(original, path.read_bytes())
        self.assertEqual([path], list(path.parent.iterdir()))

    def test_atomic_replacement_failure_preserves_original(self):
        path = self.root / "output.json"
        write_json(path, {"version": 1})
        original = path.read_bytes()
        cause = OSError("synthetic rename denial")
        with (
            patch("ownvoice.io.os.replace", side_effect=cause),
            self.assertRaises(DiagnosticError) as caught,
        ):
            write_json(path, {"version": 2})
        self.assertEqual(original, path.read_bytes())
        self.assertEqual([path], list(self.root.iterdir()))
        self.assertIs(cause, caught.exception.__cause__)
        for part in (
            "write private artefact",
            str(path),
            "synthetic rename denial",
            "expected",
            "next step:",
        ):
            self.assertIn(part, str(caught.exception))

    def test_git_detection_new_paths_symlinks_and_write_refusal(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        self.assertTrue(inside_git_worktree(repo / "not-created" / "file.json"))
        self.assertFalse(inside_git_worktree(self.root / "outside"))
        link = self.root / "link"
        link.symlink_to(repo, target_is_directory=True)
        self.assertTrue(inside_git_worktree(link / "file.json"))
        linked = self.root / "linked"
        linked.mkdir()
        (linked / ".git").write_text("gitdir: /unused/worktree/path")
        self.assertTrue(inside_git_worktree(linked / "new"))
        with self.assertRaisesRegex(
            DiagnosticError, "write private artefact.*git working tree.*next step"
        ):
            write_json(repo / "private.json", {})
        self.assertFalse((repo / "private.json").exists())

    def test_read_error_and_layout(self):
        with self.assertRaises(DiagnosticError) as caught:
            has_private_marker(self.root / "missing")
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertIn("inspect private marker", str(caught.exception))
        self.assertIn("next step:", str(caught.exception))
        layout = Layout(self.root)
        self.assertEqual(
            self.root / "sources/corporate/extract/.done",
            layout.source_paths("corporate")["extract_done"],
        )
        self.assertEqual(self.root / "names.txt", layout.names)
        self.assertEqual(self.root / "unmapped-domains.json", layout.unmapped_domains)
        with self.assertRaisesRegex(DiagnosticError, "source.label.*next step"):
            layout.source("../escape")
