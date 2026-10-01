"""C15 cross-slice contracts. Authz is N/A: no listener, single operator.

All corpus and generated files live in pytest's private temporary directory.
The fixtures exercise real commands, with only the external PST binary shimmed.
"""

import argparse
import ast
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

from ownvoice.cli import build_parser
from ownvoice.guard.rules import artifact_name
from ownvoice.io import PRIVATE_KEY, PRIVATE_LINE, write_jsonl, write_marked_text
from ownvoice.qual import chunk
from ownvoice.schemas import ingest_report, manifest
from tests import test_lint, test_qual
from tests.test_cli_surface import EXPECTED_FRD_COMMANDS

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("example.com", "example.net", "example.org", "unmapped.example", "fallback.example")
SCHEMAS = {
    "records.jsonl": "records",
    "profiled-records.jsonl": "records",
    "profiled-articles.jsonl": "article_records",
    "cross-register.json": "cross_register",
    "rejects.jsonl": "rejects",
    "checkpoint.json": "checkpoint",
    "merge-state.json": "merge_state",
    "unmapped-domains.json": "unmapped_domains",
    "names.txt": "names",
    "profile-stats.json": "profile_stats",
    "stats-llm.json": "stats_llm",
    "exemplars.json": "exemplars",
    "edit-delta.json": "edit_delta",
    "manifest.json": "manifest",
    "grounded.jsonl": "finding",
    "grounded.jsonl.report.json": "qual_report",
    "diff.json": "qual_diff",
    "findings-set.json": "findings_set",
    "lint.json": "lint",
}


def command(config, *args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "ownvoice", "--config", str(config), "--verbose", *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def assert_implemented(result):
    assert result.returncode != 1, result.stderr
    assert "not implemented yet" not in result.stdout + result.stderr


def assert_diagnostic(result, operation, identity, code):
    assert result.returncode == code, result.stderr
    assert operation in result.stderr, result.stderr
    assert identity in result.stderr, result.stderr
    assert "expected " in result.stderr, result.stderr
    assert re.search(r"next step: \S.+", result.stderr), result.stderr


def assert_marker(path):
    text = path.read_text()
    if path.suffix == ".jsonl":
        for line in text.splitlines():
            assert json.loads(line).get(PRIVATE_KEY) == "private", path
    elif path.suffix == ".json":
        assert json.loads(text).get(PRIVATE_KEY) == "private", path
    else:
        assert text.splitlines()[0] == PRIVATE_LINE, path


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("c15")
    work = root / "work"
    config = root / "config.toml"
    (root / "map.toml").write_text(
        'schema_version=1\n[domains]\n"example.net"="client"\n"example.com"="client"\n'
        '[x500]\n"ExampleCorp"="colleague"\n[names]\n"Known Person"="personal"\n'
    )
    (root / "rules.md").write_text((ROOT / "skills/editorial-rules/editorial-rules.md").read_text())
    (root / "mail.pst").write_bytes(b"!BDNsynthetic")
    bodies = (
        "please send Zorvyn the report at zorvyn@example.net so we can review the plan together.",
        "Zorvyn can ask Veltrix to review the next draft and we can share our thoughts at the meeting.",
        "we should discuss the medical diagnosis privately before sending the final report.",
        "please check the proposed schedule and let us know when the work can begin.",
    )
    with (root / "mail.mbox").open("wb") as stream:
        for index, body in enumerate(bodies):
            mail = EmailMessage()
            mail["From"] = "owner@example.com"
            mail["To"] = "Zorvyn <zorvyn@example.net>"
            mail["Message-ID"] = f"<c15-{index}@example.com>"
            mail["Date"] = "Tue, 20 Jan 2026 12:00:00 +0000"
            mail.set_content(body)
            stream.write(b"From owner@example.com Tue Jan 20 12:00:00 2026\n")
            stream.write(mail.as_bytes() + b"\n")
    config.write_text(f'''schema_version=1
[owner]
addresses=["owner@example.com"]
names=["Owner"]
timezone="UTC"
[paths]
work_dir="{work}"
domain_map="map.toml"
editorial_rules="rules.md"
[llm]
provider="synthetic"
retention_terms="synthetic"
training_use="none"
attestation="2026-09-26 synthetic"
[[source]]
label="mail"
kind="mbox"
path="mail.mbox"
llm_eligible=true
[[source]]
label="pst"
kind="pst"
path="mail.pst"
llm_eligible=false
''')
    environment = {
        **os.environ,
        "PATH": str(ROOT / "tests/shims") + os.pathsep + os.environ["PATH"],
    }
    logs = []

    def run(*args, codes=(0,)):
        result = command(config, *args, env=environment)
        assert_implemented(result)
        assert result.returncode in codes, result.stderr
        logs.append(result.stdout + result.stderr)
        return result

    run("ingest")
    rows = chunk.read_json(work / "records.jsonl", lines=True)
    assert {r["source"] for r in rows} == {"mail", "pst"}
    assert any(r["sensitive"] for r in rows)
    assert any(r["scrub"]["residual_capitalised"] for r in rows)
    assert not (work / "sources/pst/extract").exists()
    (root / "before.md").write_text("We are ready to start the work with a simple plan.")
    (root / "after.md").write_text("We're ready to start the work with a simple plan.")
    chains = root / "chains.toml"
    chains.write_text(
        'schema_version=1\n[[chain]]\nid="article"\norigin="llm"\n'
        'versions=["before.md","after.md"]\n'
    )
    profile = work / "profile/ownvoice"
    run("profile", "--articles", chains)
    run("edit-delta", "--chains", chains)
    stats = chunk.read_json(profile / "profile-stats.json")
    assert stats["registers"]["article"]["derived_from"] is None
    assert stats["registers"]["article"]["n"] == 1
    path = work / "qual/manifest.json"
    run("qual", "chunk", "--records", work / "records.jsonl", "--pass", "A", "--out", path)
    value = manifest.validate(chunk.read_json(path))
    assert value["chunks"], "pipeline must exercise nonempty chunks"
    raw = root / "raw.jsonl"
    write_jsonl(raw, [test_qual.raw_finding(row) for row in value["chunks"]])
    # Stand-in model completion, as in C11. All helper commands remain subprocesses.
    test_qual.finish(path, value)
    grounded, diff, existing = (
        path.parent / n for n in ("grounded.jsonl", "diff.json", "findings-set.json")
    )
    run("qual", "ground", "--manifest", path, "--findings", raw, "--out", grounded)
    assert chunk.read_json(grounded, lines=True)
    run("qual", "reconcile", "--candidate", grounded, "--existing", existing, "--out", diff)
    run("qual", "merge", "--existing", existing, "--add", diff, "--out", existing)
    assert chunk.read_json(existing)["findings"]
    draft = root / "draft.md"
    draft.write_text("Please review the plan and send your thoughts before our next meeting.")
    run(
        "lint",
        draft,
        "--stats",
        profile / "profile-stats.json",
        "--register",
        "client",
        "--medium",
        "email",
        "--out",
        profile / "lint.json",
        codes=(0, 4),
    )
    return root, config, work, rows, value, logs, bodies


def test_pipeline_artifact_contracts(pipeline):
    _, _, work, _, value, _, _ = pipeline
    chunks = {Path(row["text_path"]): row for row in value["chunks"]}
    files = [path for path in work.rglob("*") if path.is_file()]
    assert files
    for path in [work, *work.rglob("*")]:
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600), path
    for path in files:
        assert_marker(path)
        if path in chunks:
            manifest.validate(value)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == chunks[path]["text_sha256"]
            continue
        if path.name == "ingest-report.json":
            validator = (
                ingest_report.validate_merged if path.parent == work else ingest_report.validate
            )
        else:
            assert path.name in SCHEMAS, f"no schema registered for {path}"
            validator = importlib.import_module("ownvoice.schemas." + SCHEMAS[path.name]).validate
        values = (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.suffix == ".jsonl"
            else [json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()]
        )
        for item in values:
            validator(item)


def scan_private(path, names):
    text = path.read_text()
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]+", text), path
    assert not any(domain in text for domain in DOMAINS), path
    items = (
        [json.loads(line) for line in text.splitlines()]
        if path.name in ("records.jsonl", "rejects.jsonl")
        else [text]
    )
    for item in items:
        residual = (
            item.get("scrub", {}).get("residual_capitalised", []) if isinstance(item, dict) else []
        )
        for name in names:
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", json.dumps(item)):
                assert name in residual, (
                    f"unmasked name {name!r} in {path} without same-record residual"
                )


def test_ac3_and_ac18_all_pipeline_outputs(pipeline):
    _, _, work, rows, value, logs, bodies = pipeline
    names = (work / "names.txt").read_text().splitlines()[1:]
    assert "Zorvyn" in names
    for path in work.rglob("*"):
        if path.is_file() and path.name not in (
            "names.txt",
            "domain-map.toml",
            "unmapped-domains.json",
        ):
            scan_private(path, names)
    by_id = {r["record_id"]: r for r in rows}
    chunk_ids = {rid for c in value["chunks"] for rid in c["record_ids"]}
    assert chunk_ids
    assert all(by_id[rid]["source"] == "mail" and not by_id[rid]["sensitive"] for rid in chunk_ids)
    examples = chunk.read_json(work / "profile/ownvoice/exemplars.json")
    for register in examples["registers"].values():
        for item in register["items"]:
            if item["record_id"] in by_id:
                row = by_id[item["record_id"]]
                assert row["source"] == "mail" and not row["sensitive"]
                assert not row["scrub"]["residual_capitalised"]
    llm_text = (work / "profile/ownvoice/stats-llm.json").read_text()
    llm_text += json.dumps(examples)
    llm_text += "".join(Path(c["text_path"]).read_text() for c in value["chunks"])
    for forbidden in (
        "medical diagnosis",
        "updated scope",
        "proposal before the next meeting",
        "Zorvyn",
    ):
        assert forbidden not in llm_text
    for output in logs:
        assert not re.search(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]+", output)
        assert all(body not in output for body in bodies)


def test_every_command_registered_and_no_stub():
    actual = {}

    def visit(parser, prefix=""):
        actual[prefix] = {flag for action in parser._actions for flag in action.option_strings}
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    visit(child, (prefix + " " + name).strip())

    visit(build_parser())
    assert actual == EXPECTED_FRD_COMMANDS
    for path in (ROOT / "ownvoice/commands").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "not_implemented", path
            if isinstance(node, ast.Attribute):
                assert node.attr != "not_implemented", path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "not implemented yet" not in node.value, path


def test_ac12_guard_and_d7_tree():
    result = command("unused", "guard", "--tree", ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    paths = (
        subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        .stdout.decode()
        .split("\0")
    )
    paths = set(filter(None, paths))
    assert not [name for name in paths if artifact_name(name, paths)]


def test_artifact_writers_are_centralized():
    # These are guard input snapshots, an executable and a temporary synthesis probe, not
    # corpus/profile outputs. Bind each exception to its exact call, not a module.
    exceptions = {
        ("guard/__init__.py", "snapshot.write_bytes(data)"),
        ("guard/__init__.py", "hook.write_text(content)"),
        ("qual/synthesis_check.py", "path.write_text(draft, encoding='utf-8')"),
    }
    observed = set()
    for path in (ROOT / "ownvoice").rglob("*.py"):
        if path == ROOT / "ownvoice/io.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            direct = name in {"write", "write_text", "write_bytes", "writelines"}
            if name in {"open", "fdopen"}:
                modes = [
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
                modes += [
                    k.value.value
                    for k in node.keywords
                    if k.arg == "mode" and isinstance(k.value, ast.Constant)
                ]
                direct |= any(any(c in mode for c in "wax+") for mode in modes)
            if direct:
                observed.add((path.relative_to(ROOT / "ownvoice").as_posix(), ast.unparse(node)))
    assert observed == exceptions


@pytest.mark.parametrize("mutation", ["stub", "marker", "next_step", "privacy"])
def test_negative_controls(tmp_path, mutation, monkeypatch, capsys):
    from ownvoice import cli, io
    from ownvoice.commands import profile
    from ownvoice.errors import DiagnosticError

    # Temporary code patches exercise the same assertions used for real outputs.
    if mutation == "stub":

        def stub(args):
            print("not implemented yet", file=sys.stderr)
            return 1

        monkeypatch.setattr(profile, "run", stub)
        code = cli.main(["profile"])
        captured = capsys.readouterr()
        broken = subprocess.CompletedProcess([], code, captured.out, captured.err)
        with pytest.raises(AssertionError):
            assert_implemented(broken)
    elif mutation == "marker":
        monkeypatch.setattr(io, "PRIVATE_KEY", "broken_marker")
        path = tmp_path / "broken.jsonl"
        write_jsonl(path, [{"row": 1}, {"row": 2}])
        with pytest.raises(AssertionError):
            assert_marker(path)
    elif mutation == "next_step":
        original = DiagnosticError.__str__
        monkeypatch.setattr(
            DiagnosticError, "__str__", lambda self: original(self).split("; next step:")[0]
        )
        code = cli.main(["unknown-command"])
        captured = capsys.readouterr()
        broken = subprocess.CompletedProcess([], code, captured.out, captured.err)
        with pytest.raises(AssertionError):
            assert_diagnostic(broken, "parse command arguments", "ownvoice", 2)
    else:
        path = tmp_path / "records.jsonl"
        write_jsonl(path, [{"text": "Zorvyn", "scrub": {"residual_capitalised": []}}])
        with pytest.raises(AssertionError, match="same-record residual"):
            scan_private(path, ["Zorvyn"])


def test_fixture_manifest_f01_through_f53():
    from tests import test_ingest_extract, test_scrub

    inventory = json.loads((ROOT / "tests/fixtures/conformance-manifest.json").read_text())
    assert set(inventory) == {f"F{i:02}" for i in range(1, 54)}
    available = {
        "ingest": {row["id"][:3] for row in test_ingest_extract.cases()},
        "scrub": {row["id"][:3] for row in test_scrub.cases()},
    }
    for identity, entry in inventory.items():
        module_name, *attributes = entry["test"].split("::")
        target = importlib.import_module(module_name)
        for attribute in attributes:
            target = getattr(target, attribute)
        assert callable(target) and attributes[-1].startswith("test_"), entry
        if entry.get("fixtures"):
            assert identity in available[entry["fixtures"]], identity


@pytest.mark.parametrize("mutation", [None, "argument", "drop", "duplicate"])
def test_error_site_inventory(mutation, monkeypatch):
    """Freeze every diagnostic construction and helper call, including fields.

    Unlike a text search for 'next step', this detects a removed constructor
    argument, empty action or changed helper call at the precise error site.
    Runtime boundary cases below also exercise rendering and CLI exit handling.
    """
    from tests.conformance.expected_errors import ERROR_SITES

    if mutation:
        from tests.conformance import expected_errors

        changed = list(ERROR_SITES)
        if mutation == "argument":
            path, expression = changed[0]
            tree = ast.parse(expression)
            tree.body[0].value.args[0] = ast.Constant("changed operation")
            changed[0] = (path, ast.unparse(tree))
        elif mutation == "drop":
            changed.pop()
        else:
            changed.append(changed[0])
        monkeypatch.setattr(expected_errors, "ERROR_SITES", changed)
        with pytest.raises(AssertionError, match="diagnostic paths changed"):
            test_error_site_inventory(None, monkeypatch)
        return

    actual = []
    for path in sorted((ROOT / "ownvoice").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in {"DiagnosticError", "problem", "error", "fail", "constraint"}:
                actual.append((path.relative_to(ROOT).as_posix(), ast.unparse(node)))
                if name == "DiagnosticError":
                    assert len(node.args) == 6, (path, node.lineno)
                    for index in (0, 1, 5):
                        field = node.args[index]
                        if isinstance(field, ast.Constant):
                            assert isinstance(field.value, str) and field.value.strip(), (
                                path,
                                node.lineno,
                            )

    def norm(rows):
        return sorted((path, ast.dump(ast.parse(expression))) for path, expression in rows)

    assert norm(actual) == norm(ERROR_SITES), (
        "diagnostic paths changed; review operation, identity and next step"
    )


@pytest.mark.parametrize(
    "case",
    [
        "pffexport_missing",
        "readpst_missing",
        "pffexport_exit",
        "readpst_exit",
        "budget",
        "register",
    ],
)
def test_documented_error_contract(pipeline, tmp_path, case):
    from tests import test_pst_ingest

    root, config, work, _, _, _, _ = pipeline
    if case.startswith(("pffexport", "readpst")):
        fixture = test_pst_ingest.PstTests()
        fixture.setUp()
        try:
            reader, failure = case.split("_")
            fixture.setup_pst(reader)
            result = fixture.cli(env={"PATH": ""} if failure == "missing" else {"PST_FAIL": "1"})
            assert_diagnostic(result, "ingest", "synthetic", 3)
            assert reader in result.stderr and "mail.pst" in result.stderr
            assert (
                "not found on PATH" if failure == "missing" else "Error opening File"
            ) in result.stderr
        finally:
            fixture.doCleanups()
    elif case == "budget":
        altered = tmp_path / "budget.toml"
        altered.write_text(
            config.read_text()
            .replace('domain_map="map.toml"', f'domain_map="{root / "map.toml"}"')
            .replace('editorial_rules="rules.md"', f'editorial_rules="{root / "rules.md"}"')
            + "\n[profile]\ntoken_budget=1\n"
        )
        result = command(altered, "profile")
        assert_diagnostic(
            result, "profile: token budget exceeded", "stats-llm.json + exemplars.json", 2
        )
    else:
        result = command(
            config,
            "lint",
            root / "draft.md",
            "--stats",
            work / "profile/ownvoice/profile-stats.json",
            "--register",
            "clinet",
            "--medium",
            "email",
        )
        assert_diagnostic(result, "select lint register", "clinet", 2)


@pytest.mark.parametrize(
    "args,operation,identity,code",
    [
        (("ingest",), "load TOML", "c15-absent.toml", 2),
        (("profile",), "load TOML", "c15-absent.toml", 2),
        (
            ("lint", "absent", "--stats", "absent", "--register", "client", "--medium", "email"),
            "load TOML",
            "c15-absent.toml",
            2,
        ),
        (("edit-delta", "--chains", "absent"), "load TOML", "c15-absent.toml", 2),
        (("edit-delta", "discover", "--dir", "absent"), "load TOML", "c15-absent.toml", 2),
        (
            ("edit-delta", "compare", "--pairs", "c15-absent.toml", "--out", "unused"),
            "load TOML",
            "c15-absent.toml",
            2,
        ),
        (
            ("qual", "chunk", "--records", "absent", "--pass", "A", "--out", "unused"),
            "load TOML",
            "c15-absent.toml",
            2,
        ),
        (
            ("qual", "status", "--manifest", "c15-absent.json"),
            "read qual input",
            "c15-absent.json",
            3,
        ),
        (
            (
                "qual",
                "ground",
                "--manifest",
                "c15-absent.json",
                "--findings",
                "absent",
                "--out",
                "unused",
            ),
            "read qual input",
            "c15-absent.json",
            3,
        ),
        (
            (
                "qual",
                "reconcile",
                "--candidate",
                "c15-absent.jsonl",
                "--existing",
                "absent",
                "--out",
                "unused",
            ),
            "read qual input",
            "c15-absent.jsonl",
            3,
        ),
        (
            (
                "qual",
                "merge",
                "--existing",
                "absent",
                "--add",
                "c15-absent.json",
                "--out",
                "unused",
            ),
            "read qual input",
            "c15-absent.json",
            3,
        ),
        (("clean", "--all"), "load TOML", "c15-absent.toml", 2),
        (("config", "show"), "load TOML", "c15-absent.toml", 2),
    ],
)
def test_command_error_boundaries(args, operation, identity, code, tmp_path):
    result = command(tmp_path / "c15-absent.toml", *args)
    assert_implemented(result)
    assert_diagnostic(result, operation, identity, code)


def test_ac3_lint_artefact_scrubs_correspondent_heading():
    fixture = test_lint.LintTests()
    fixture.setUp()
    try:
        fixture.profile()
        write_marked_text(fixture.work / "names.txt", "Zorvyn\n")
        output = fixture.work / "profile" / "ownvoice" / "lint.json"
        result = fixture.run_lint(
            "# Zorvyn zorvyn@example.net\nPlease review the plan.",
            "schema_version = 1\n[limits.email]\nheadings_allowed = false",
            "--out",
            str(output),
        )
        assert result.returncode == 4, result.stderr
        report = json.loads(output.read_text())
        headings = [
            finding
            for finding in report["findings"]
            if finding["rule_id"] == "rules.headings_allowed"
        ]
        assert len(headings) == 1
        assert headings[0]["locations"], "fixture must exercise a persisted heading excerpt"
        leaked = [
            token
            for token in ("Zorvyn", "zorvyn@example.net", "example.net")
            if token in output.read_text()
        ]
        assert not leaked, (
            f"scan lint artefact [{output}]: raw third-party identifiers {leaked!r}; "
            "expected AC-3 masking in every written lint finding; next step: "
            "repair C9 lint report serialization before completing C15"
        )
    finally:
        fixture.doCleanups()
