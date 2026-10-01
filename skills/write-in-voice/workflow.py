"""Harness-neutral reference loop; the active harness supplies the model callback."""

import json
import re
import subprocess
import sys
from pathlib import Path

from ownvoice.cli import Parser
from ownvoice.errors import DiagnosticError, ValidationErrors
from ownvoice.io import _atomic_write
from ownvoice.schemas import lint

CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text())


def brief_sections(profile_text, register):
    """Return only the four writing sections, with their original heading hierarchy."""
    lines = profile_text.splitlines()
    errors = []

    def atx_heading(line):
        match = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)", line)
        if not match:
            return None
        title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", match[2] or "").strip()
        return len(match[1]), title

    def section(heading, source, *, optional=False):
        target = atx_heading(heading)
        headings = [atx_heading(line) for line in source]
        starts = [index for index, value in enumerate(headings) if value == target]
        if len(starts) != 1:
            if starts or not optional:
                errors.append(
                    DiagnosticError(
                        "extract writing brief",
                        heading,
                        f"duplicate heading: {len(starts)} occurrences"
                        if starts
                        else "missing heading",
                        "one heading in voice-profile.md (register under ## 2. Per register)",
                        None,
                        "rebuild the profile with voice-profile-build and select an available register",
                    )
                )
            return []
        start = starts[0]
        end = start + 1
        while end < len(source):
            if headings[end] and headings[end][0] <= target[0]:
                break
            end += 1
        return source[start:end]

    register_heading = f"### {register}"
    registers = section("## 2. Per register", lines)
    chosen = [
        ("## Core voice", section("## Core voice", lines, optional=True)),
        (
            register_heading,
            section(register_heading, registers if register != "Per-source contrast" else []),
        ),
        ("## 3. Edit-delta tendencies", section("## 3. Edit-delta tendencies", lines)),
        ("## 5. Anti-patterns", section("## 5. Anti-patterns", lines)),
    ]
    if errors:
        raise ValidationErrors(errors)
    if not chosen[0][1]:
        chosen[0] = (
            "## Core voice",
            ["Core voice: not in this profile; rebuild it with voice-profile-build."],
        )
    return "\n\n".join("\n".join(body).strip() for _, body in chosen) + "\n"


def validate_brief(brief):
    errors = []

    def require(field, valid, expected):
        if not valid:
            errors.append(
                DiagnosticError(
                    "validate writing brief",
                    field,
                    "missing or wrong type/value",
                    expected,
                    None,
                    "correct this brief field before drafting",
                )
            )

    if not isinstance(brief, dict):
        require("brief", False, "an object")
        raise ValidationErrors(errors)
    audience = brief.get("audience")
    audience = audience if isinstance(audience, dict) else {}
    require(
        "audience.text",
        isinstance(audience.get("text"), str) and bool(audience["text"].strip()),
        "nonempty text",
    )
    require(
        "audience.recipient_class",
        audience.get("recipient_class") in CONTRACT["recipient_classes"],
        "a declared recipient class",
    )
    require("medium", brief.get("medium") in CONTRACT["media"], "a declared medium")
    require(
        "formality",
        type(brief.get("formality")) is int and 1 <= brief["formality"] <= 5,
        "integer 1 through 5",
    )
    length = brief.get("length")
    require(
        "length",
        (type(length) is int and length > 0)
        or (isinstance(length, str) and length in ("short", "medium", "long")),
        "positive word count or short, medium, long",
    )
    require(
        "purpose",
        isinstance(brief.get("purpose"), str) and bool(brief["purpose"].strip()),
        "nonempty text",
    )
    for field in ("facts", "must_include", "must_avoid"):
        require(
            field,
            isinstance(brief.get(field), list)
            and all(isinstance(item, str) for item in brief[field]),
            "array of strings",
        )
    if errors:
        raise ValidationErrors(errors)


def register_for(brief):
    """Email keeps its recipient register; every other medium, including `article`, is
    the article register, and run_loop lints it with the brief's own medium."""
    validate_brief(brief)
    if brief["medium"] != "email":
        return CONTRACT["non_email_register"]
    recipient = brief["audience"]["recipient_class"]
    return (
        CONTRACT["unknown_email_formality"][str(brief["formality"])]
        if recipient == "unknown"
        else recipient
    )


def select_exemplars(register, length, *, stats_only):
    if stats_only or register["selection"]["status"] == "no_llm_eligible_source":
        return []
    if isinstance(length, str):
        stratum = ("short", "medium", "long").index(length)
    else:
        cuts = [s["boundaries"][1] for s in register["selection"]["strata"][:2]]
        stratum = sum(length > cut for cut in cuts)
    return [item for item in register["items"] if item["stratum"] == stratum][:5]


def cli(config, *args):
    command = [sys.executable, "-m", "ownvoice", "--config", str(config), *map(str, args)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    accepted = (0, CONTRACT["lint_findings_exit"]) if args[0] == "lint" else (0,)
    if result.returncode not in accepted:
        cause = subprocess.CalledProcessError(
            result.returncode, command, result.stdout, result.stderr
        )
        raise DiagnosticError(
            "run writing subprocess",
            config,
            f"{args[0]} exit {result.returncode}",
            f"exit in {accepted}",
            result.stderr,
            "resolve the CLI diagnostic before resuming the writing session",
            exit_code=3,
        ) from cause
    return json.loads(result.stdout)


def run_loop(brief, context, model, *, config, session_dir):
    """Model returns draft and brief-grounded warning justifications; never sends mail."""
    register = register_for(brief)
    paths = cli(config, "config", "show", "--format", "json")
    session = Path(session_dir)
    findings = []
    for iteration in range(1, CONTRACT["max_iterations"] + 1):
        response = model(brief, context, findings)
        draft = response["draft"]
        justified = response.get("justified_warnings", {})
        draft_path = session / "draft.md"
        # A temporary draft is not a corpus/profile artefact. Keep marker text
        # out of the lint input so counts describe exactly the delivered draft.
        _atomic_write(draft_path, lambda stream, draft=draft: stream.write(draft))
        report = lint.validate(
            cli(
                config,
                "lint",
                draft_path,
                "--stats",
                paths["profile_stats"],
                "--register",
                register,
                "--medium",
                brief["medium"],
                "--rules",
                paths["editorial_rules"],
                "--format",
                "json",
                "--out",
                session / "lint.json",
            )
        )
        findings = report["findings"]
        remaining = [
            f
            for f in findings
            if f["severity"] == "error"
            or (f["severity"] == "warn" and not justified.get(f["rule_id"], "").strip())
        ]
        if not remaining:
            break
    counts = report["summary"]
    ids = sorted({f["rule_id"] for f in findings if f["severity"] in ("error", "warn")})
    line = f"lint: {counts['error']} errors, {counts['warn']} " + (
        "warning" if counts["warn"] == 1 else "warnings"
    )
    if ids:
        line += " (" + ", ".join(ids) + ")"
    return {
        "draft": draft,
        "lint_result": line,
        "iterations": iteration,
        "remaining_findings": remaining,
        "justified_warnings": {
            f["rule_id"]: justified[f["rule_id"]]
            for f in findings
            if f["severity"] == "warn" and justified.get(f["rule_id"])
        },
        "info": [f for f in findings if f["severity"] == "info"],
        "report_path": str(session / "lint.json"),
    }


def main(argv=None):
    parser = Parser(prog="write-in-voice workflow.py")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("brief-sections")
    extract.add_argument("--profile", required=True, type=Path)
    extract.add_argument("--register", required=True)
    extract.add_argument("--verbose", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.verbose:
            print(f"read writing profile [{args.profile.resolve()}]", file=sys.stderr)
        try:
            profile_text = args.profile.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DiagnosticError(
                "read writing profile",
                args.profile,
                str(exc),
                "a readable UTF-8 voice-profile.md",
                exc,
                "check the profile path and permissions, then rebuild with voice-profile-build",
                exit_code=3,
            ) from exc
        print(brief_sections(profile_text, args.register), end="")
    except (DiagnosticError, ValidationErrors) as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
