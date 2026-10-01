"""Private ingest orchestration with scrub-before-write and conserved accounting."""

import hashlib
import re
import sys
import time
from collections import Counter
from email.errors import MessageError
from pathlib import Path
from types import SimpleNamespace

from ownvoice import provenance
from ownvoice.errors import DiagnosticError, ExitCode, ValidationErrors, internal_error
from ownvoice.extract import classify, dedup, scrub, signature
from ownvoice.extract.body import Rejected, extract, word_count
from ownvoice.ingest import checkpoint, pst, report
from ownvoice.ingest.preflight import preflight, select_sources
from ownvoice.io import write_json, write_jsonl, write_marked_text
from ownvoice.layout import Layout
from ownvoice.readers import eml, mbox
from ownvoice.readers.recipients import resolve
from ownvoice.schemas import checkpoint as checkpoint_schema
from ownvoice.schemas import merge_state as merge_state_schema
from ownvoice.schemas import names as names_schema
from ownvoice.schemas import records as record_schema
from ownvoice.schemas import rejects as reject_schema
from ownvoice.schemas import unmapped_domains


def record_id(message, source, text=""):
    value = message.message_id or "\x00".join(
        (source["label"], message.source_locator, str(message.date or ""), text)
    )
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def fingerprint(paths):
    stats = [p.stat() for p in paths]
    first, last = hashlib.sha256(), hashlib.sha256()
    try:
        for path in paths:
            with path.open("rb") as stream:
                first.update(stream.read(1024 * 1024))
                stream.seek(max(0, path.stat().st_size - 1024 * 1024))
                last.update(stream.read(1024 * 1024))
        hashes = first.hexdigest(), last.hexdigest()
    except OSError:
        # edge hashes are best-effort; metadata remains mandatory.
        hashes = None, None
    return {
        "size": sum(s.st_size for s in stats),
        "mtime_ns": max(s.st_mtime_ns for s in stats),
        "first_sha256": hashes[0],
        "last_sha256": hashes[1],
    }


def rejection(locator, identifier, reason, label, cause=None):
    # MIME exceptions can include header/body values. Keep the original exception chained
    # in memory, but only its type reaches the persisted diagnostic (privacy override).
    safe_cause = type(cause).__name__ if cause else None
    detail = DiagnosticError(
        "parse message",
        f"{label}/{locator}",
        reason,
        "a decodable owner-sent mail body",
        safe_cause,
        "inspect the source privately and retry ingest with --verbose",
    )
    return reject_schema.build(
        source_locator=locator, record_id=identifier, reason=reason, detail=str(detail)
    )


def process_source(config, domain_map, source, paths, args, journal=None, finish=None):
    records, rejects, selected, seen = [], [], 0, 0
    identifiers = set()
    resolution = dict.fromkeys(("recipients", "smtp", "x500", "names", "unknown"), 0)
    domains, names, orgs = Counter(), set(), Counter()
    resume_index = 0
    if journal:
        records, rejects = journal.records, journal.rejects
        if journal.previous:
            previous = journal.previous
            resume_index = seen = previous["message_index"]
            state = previous["state"]
            selected, resolution = state["selected"], state["resolution"]
            domains, names = checkpoint.domains(journal.outputs, state), set(state["names"])
            orgs = checkpoint.domains(journal.outputs, state, "x500_orgs")
            identifiers = {r["record_id"] for r in records}
    is_pst = source["kind"] == "pst"
    reader = paths if is_pst else mbox if source["kind"] == "mbox" else eml
    # Existing reject locators bind each committed outcome to its global index.
    # Replay only counts for that prefix, without persisting new schema fields.
    rejected_indices = (
        {int(row["source_locator"].rsplit("/", 1)[1]) for row in rejects} if is_pst else set()
    )
    started = time.monotonic()
    owners = {x.casefold() for x in config["owner"]["addresses"] + source["owner_addresses"]}
    excluded = {x.casefold() for x in config["ingest"]["takeout_excluded_labels"]}
    try:
        messages = reader.messages(boundaries=True) if is_pst else reader.messages(paths)
        for index, raw in messages:
            if is_pst:
                folder = reader.current_folder
                if journal:
                    journal.folder = folder["name"]
                if raw is None:
                    if index > resume_index:
                        if journal:
                            journal.save(seen, selected, resolution, domains, names, orgs=orgs)
                        if not args.quiet:
                            rate = seen / max(time.monotonic() - started, 0.001)
                            print(
                                f"ingest[{source['label']}]: folder {folder['name']}: "
                                f"{folder['messages_seen']} messages, {folder['records']} records, "
                                f"{folder['rejects']} rejected, {rate:.0f} msg/s",
                                file=sys.stderr,
                            )
                    continue
                folder["messages_seen"] += 1
            if index < resume_index:
                if is_pst:
                    folder["rejects" if index in rejected_indices else "records"] += 1
                continue
            seen += 1
            locator = f"{source['kind']}:{Path(source['path']).name}#messages/{index}"
            identifier = hashlib.sha256((source["label"] + locator).encode()).hexdigest()[:16]
            try:
                if isinstance(raw, Rejected):
                    raise raw
                message, mail = raw if is_pst else eml.parse(raw, locator)
                identifier = record_id(message, source)
                labels = {
                    x.strip().casefold()
                    for v in mail.get_all("X-Gmail-Labels", [])
                    for x in str(v).split(",")
                }
                if not is_pst and labels & excluded:
                    raise Rejected("excluded_label")
                if (
                    not is_pst
                    and (message.sender_address or "").casefold() not in owners
                    and "sent" not in labels
                ):
                    raise Rejected("not_owner")
                selected += 1
                category, bucket, stages, unknown_domains, unknown_names, unknown_orgs = resolve(
                    message, domain_map
                )
                for stage, count in stages.items():
                    resolution[stage] += count
                    resolution["recipients"] += count
                domains.update(unknown_domains)
                orgs.update(unknown_orgs)
                names.update(hashlib.sha256(name.encode()).hexdigest() for name in unknown_names)
                if any(part.defects for part in mail.walk()):
                    raise Rejected("parse_error", mail.defects[0] if mail.defects else None)
                text, strip = extract(
                    mail,
                    config["ingest"],
                    mboxrd=source["kind"] == "mbox" or source.get("reader") == "readpst",
                )
                identifier = record_id(message, source, text)
                if identifier in identifiers:
                    raise Rejected("duplicate")
                year, weekday, hour = classify.date_fields(message, source)
                if year is None:
                    strip["flags"].append("missing_date")
                era = source.get("era")
                if era and year is not None and not era["from_year"] <= year <= era["to_year"]:
                    raise Rejected("out_of_range_year")
                record = record_schema.build(
                    record_id=identifier,
                    source=source["label"],
                    source_kind=source["kind"],
                    era=f"{era['from_year']}-{era['to_year']}" if era else None,
                    year=year,
                    weekday=weekday,
                    hour_bucket=hour,
                    recipient_class=category,
                    recipient_count_bucket=bucket,
                    recipient_stages=stages,
                    thread_position=classify.thread_position(
                        message, strip["rules_fired"], config["ingest"]
                    ),
                    word_count=word_count(text),
                    text=text,
                    greeting=None,
                    signoff=None,
                    strip=strip,
                    scrub={
                        **dict.fromkeys(
                            (
                                "greeting_names",
                                "lexicon_names",
                                "emails",
                                "phones",
                                "urls",
                                "numbers",
                            ),
                            0,
                        ),
                        "residual_capitalised": [],
                    },
                    template=False,
                    sensitive=False,
                )
                if finish:
                    finish([record])
                records.append(record)
                if is_pst:
                    folder["records"] += 1
                if journal:
                    journal.append("records", record)
                identifiers.add(identifier)
                for rule in strip["rules_fired"] or ["selected"]:
                    args.logger.event(record_id=identifier, rule_id=rule)
            except (Rejected, MessageError, ValueError, IndexError) as exc:
                reason = exc.reason if isinstance(exc, Rejected) else "parse_error"
                rejects.append(
                    rejection(
                        locator,
                        identifier,
                        reason,
                        source["label"],
                        exc.cause if isinstance(exc, Rejected) else exc,
                    )
                )
                if is_pst:
                    folder["rejects"] += 1
                args.logger.event(record_id=identifier, rule_id=reason)
                if journal:
                    journal.append("rejects", rejects[-1])
            if journal and seen % config["ingest"]["checkpoint_every"] == 0:
                journal.save(seen, selected, resolution, domains, names, orgs=orgs)
            if seen % 250 == 0 and not args.quiet:
                rate = seen / max(time.monotonic() - started, 0.001)
                print(
                    f"ingest[{source['label']}]: {seen} messages, {len(records)} records, "
                    f"{len(rejects)} rejected, {rate:.0f} msg/s",
                    file=sys.stderr,
                )
    except OSError as exc:
        raise DiagnosticError(
            "read ingest source",
            source["label"],
            str(exc),
            "readable source files",
            exc,
            "restore source access and retry ingest",
            exit_code=ExitCode.DEPENDENCY,
        ) from exc
    if seen != len(records) + len(rejects):
        raise internal_error(
            "account for messages",
            source["label"],
            ValueError(f"seen={seen}, records={len(records)}, rejects={len(rejects)}"),
        )
    if journal:
        journal.save(seen, selected, resolution, domains, names, orgs=orgs)
    return records, rejects, selected, resolution, domains, names, orgs


def collect_names(config, sources, inputs):
    names = set()
    for source in sources:
        if source["kind"] == "pst":
            names.update(inputs[source["label"]].harvest(config))
            continue
        reader = mbox if source["kind"] == "mbox" else eml
        try:
            for index, raw in reader.messages(inputs[source["label"]]):
                try:
                    _, mail = eml.parse(raw, f"{source['label']}#{index}")
                    names.update(scrub.harvest(mail, config["owner"]["names"], config["ingest"]))
                except (MessageError, ValueError, IndexError):
                    # The ordinary parse pass emits a privacy-safe reject for this message.
                    continue
        except OSError as exc:
            raise DiagnosticError(
                "collect correspondent names",
                source["label"],
                str(exc),
                "readable source headers",
                exc,
                "restore source access and retry ingest",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc
    return names


def finalise(records, config, names, words, groups, deny, sensitive, fingerprints=None):
    owners, valedictions = config["owner"]["names"], config["ingest"]["valedictions"]
    if fingerprints is None:
        fingerprints = signature.learn(records, owners, valedictions)
    for record in records:
        text, signoff, rules = signature.strip(
            record["text"],
            owners,
            valedictions,
            fingerprints.get((record["source"], record["year"]), set()),
        )
        if not text:
            raise Rejected("empty_after_strip")
        # Extraction sees signatures too. Re-evaluate only text-dependent evidence
        # on the owner's remaining body, preserving MIME and inline ambiguity.
        strip = record["strip"]
        strip["flags"] = [
            flag for flag in strip["flags"] if flag not in {"residual_marker", "long_body"}
        ]
        if re.search(r"wrote:|^From:|^>|^Subject:", text, re.IGNORECASE | re.MULTILINE):
            strip["flags"].append("residual_marker")
        if word_count(text) > 3000:
            strip["flags"].append("long_body")
        strip["confidence"] = (
            "low" if set(strip["flags"]) - {"decode_error_partial", "missing_date"} else "high"
        )
        record["sensitive"] = scrub.sensitive(text, sensitive)
        text, greeting, counts = scrub.scrub(
            text,
            names,
            owners,
            deny_terms=deny,
            wordlist=words,
            groups=groups,
        )
        record.update(
            text=text, greeting=greeting, signoff=signoff, scrub=counts, word_count=word_count(text)
        )
        record["strip"]["rules_fired"].extend(rules)
        record_schema.validate(record)
    return dedup.templates(records)


def run(config, domain_map, args):
    sources = select_sources(config, args)
    merge_sources = list(config["source"])
    configured_labels = {source["label"] for source in merge_sources}
    merge_sources.extend(source for source in sources if source["label"] not in configured_labels)
    pst.listing(config["paths"]["work_dir"])
    inputs = preflight(config, sources)
    prov = provenance.build(
        config, config["paths"]["domain_map"], config["paths"]["editorial_rules"]
    )
    layout = Layout(Path(config["paths"]["work_dir"]))
    # Refuse stale selected sources before any writes; explicit reparses repair one label.
    for source in sources:
        label = source["label"]
        if label in (args.restart, args.reparse):
            continue
        outputs = layout.source_paths(label)
        for kind in ("checkpoint", "report"):
            if outputs[kind].exists():
                provenance.require_scrub(config, checkpoint.read(outputs[kind]), label)
    words, groups = scrub.shipped("wordlist"), scrub.shipped("groups")
    sensitive, sensitive_provenance = scrub.sensitive_terms(config["ingest"]["sensitive_terms"])
    deny = (
        scrub.read_terms(config["ingest"]["deny_terms_file"])
        if config["ingest"]["deny_terms_file"]
        else set()
    )
    plans, errors = {}, []
    for source in sources:
        label = source["label"]
        paths = inputs[label]
        outputs = layout.source_paths(label)
        try:
            source_fingerprint, files = fingerprint(paths), checkpoint.identity(paths)
        except OSError as exc:
            raise DiagnosticError(
                "fingerprint ingest source",
                label,
                str(exc),
                "readable source metadata",
                exc,
                "restore source access and retry ingest",
                exit_code=ExitCode.DEPENDENCY,
            ) from exc
        reset = label in (args.restart, args.reparse)
        previous = (
            checkpoint.read(outputs["checkpoint"])
            if outputs["checkpoint"].exists() and not reset
            else None
        )
        if previous:
            checkpoint_schema.validate(previous)
        if previous and not reset:
            state = previous.get("state")
            reset = not state or not checkpoint.matches(state, source_fingerprint, files)
            if state and not state["complete"]:
                reset |= any(
                    previous[k] != prov[k]
                    for k in ("config_digest", "domain_map_digest", "rules_sha256", "tool_version")
                )
        if reset:
            checkpoint.reset(outputs)
            previous = None
        complete = bool(previous and previous["state"]["complete"] and outputs["report"].exists())
        plans[label] = (outputs, source_fingerprint, files, previous, complete)
        if source["kind"] == "pst" and not complete:
            try:
                inputs[label] = pst.prepare(source, outputs, source_fingerprint, prov, config, args)
            except DiagnosticError as exc:
                errors.append(exc)
                failed_report = report.build(
                    source,
                    prov,
                    source_fingerprint,
                    [],
                    [],
                    0,
                    dict.fromkeys(("recipients", "smtp", "x500", "names", "unknown"), 0),
                    {},
                    set(),
                )
                write_json(outputs["report"], failed_report)
                del plans[label]
    sources = [s for s in sources if s["label"] in plans]
    changed = any(not plan[-1] for plan in plans.values())
    names_lexicon = (
        collect_names(config, [s for s in sources if not plans[s["label"]][-1]], inputs)
        if changed
        else set()
    )
    if changed:
        if layout.names.exists():
            names_lexicon.update(layout.names.read_text().splitlines()[1:])
        write_marked_text(layout.names, names_schema.build(names_lexicon).split("\n", 1)[1])
    prov["lexicons"] = {"sensitive": sensitive_provenance}
    for source in sources:
        outputs, source_fingerprint, files, previous, complete = plans[source["label"]]
        if complete:
            records = checkpoint.rows(outputs["records"], previous["records"])
            rejects = checkpoint.rows(outputs["rejects"], previous["rejects"])
            state = previous["state"]
            selected, resolution = state["selected"], state["resolution"]
            domains, names = checkpoint.domains(outputs, state), set(state["names"])
            orgs = checkpoint.domains(outputs, state, "x500_orgs")
            source_report = checkpoint.read(outputs["report"])
        else:
            paths = inputs[source["label"]]
            # Source-wide signature learning is memory-only. Resume skips the committed
            # prefix in the output pass; no unsanitized body is ever journalled.
            silent = SimpleNamespace(quiet=True, logger=SimpleNamespace(event=lambda **kw: None))
            learning = process_source(config, domain_map, source, paths, silent)[0]
            fingerprints = signature.learn(
                learning, config["owner"]["names"], config["ingest"]["valedictions"]
            )
            del learning
            journal = checkpoint.Journal(outputs, prov, source_fingerprint, files, previous)

            def finish(batch, fingerprints=fingerprints):
                finalise(batch, config, names_lexicon, words, groups, deny, sensitive, fingerprints)

            records, rejects, selected, resolution, domains, names, orgs = process_source(
                config, domain_map, source, paths, args, journal, finish
            )
            dedup.templates(records)
            source_report = report.build(
                source,
                prov,
                source_fingerprint,
                records,
                rejects,
                selected,
                resolution,
                domains,
                names,
                orgs,
                paths if source["kind"] == "pst" else None,
            )
            write_jsonl(outputs["records"], records)
            write_json(outputs["report"], source_report)
            journal.save(
                len(records) + len(rejects),
                selected,
                resolution,
                domains,
                names,
                complete=source_report["status"] == "complete",
                orgs=orgs,
            )
            if source["kind"] == "pst":
                if paths.errors:
                    errors.append(
                        pst.problem(
                            source,
                            f"{len(paths.errors)} unreadable selected folders",
                            "all selected folders readable",
                        )
                    )
                if not args.keep_extracted:
                    pst.remove(outputs["extract"])
                    print(
                        f"ingest[{source['label']}]: export deleted; later --reparse needs "
                        "--restart (re-export measured at 331 s per 10.5 GB with pffexport)",
                        file=sys.stderr,
                    )
        report.summary(source_report, outputs["rejects"], records)
        if not records:
            errors.append(
                DiagnosticError(
                    "ingest",
                    source["label"],
                    f"no owner-sent messages in {source['path']} ({selected} of {source_report['messages_seen']} "
                    "messages matched owner_addresses or sent_folders)",
                    "at least 1",
                    None,
                    "Check the file copied completely and the addresses/folders in config.toml",
                )
            )
    source_counts, source_versions = {}, {}
    merged, unknown_domains, unknown_names, unknown_orgs = [], Counter(), set(), Counter()
    for source in merge_sources:
        label = source["label"]
        outputs = layout.source_paths(label)
        for kind in ("checkpoint", "report"):
            if outputs[kind].exists():
                provenance.require_scrub(config, checkpoint.read(outputs[kind]), label)
        previous = (
            checkpoint_schema.validate(checkpoint.read(outputs["checkpoint"]))
            if outputs["checkpoint"].exists()
            else None
        )
        if not (
            previous
            and previous.get("state", {}).get("complete")
            and outputs["records"].exists()
            and outputs["report"].exists()
            and checkpoint.read(outputs["report"])["status"] == "complete"
        ):
            print(
                str(
                    DiagnosticError(
                        "merge ingest source",
                        label,
                        "excluded: no completed per-source records and report",
                        "a complete checkpoint with records.jsonl and a complete ingest-report.json",
                        None,
                        f"run ingest --only {label} to complete this source",
                    )
                ),
                file=sys.stderr,
            )
            continue
        records = checkpoint.rows(outputs["records"], previous["records"])
        source_counts[label] = len(records)
        source_versions[label] = provenance.file_sha256(outputs["report"])
        merged.extend(records)
        state = previous["state"]
        unknown_domains.update(checkpoint.domains(outputs, state))
        unknown_names.update(state["names"])
        unknown_orgs.update(checkpoint.domains(outputs, state, "x500_orgs"))
    merge_state = layout.work_dir / "merge-state.json"
    if (
        not changed
        and merge_state.exists()
        and merge_state_schema.validate(checkpoint.read(merge_state))["sources"] == source_versions
        and all(
            (layout.work_dir / name).exists()
            for name in ("records.jsonl", "ingest-report.json", "unmapped-domains.json")
        )
    ):
        if errors:
            raise ValidationErrors(errors)
        return 0
    merged, cross_duplicates = dedup.merge(merged)
    merged_report = report.merged(prov, source_counts, merged, cross_duplicates)
    write_jsonl(layout.work_dir / "records.jsonl", merged)
    write_json(layout.work_dir / "ingest-report.json", merged_report)
    summary = unmapped_domains.build(
        **{key: value for key, value in prov.items() if key != "lexicons"},
        domains=[
            {"domain": d, "messages": n}
            for d, n in sorted(unknown_domains.items(), key=lambda item: (-item[1], item[0]))[:50]
        ],
        x500_orgs=[
            {"org": o, "messages": n}
            for o, n in sorted(unknown_orgs.items(), key=lambda item: (-item[1], item[0]))[:50]
        ],
        unresolved_names=len(unknown_names),
    )
    write_json(layout.unmapped_domains, summary)
    if not args.quiet:
        for row in summary["domains"]:
            # Only domain labels are permitted on this surface, never full addresses.
            domain = row["domain"]
            if re.fullmatch(r"[a-z0-9.-]+", domain):
                print(f"unmapped domain {domain}: {row['messages']} messages", file=sys.stderr)
        print(f"unresolved display names: {len(unknown_names)}", file=sys.stderr)
        for row in summary["x500_orgs"]:
            print(f"unmapped X.500 org {row['org']}: {row['messages']} messages", file=sys.stderr)
    write_json(
        merge_state,
        merge_state_schema.build(
            **{key: value for key, value in prov.items() if key != "lexicons"},
            sources=source_versions,
        ),
    )
    if errors:
        raise ValidationErrors(errors)
    return 0
