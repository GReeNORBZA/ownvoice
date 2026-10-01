"""Lint command, with schema validation and private atomic output."""

import json
from pathlib import Path

from ownvoice import provenance
from ownvoice.config import load_config
from ownvoice.errors import DiagnosticError, ExitCode
from ownvoice.io import write_json
from ownvoice.schemas import lint, profile_stats
from ownvoice.style import rules_block
from ownvoice.style.lint import check, summary


def run(args):
    config, _ = load_config(args.config)
    inputs = []
    for name in (args.draft, args.stats):
        path = Path(name).expanduser().resolve()
        try:
            inputs.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise DiagnosticError(
                "read lint input",
                path,
                str(exc),
                "readable UTF-8 input",
                exc,
                "correct the input path or encoding and retry lint",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc
    try:
        stats = profile_stats.validate(json.loads(inputs[1]))
    except ValueError as exc:
        raise DiagnosticError(
            "parse lint statistics",
            args.stats,
            str(exc),
            "valid profile JSON",
            exc,
            "regenerate profile-stats.json with ownvoice profile",
        ) from exc
    for label in stats["corpus"]["sources"]:
        provenance.require_scrub(config, stats, label)
    provenance.require_current(config, stats, args.stats, "profile")
    for field, value, choices in (
        ("register", args.register, stats["registers"]),
        ("source", args.source, stats["by_source"]),
    ):
        if value is not None and value not in choices:
            raise DiagnosticError(
                "select lint " + field,
                value,
                "unknown " + field,
                "available: " + ", ".join(sorted(choices)),
                None,
                "choose an available " + field,
            )
    rules_path = Path(args.rules or config["paths"]["editorial_rules"]).expanduser().resolve()
    rules = rules_block.load(rules_path)
    softeners = ()
    if config["ingest"]["softeners"]:
        from ownvoice.commands.profile import read_lexicon

        softeners = read_lexicon(config["ingest"]["softeners"])
    words, sentences, enabled, findings = check(
        inputs[0],
        stats,
        rules,
        args.register,
        args.medium,
        source=args.source,
        minimum=config["profile"]["thin_register_min"],
        never_min=config["profile"]["never_hit_min_words"],
        softeners=softeners,
        owner_names=config["owner"]["names"],
        valedictions=config["ingest"]["valedictions"],
    )
    report = lint.build(
        **provenance.build(config, config["paths"]["domain_map"], rules_path),
        draft=str(Path(args.draft).expanduser().resolve()),
        register=args.register,
        medium=args.medium,
        word_count=words,
        sentences=sentences,
        rate_checks_enabled=enabled,
        findings=findings,
        summary={
            severity: sum(f["severity"] == severity for f in findings)
            for severity in ("error", "warn", "info")
        },
    )
    output = (
        Path(args.out).expanduser()
        if args.out
        else Path(args.draft).expanduser().resolve().parent / "lint.json"
    )
    write_json(output, report)
    if not args.quiet:
        print(json.dumps(report, ensure_ascii=False) if args.format == "json" else summary(report))
    return int(ExitCode.LINT if report["summary"]["error"] else ExitCode.OK)
