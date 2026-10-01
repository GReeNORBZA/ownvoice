"""Code-owned two-pass extraction and one-call private profile synthesis."""

import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path

from ownvoice import provenance
from ownvoice.cli import Parser
from ownvoice.cli import main as ownvoice
from ownvoice.config import load_config
from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors, internal_error
from ownvoice.io import (
    PRIVATE_LINE,
    inside_git_worktree,
    write_json,
    write_jsonl,
    write_marked_text,
)
from ownvoice.layout import Layout
from ownvoice.qual import chunk, cross_register, ground, merge, reconcile, sample, synthesis_check
from ownvoice.schemas import (
    article_records,
    common,
    edit_delta,
    exemplars,
    finding,
    findings_set,
    ingest_report,
    profile_stats,
    stats_llm,
)
from ownvoice.style import budget


def delimit(text, label="DATA"):
    token = label + "_" + chunk.digest(text)
    while token in text:
        token += "_"
    return f"BEGIN_{token}\n{text}\nEND_{token}"


def invoke(adapter, executable, prompt, diagnostic):
    """All content goes through stdin, never argv or orchestrator stdout."""
    with tempfile.TemporaryDirectory(prefix="ownvoice-model-") as directory:
        cwd = Path(directory) / "empty"
        cwd.mkdir(mode=0o700)
        final = Path(directory) / "final.txt"
        if adapter == "claude":
            command = [
                executable,
                "--print",
                "--output-format",
                "text",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--setting-sources",
                "",
                "--disable-slash-commands",
                "--no-session-persistence",
                "--permission-mode",
                "dontAsk",
            ]
        else:
            command = [
                executable,
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "-c",
                'approval_policy="never"',
                "-c",
                'web_search="disabled"',
                "-c",
                "sandbox_workspace_write.network_access=false",
                "-c",
                "features.shell_tool=false",
                "-c",
                "features.apps=false",
                "-c",
                "features.multi_agent=false",
                "-c",
                "mcp_servers={}",
                "--output-last-message",
                str(final),
                "-",
            ]
        try:
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=cwd,
                timeout=600,
                check=False,
            )
            if result.returncode:
                cause = subprocess.CalledProcessError(
                    result.returncode, command, stderr=result.stderr
                )
                raise chunk.problem(
                    "call profile model",
                    adapter,
                    f"exit {result.returncode}; stderr: {result.stderr}",
                    "exit 0",
                    "check the harness authentication and restrictive-mode support",
                    cause,
                ) from cause
            return chunk.read_text(final) if adapter == "codex" else result.stdout
        except (OSError, subprocess.TimeoutExpired, DiagnosticError) as exc:
            # Harness stderr may contain email text. Keep the complete cause
            # privately and emit only its path to the orchestrator.
            write_marked_text(diagnostic, str(exc))
            raise DiagnosticError(
                "call profile model",
                adapter,
                f"call did not complete; details in {diagnostic}",
                "exit 0 and a final text response",
                None,
                "inspect the private diagnostic and repair the harness before retrying",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc


def command(arguments):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        status = ownvoice(arguments)
    if status:
        raise DiagnosticError(
            "run profile helper",
            arguments[0],
            f"exit {status}",
            "exit 0",
            output.getvalue(),
            "repair the helper input before rebuilding the profile",
            exit_code=ExitCode(status),
        )


def parse_findings(response):
    """Return (findings, rejections) from one JSONL response.

    A line that is not a JSON object makes the whole response invalid (prose,
    fences or commentary). A well-formed object that fails the finding schema,
    such as a quote over 25 words, is dropped alone and counted, so one bad
    finding no longer discards the rest. A response whose every line is
    rejected is still invalid and retried.
    """
    items, rejections = [], []
    lines = [line for line in response.splitlines() if line.strip()]
    for number, line in enumerate(lines, 1):
        fields = json.loads(line)
        if not isinstance(fields, dict):
            raise TypeError(f"line {number} is not a JSON object")
        try:
            items.append(finding.build(**fields))
        except (TypeError, ValidationErrors) as exc:
            rejections.append(f"line {number}: {exc}")
    if lines and not items:
        raise ValueError(f"all {len(lines)} findings failed the finding schema")
    return items, rejections


def extract_framing(row, framing, text, prompt, adapter, executable, retries, directory):
    """Run one chunk framing with its retries. Safe to run concurrently.

    Returns (items or None when exhausted, attempts, dropped count, progress notes).
    """
    framing_prompt = prompt.split(f"<!-- framing-{framing} -->")[1].split("<!--")[0]
    request = (
        framing_prompt
        + "\nUse this chunk_id: "
        + row["chunk_id"]
        + "\nAllowed registers: "
        + ", ".join(row["registers"])
        + "\n"
        + delimit(text)
    )
    notes = []
    for attempt in range(retries + 1):
        diagnostic = directory / f"{row['chunk_id']}.{framing}.{attempt}.diagnostic.md"
        try:
            response = invoke(adapter, executable, request, diagnostic)
            items, rejections = parse_findings(response)
        except (ValueError, TypeError, ValidationErrors, DiagnosticError) as exc:
            write_marked_text(diagnostic, str(exc))
            notes.append(
                f"framing {framing} attempt {attempt + 1}/{retries + 1}; "
                f"invalid return, expected finding JSONL; inspect {diagnostic.name}"
            )
            continue
        if rejections:
            write_marked_text(diagnostic, "\n".join(rejections))
            notes.append(
                f"framing {framing} attempt {attempt + 1}/{retries + 1}; "
                f"dropped {len(rejections)} schema-invalid findings; inspect {diagnostic.name}"
            )
        return items, attempt + 1, len(rejections), notes
    return None, retries + 1, 0, notes


def dispatch_manifest(path, prompt, adapter, executable, retries, concurrency=1):
    value = chunk.load(path)
    chunk.listed_paths(path, value)
    total = len(value["chunks"])
    texts = {}
    for row in value["chunks"]:
        text = chunk.read_text(row["text_path"])
        if chunk.digest(text) != row["text_sha256"]:
            raise chunk.problem(
                "dispatch qual chunk",
                row["chunk_id"],
                "text digest changed",
                "the original masked chunk",
                "regenerate the manifest and chunks",
            )
        texts[row["chunk_id"]] = text
    results, dropped, done_findings = {}, 0, 0
    # Workers only call the model and write their own diagnostics. Manifest,
    # raw-file writes and progress stay on this thread.
    pool = ThreadPoolExecutor(max_workers=concurrency)
    try:
        jobs = {
            pool.submit(
                extract_framing,
                row,
                framing,
                texts[row["chunk_id"]],
                prompt,
                adapter,
                executable,
                retries,
                path.parent,
            ): (index, row, framing, raw_path)
            for index, row in enumerate(value["chunks"], 1)
            for framing, raw_path in enumerate(row["raw_paths"], 1)
        }
        for job in as_completed(jobs):
            index, row, framing, raw_path = jobs[job]
            items, attempts, rejected, notes = job.result()
            for note in notes:
                print(f"qual pass {value['pass']}: chunk {index}/{total} {note}", file=sys.stderr)
            # Valid empty raw file is distinct from failed status in manifest.
            write_jsonl(raw_path, items or [])
            dropped += rejected
            row["attempts"] = max(row["attempts"], attempts)
            results[row["chunk_id"], framing] = items
            if all((row["chunk_id"], f) in results for f in (1, 2)):
                framings = [results[row["chunk_id"], f] for f in (1, 2)]
                row["status"] = "done" if all(f is not None for f in framings) else "failed"
                if row["status"] == "done":
                    done_findings += sum(len(f) for f in framings)
                print(
                    f"qual pass {value['pass']}: chunk {index}/{total} {row['status']}, "
                    f"findings {done_findings}, failed {chunk.counts(value)['failed']}",
                    file=sys.stderr,
                )
            write_json(path, value)
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    # Candidate order is chunk then framing order, independent of completion order.
    all_findings = [
        item
        for row in value["chunks"]
        if row["status"] == "done"
        for framing in (1, 2)
        for item in results[row["chunk_id"], framing]
    ]
    candidates = path.parent / f"{value['pass']}.candidates.jsonl"
    write_jsonl(candidates, all_findings)
    return value, candidates, dropped


def resumable_run(path, directory, config):
    """Validate a prior synthesis run whose Stage Q passes completed.

    Resuming repeats only Stage S. The run must sit in this profile directory,
    hold both pass manifests and the merged findings, and have been planned
    under the current config, domain map, rules and tool version.
    """
    run = path.resolve()
    required = [run / name for name in ("A.manifest.json", "B.manifest.json", "findings-set.json")]
    if (
        run.parent != directory.resolve()
        or not run.name.startswith("synthesis-")
        or not all(item.is_file() for item in required)
    ):
        raise chunk.problem(
            "resume profile synthesis",
            path,
            "not a completed Stage Q run in this profile directory",
            "a synthesis-* run holding A/B manifests and findings-set.json",
            "run voice-profile-build without --resume-run",
        )
    expected = provenance.build(
        config, config["paths"]["domain_map"], config["paths"]["editorial_rules"]
    )
    for manifest in required[:2]:
        value = chunk.load(manifest)
        stale = [
            key
            for key in ("config_digest", "domain_map_digest", "rules_sha256", "tool_version")
            if value[key] != expected[key]
        ]
        if stale:
            raise chunk.problem(
                "resume profile synthesis",
                manifest,
                "run planned under different inputs: " + ", ".join(stale),
                "the current config, domain map, rules and tool digests",
                "run voice-profile-build without --resume-run",
            )
    return run


def recorded_drops(run):
    """Count schema-invalid findings dropped in a run from its private diagnostics."""
    return sum(
        len(re.findall(r"(?m)^line \d+: ", chunk.read_text(path)))
        for path in run.glob("*.diagnostic.md")
    )


def top_findings(value):
    confidence = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        value["findings"],
        key=lambda row: (
            -len({p["record_id"] for p in row["provenance"]}),
            confidence[row["confidence"]],
            min(p["record_id"] for p in row["provenance"]),
            row["finding_id"],
        ),
    )[:80]


def preflight(config, directory):
    names = Layout(Path(config["paths"]["work_dir"])).names
    errors = []
    if not names.is_file():
        errors.append(
            chunk.problem(
                "preflight profile synthesis",
                names,
                "names.txt is missing",
                "an existing names.txt",
                "run ingest to create the private names list before building a profile",
            )
        )
    if inside_git_worktree(directory):
        errors.append(
            chunk.problem(
                "preflight profile synthesis",
                directory,
                "profile dir is inside a git working tree",
                "a private profile directory outside git",
                "choose an external --profile-dir",
            )
        )
    if errors:
        raise ValidationErrors(errors)
    return names


def load_inputs(config, directory):
    inputs = {}
    for filename, schema in (
        ("profile-stats.json", profile_stats),
        ("stats-llm.json", stats_llm),
        ("exemplars.json", exemplars),
    ):
        value = schema.validate(chunk.read_json(directory / filename))
        if filename == "profile-stats.json":
            for label in value["corpus"]["sources"]:
                report = ingest_report.validate(
                    chunk.read_json(
                        Layout(Path(config["paths"]["work_dir"])).source_paths(label)["report"]
                    )
                )
                provenance.require_scrub(config, report, label)
        expected = provenance.build(
            config, config["paths"]["domain_map"], config["paths"]["editorial_rules"]
        )
        if any(
            value[key] != expected[key]
            for key in ("config_digest", "domain_map_digest", "rules_sha256", "tool_version")
        ):
            raise chunk.problem(
                "bind synthesis inputs",
                directory / filename,
                "input provenance is stale",
                "current config, domain map, rules and tool digests",
                "rerun ownvoice profile with the current config before synthesis",
            )
        inputs[filename] = value
    return inputs


def load_profiled_records(directory, stats):
    binding = stats.get("profiled_records")
    if not binding:
        raise chunk.problem(
            "bind synthesis profiled records",
            directory / "profile-stats.json",
            "profiled_records SHA-256 binding is missing",
            "a file and SHA-256 bound by profile",
            "rerun ownvoice profile with the selected inputs before synthesis",
        )
    path = directory / binding["file"]
    if not path.resolve().is_relative_to(directory.resolve()):
        raise chunk.problem(
            "bind synthesis profiled records",
            path,
            "SHA-256 bound path escapes profile directory",
            "a bound file inside the profile directory",
            "rerun ownvoice profile with the selected inputs before synthesis",
        )
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DiagnosticError(
            "bind synthesis profiled records",
            path,
            str(exc),
            "a readable SHA-256 bound records file",
            exc,
            "rerun ownvoice profile with the selected inputs before synthesis",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    if actual != binding["sha256"]:
        raise chunk.problem(
            "bind synthesis profiled records",
            path,
            f"SHA-256 {actual}",
            f"SHA-256 {binding['sha256']}",
            "rerun ownvoice profile with the selected inputs before synthesis",
        )
    return path


def load_edit_delta(directory, stats, *, config=None):
    def validate(value, path):
        value = edit_delta.validate(value)
        expected = (
            provenance.config_digest(config) if config is not None else stats["config_digest"]
        )
        if value["config_digest"] != expected:
            raise chunk.problem(
                "validate artefact policy",
                path,
                "recorded edit-delta config digest is stale",
                "current file-backed input content digests",
                "run ownvoice edit-delta with the current config, then ownvoice profile --edit-delta",
            )
        return value

    binding = stats.get("edit_delta")
    if not binding:
        path = directory / "edit-delta.json"
        return validate(chunk.read_json(path), path) if path.exists() else None
    path = directory / binding["file"]
    if not path.resolve().is_relative_to(directory.resolve()):
        raise chunk.problem(
            "bind synthesis edit delta",
            path,
            "bound path escapes profile directory",
            "a private artefact inside the profile directory",
            "rerun ownvoice profile with --edit-delta to restore the binding",
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise DiagnosticError(
            "bind synthesis edit delta",
            path,
            str(exc),
            "a readable bound artefact",
            exc,
            "rerun ownvoice profile with --edit-delta to restore the bound artefact",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    actual = hashlib.sha256(content).hexdigest()
    if actual != binding["sha256"]:
        raise chunk.problem(
            "bind synthesis edit delta",
            path,
            f"SHA-256 {actual}",
            f"SHA-256 {binding['sha256']}",
            "rerun ownvoice profile with --edit-delta to restore the binding",
        )
    return validate(json.loads(content), path)


def load_profiled_articles(directory, stats):
    binding = stats.get("profiled_articles")
    if binding is None:
        return None
    path = directory / binding["file"]
    if not path.resolve().is_relative_to(directory.resolve()):
        raise chunk.problem(
            "bind synthesis profiled articles",
            path,
            "bound path escapes profile directory",
            "a bound file inside the profile directory",
            "rerun ownvoice profile --articles with the selected chains",
        )
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DiagnosticError(
            "bind synthesis profiled articles",
            path,
            str(exc),
            "a readable SHA-256 bound articles file",
            exc,
            "rerun ownvoice profile --articles with the selected chains",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    if actual != binding["sha256"]:
        raise chunk.problem(
            "bind synthesis profiled articles",
            path,
            f"SHA-256 {actual}",
            f"SHA-256 {binding['sha256']}",
            "rerun ownvoice profile --articles with the selected chains",
        )
    for row in chunk.read_json(path, lines=True):
        article_records.validate(row)
    return path


def plan_passes(
    config_path, config, records_path, articles_path, run, call_cap=budget.STAGE_Q_CALL_CAP
):
    original = config["profile"]["qual_sample_words"]
    email_sample_words = original
    while True:
        plans = []
        for pass_name in ("A", "B"):
            path = run / f"{pass_name}.manifest.json"
            arguments = [
                "--config",
                str(config_path),
                "qual",
                "chunk",
                "--records",
                str(records_path),
                "--pass",
                pass_name,
                "--out",
                str(path),
            ]
            if articles_path is not None:
                arguments += ["--articles", str(articles_path)]
            if email_sample_words != original:
                arguments += ["--sample-words", str(email_sample_words)]
            command(arguments)
            plans.append(path)
        planned_calls = 2 * sum(len(chunk.load(path)["chunks"]) for path in plans)
        if planned_calls <= call_cap:
            return plans, email_sample_words, planned_calls
        if email_sample_words <= max(1, original * 0.1):
            raise chunk.problem(
                "plan qualitative calls",
                run,
                f"planned calls {planned_calls} at email sample {email_sample_words} words",
                f"at most {call_cap} calls",
                "reduce the article input or revise the qualitative sample before rebuilding",
            )
        # Clean discarded plans while their manifests still own every chunk.
        # The next iteration recreates any chunks shared with the final sample.
        for path in plans:
            command(["clean", "--chunks", str(path)])
        email_sample_words = max(1, email_sample_words * 9 // 10)


def quote_has_block_boundary(text):
    # Grounding does not make Markdown structure safe. splitlines also covers
    # the line separators used by the writing-brief extractor.
    return any(
        re.match(
            r"^\s*(?:#{1,6}(?:\s|$)|`{3}|~{3}|[<>]|[-+*](?:\s|$)|"
            r"[0-9]{1,9}[.)]\s|\[[^\]]+\]:|(?:[_*-][ \t]*){3,}$|[=-]+[ \t]*$)",
            line,
        )
        for line in text.splitlines()
    )


def core_voice(value, groups):
    if not groups:
        return []
    by_id = {group["group_id"]: group for group in groups}
    invalid = []
    if not isinstance(value, list) or not value:
        invalid = sorted(by_id)
    else:
        for item in value:
            identifier = item.get("group_id") if isinstance(item, dict) else None
            valid = isinstance(identifier, str) and identifier in by_id
            if valid:
                quotes = item.get("quotes")
                pattern = item.get("pattern")
                valid = (
                    set(item) == {"group_id", "pattern", "quotes"}
                    and isinstance(pattern, str)
                    and bool(pattern.strip())
                    and pattern.splitlines() == [pattern]
                    and isinstance(quotes, list)
                    and 2 <= len(quotes) <= 3
                )
                if valid:
                    allowed = {
                        (q["register"], q["verbatim_quote"]) for q in by_id[identifier]["quotes"]
                    }
                    valid = all(
                        isinstance(q, dict)
                        and set(q) == {"register", "quote"}
                        and isinstance(q["register"], str)
                        and isinstance(q["quote"], str)
                        and (q["register"], q["quote"]) in allowed
                        and not quote_has_block_boundary(q["quote"])
                        for q in quotes
                    )
                    valid = valid and len({q["register"] for q in quotes}) >= 2
            if not valid:
                invalid.append(
                    identifier
                    if isinstance(identifier, str) and re.fullmatch(r"[a-f0-9]{64}", identifier)
                    else "unknown-group"
                )
    if invalid:
        raise chunk.problem(
            "validate core voice",
            ", ".join(sorted(set(invalid))),
            "response contains an empty core_voice list"
            if value == []
            else "response contains ungrounded or invalid patterns, or structural Markdown quotes",
            "at least one pattern, each with 2-3 exact group quotes from at least two registers "
            "and no Markdown block boundaries in quotes",
            "regenerate Stage S using only the named cross-register groups",
        )
    return value


def unfence(response):
    """Strip one outer Markdown code fence around the whole reply, if present."""
    match = re.fullmatch(r"\s*```[A-Za-z]*\n(.*)\n```\s*", response, re.DOTALL)
    return match[1] if match else response


def parse_sections(response, registers, groups=None):
    try:
        value = json.loads(unfence(response))
        assert isinstance(value, dict) and set(value) in (
            {"1", "2", "3", "5"},
            {"1", "2", "3", "5", "core_voice"},
        )
        assert all(isinstance(value[key], str) and value[key].strip() for key in ("1", "3", "5"))
        assert isinstance(value["2"], dict) and set(value["2"]) == set(registers)
        assert all(isinstance(v, str) and v.strip() for v in value["2"].values())
        assert not any(
            re.match(r"^\s*#{1,2}(?:\s|$)", line)
            for v in (value["1"], *value["2"].values(), value["3"], value["5"])
            for line in v.splitlines()
        )
        value["core_voice"] = core_voice(value.get("core_voice"), groups or [])
        return value
    except (ValueError, AssertionError, TypeError) as exc:
        raise chunk.problem(
            "parse synthesis response",
            "Stage S",
            "response violates section contract",
            "JSON sections 1, 2 (every register), 3, 5 with nonempty Markdown and no H1/H2",
            "correct the model response contract and regenerate",
            exc,
        ) from exc


def assemble(sections, facts, contrast, rules, hashes):
    text = "## 0. Provenance\n\n" + json.dumps(facts, ensure_ascii=False, indent=2) + "\n\n"
    text += "## 1. Precedence and use\n\n" + sections["1"]
    text += (
        "\n\nCore voice is qualitative, and a register section overrides it where they conflict."
    )
    text += "\n\n## Core voice\n\n"
    if facts["profile_mode"] == "stats-only profile":
        text += "Unavailable: stats-only profile."
    elif not sections.get("core_voice"):
        text += "Unavailable: no qualitative pattern was grounded in two or more registers."
    else:
        text += "\n".join(
            f"- **{item['pattern']}**\n"
            + "\n".join(
                f'  - {quote["register"]}: "' + "\n    ".join(quote["quote"].splitlines()) + '"'
                for quote in item["quotes"]
            )
            for item in sections["core_voice"]
        )
    text += "\n\n## 2. Per register\n\n"
    for register, body in sections["2"].items():
        text += f"### {register}\n\n{body}\n\n"
    text += "### Per-source contrast\n\n"
    text += "| Register | Metric | Source medians | Merged IQR | Status | Default source |\n"
    text += "| --- | --- | --- | --- | --- | --- |\n"
    for row in contrast:
        text += (
            "| "
            + " | ".join(
                str(value)
                for value in (
                    row["register"],
                    row["metric"],
                    json.dumps(row["p50_by_source"], sort_keys=True),
                    row["iqr_merged"],
                    row["status"],
                    row["default_source"],
                )
            )
            + " |\n"
        )
    text += "\n## 3. Edit-delta tendencies\n\n" + sections["3"]
    text += "\n\n## 4. Editorial rules\n\n" + rules
    text += "\n\n## 5. Anti-patterns\n\n" + sections["5"]
    text += "\n\n## 6. Lint reference\n\n"
    text += "\n".join(f"{name}: SHA-256 {digest}" for name, digest in hashes.items()) + "\n"
    return text


def publish(directory, draft, timestamp):
    path = directory / "voice-profile.md"
    if path.exists():
        previous = chunk.read_text(path)
        match = re.search(r'"generated_at": "([0-9T:.Z+-]+)"', previous)
        if not previous.startswith(PRIVATE_LINE + "\n") or not match:
            raise chunk.problem(
                "archive voice profile",
                path,
                "previous profile lacks marker or generation date",
                "a generated private voice profile",
                "move the unrecognized file aside privately",
            )
        historical = directory / f"voice-profile.{match[1]}.md"
        if historical.exists() and chunk.read_text(historical) != previous:
            raise chunk.problem(
                "archive voice profile",
                historical,
                "timestamp already has different content",
                "an immutable historical profile",
                "inspect the conflicting private history",
            )
        if not historical.exists():
            write_marked_text(historical, previous.split("\n", 1)[1])
    write_marked_text(path, draft)
    for old in sorted(directory.glob("voice-profile.*.md"))[:-3]:
        old.unlink()


def build(args):
    config, _ = load_config(args.config)
    layout = Layout(Path(config["paths"]["work_dir"]))
    directory = (
        Path(args.profile_dir).expanduser().resolve() if args.profile_dir else layout.profile_dir
    )
    names = preflight(config, directory)
    inputs = load_inputs(config, directory)
    stats = inputs["profile-stats.json"]
    profiled_records = load_profiled_records(directory, stats)
    profiled_articles = load_profiled_articles(directory, stats)
    article_record_ids = (
        {row["record_id"] for row in chunk.read_json(profiled_articles, lines=True)}
        if profiled_articles is not None
        else set()
    )
    delta = load_edit_delta(directory, stats, config=config)
    eligible = {
        source["label"]
        for source in config["source"]
        if source["llm_eligible"] and source["label"] in stats["corpus"]["sources"]
    }
    dispatched_sources = set()
    dispatched_chunks = 0
    resume = getattr(args, "resume_run", None)
    if resume:
        run = resumable_run(Path(resume).expanduser(), directory, config)
    else:
        # A new private run avoids consuming stale passes or deleting prior evidence.
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        run = Path(tempfile.mkdtemp(prefix="synthesis-", dir=directory))
    prompt = chunk.read_text(args.prompt)
    rules = chunk.read_text(config["paths"]["editorial_rules"])
    findings = reconcile.empty(stats)
    manifests, sources, samples = [], [], {}
    groups = []
    email_sample_words = config["profile"]["qual_sample_words"]
    planned_calls = 0
    dropped_findings = 0
    if eligible and resume:
        # Stage Q already completed in this run; only Stage S is repeated.
        plans = [run / f"{pass_name}.manifest.json" for pass_name in ("A", "B")]
        loaded = [chunk.load(path) for path in plans]
        email_sample_words = loaded[0]["sample_words"]
        planned_calls = 2 * sum(len(value["chunks"]) for value in loaded)
        dropped_findings = recorded_drops(run)
        for pass_name, manifest, value in zip(("A", "B"), plans, loaded, strict=True):
            manifests.append(manifest)
            dispatched_chunks += len(value["chunks"])
            article_chunks = 0
            for row in value["chunks"]:
                if set(row["record_ids"]) <= article_record_ids:
                    article_chunks += 1
                else:
                    dispatched_sources.add(row["source"])
            samples[pass_name] = {
                "chunks": len(value["chunks"]),
                "records": sum(len(row["record_ids"]) for row in value["chunks"]),
                "estimated_tokens": sum(row["est_tokens"] for row in value["chunks"]),
            }
            if profiled_articles is not None:
                samples[pass_name].update(
                    article_chunks=article_chunks,
                    email_chunks=len(value["chunks"]) - article_chunks,
                )
            for row in value["chunks"]:
                text = chunk.read_text(row["text_path"])
                if chunk.digest(text) != row["text_sha256"]:
                    raise chunk.problem(
                        "resume profile synthesis",
                        row["chunk_id"],
                        "chunk text digest changed",
                        "the original masked chunk",
                        "run voice-profile-build without --resume-run",
                    )
                sources.append(text)
        existing = run / "findings-set.json"
        findings = findings_set.validate(chunk.read_json(existing))
        groups = cross_register.run(existing, run / "cross-register.json")
    elif eligible:
        plans, email_sample_words, planned_calls = plan_passes(
            args.config, config, profiled_records, profiled_articles, run
        )
        for pass_name, manifest in zip(("A", "B"), plans, strict=True):
            value, candidates, dropped = dispatch_manifest(
                manifest,
                prompt,
                args.adapter,
                args.executable or args.adapter,
                config["profile"]["qual_retries"],
                getattr(args, "concurrency", 1),
            )
            manifests.append(manifest)
            dispatched_chunks += len(value["chunks"])
            article_chunks = 0
            for row in value["chunks"]:
                if set(row["record_ids"]) <= article_record_ids:
                    article_chunks += 1
                else:
                    dispatched_sources.add(row["source"])
            samples[pass_name] = {
                "chunks": len(value["chunks"]),
                "records": sum(len(row["record_ids"]) for row in value["chunks"]),
                "estimated_tokens": sum(row["est_tokens"] for row in value["chunks"]),
            }
            dropped_findings += dropped
            if profiled_articles is not None:
                samples[pass_name].update(
                    article_chunks=article_chunks,
                    email_chunks=len(value["chunks"]) - article_chunks,
                )
            sources.extend(chunk.read_text(row["text_path"]) for row in value["chunks"])
            grounded = run / f"{pass_name}.grounded.jsonl"
            ground.run(manifest, candidates, grounded, 0.85)
            existing = run / "findings-set.json"
            diff = run / f"{pass_name}.diff.json"
            reconcile.run(grounded, existing, diff)
            findings = merge.run(existing, diff, existing)
        groups = cross_register.run(existing, run / "cross-register.json")
    projection = deepcopy(inputs["stats-llm.json"])
    examples = inputs["exemplars.json"] if eligible else None
    if not eligible:
        for register in projection["registers"].values():
            for key in (
                "greetings",
                "signoffs",
                "ngrams",
                "discourse_markers",
                "hedges",
                "function_words",
                "llm_ism_never_hit",
            ):
                register.pop(key, None)
            register["llm_ism_hits"] = []
    if examples:
        for name, register in examples["registers"].items():
            for item in register["items"]:
                article_exemplar = (
                    profiled_articles is not None
                    and name == "article"
                    and item["source"] == "articles"
                )
                if item["source"] not in eligible and not article_exemplar:
                    raise chunk.problem(
                        "select synthesis exemplar",
                        item["record_id"],
                        "source is not eligible",
                        "an eligible source",
                        "rerun ownvoice profile before synthesis",
                    )
                sources.append(item["text"])
    if delta:
        for item in delta["examples"]:
            sources.extend((item["before"], item["after"]))
    timestamp = provenance.generated_at()
    facts = {
        **{
            key: stats[key]
            for key in common.PROVENANCE
            if key != common.PRIVATE_KEY and key in stats
        },
        "generated_at": timestamp,
        "corpus": stats["corpus"],
        "llm_eligible": sorted(dispatched_sources),
        "llm": config["llm"],
        "profile_mode": "qualitative profile" if dispatched_chunks else "stats-only profile",
        "sample_sizes": samples,
        "passes": findings["passes"],
        "residual": findings["residual"],
        "unresolved_failed": findings["unresolved_failed"],
        "stage_q_dropped_findings": dropped_findings,
    }
    if profiled_articles is not None:
        article_sample = (
            sample.articles(
                chunk.read_json(profiled_articles, lines=True),
                config["profile"]["qual_sample_words"],
                config["profile"]["qual_max_record_words"],
            )
            if eligible
            else []
        )
        facts.update(
            email_sample_words=email_sample_words,
            stage_q_planned_calls=planned_calls,
            stage_q_call_cap=budget.STAGE_Q_CALL_CAP,
            article_records=len(article_sample),
            article_records_truncated=sum(row["truncated"] for row in article_sample),
        )
    payload = {
        "stats": projection,
        "findings": top_findings(findings),
        "edit_delta": delta,
        "rules": rules,
        "provenance": facts,
    }
    if examples is not None:
        payload["exemplars"] = examples
    synthesis_prompt = prompt.split("<!-- synthesis -->")[1] + "\n"
    cross_block = delimit(json.dumps(groups), "CROSS_REGISTER")
    payload["cross_register"] = groups
    estimated_total = budget.estimate_synthesis(
        payload, synthesis_prompt + delimit("") + delimit("", "CROSS_REGISTER")
    )
    del payload["cross_register"]
    ceiling = budget.STAGE_S_TOKEN_BUDGET
    if estimated_total > ceiling:
        raise chunk.problem(
            "budget synthesis input",
            "Stage S",
            f"estimated {estimated_total:,} tokens",
            f"at most {ceiling:,} estimated tokens",
            "reduce exemplars or qualitative sample size before rebuilding",
        )
    request = synthesis_prompt + cross_block + "\n" + delimit(json.dumps(payload))
    attempts = config["profile"]["qual_retries"] + 1
    for attempt in range(1, attempts + 1):
        response = invoke(
            args.adapter, args.executable or args.adapter, request, run / "S.diagnostic.md"
        )
        try:
            sections = parse_sections(
                response,
                set(projection["registers"]) - {"_global"},
                groups if dispatched_chunks else [],
            )
            hashes = {
                name: provenance.file_sha256(directory / name)
                for name in ("profile-stats.json", "stats-llm.json")
            }
            draft = assemble(sections, facts, stats["contrast"], rules, hashes)
            quoted_text = "\n".join(
                (sections["1"], *sections["2"].values(), sections["3"], sections["5"])
            )
            quoted_text += "\n" + "\n".join(item["pattern"] for item in sections["core_voice"])
            synthesis_check.check(draft, names, sources, quoted_text=quoted_text)
            break
        except (DiagnosticError, ValidationErrors) as exc:
            # Keep every rejected reply and reason privately so causes can be read.
            write_marked_text(run / f"S.check.{attempt}.md", str(exc))
            write_marked_text(run / f"S.response.{attempt}.md", response)
            diagnostic = run / "S.check.md"
            write_marked_text(diagnostic, str(exc))
            write_marked_text(run / "S.response.md", response)
            if attempt < attempts:
                print(
                    f"Stage S attempt {attempt}/{attempts}: draft rejected; "
                    f"inspect {diagnostic.name}; retrying",
                    file=sys.stderr,
                )
                continue
            raise chunk.problem(
                "validate profile synthesis",
                "Stage S",
                f"draft rejected after {attempts} attempts; spans in {diagnostic}",
                "a grounded, names-free draft matching the section contract",
                "inspect the private diagnostic and regenerate the profile",
            ) from exc
    publish(directory, draft, timestamp)
    for manifest in manifests:
        command(["clean", "--chunks", str(manifest)])
    print(f"voice-profile-build: {facts['profile_mode']}; passes {len(manifests)}; profile written")
    return 0


def main(argv=None):
    parser = Parser(prog="voice-profile-build")
    parser.add_argument(
        "--config", default=os.environ.get("OWNVOICE_CONFIG", "~/.config/ownvoice/config.toml")
    )
    parser.add_argument("--profile-dir")
    parser.add_argument("--adapter", choices=("claude", "codex"), required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--executable", help="Harness executable, or scripted fixture stand-in")
    parser.add_argument(
        "--concurrency",
        type=int,
        choices=range(1, 9),
        default=1,
        metavar="1-8",
        help="Stage Q model calls in flight at once (default 1, sequential)",
    )
    parser.add_argument(
        "--resume-run",
        metavar="DIR",
        help="Repeat only Stage S on a prior synthesis-* run whose Stage Q passes completed",
    )
    parser.add_argument("--verbose", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.verbose:
            print(f"voice-profile-build: adapter={args.adapter}; preflight inputs", file=sys.stderr)
        return build(args)
    except (DiagnosticError, ValidationErrors) as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
    except OSError as exc:
        print(
            DiagnosticError(
                "build voice profile",
                exc.filename or "private profile directory",
                str(exc),
                "readable inputs and writable private output",
                exc,
                "check the named path and permissions, then retry with --verbose",
                exit_code=ExitCode.DEPENDENCY,
            ),
            file=sys.stderr,
        )
        return int(ExitCode.DEPENDENCY)
    except Exception as exc:  # noqa: BLE001 - CLI boundary preserves the internal-error diagnostic.
        print(internal_error("build voice profile", "voice-profile-build", exc), file=sys.stderr)
        return int(ExitCode.INTERNAL)
