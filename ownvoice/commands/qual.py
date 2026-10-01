from pathlib import Path

from ownvoice import provenance
from ownvoice.config import articles_llm_eligible, load_config
from ownvoice.qual import chunk, ground, merge, reconcile, sample
from ownvoice.schemas import article_records, ingest_report, records


def run(args):
    command = args.qual_command
    if command == "chunk":
        config, _ = load_config(args.config)
        rows = [records.validate(r) for r in chunk.read_json(args.records, lines=True)]
        sources = {s["label"]: s for s in config["source"]}
        if {r["source"] for r in rows} - sources.keys() or len(
            {r["record_id"] for r in rows}
        ) != len(rows):
            raise chunk.problem(
                "select qual records",
                args.records,
                "unknown sources or duplicate record ids",
                "unique records from configured sources",
                "restore matching ingest records and config",
            )
        eligible, reports = set(), []
        for label in sorted({r["source"] for r in rows}):
            report = ingest_report.validate(
                chunk.read_json(
                    Path(config["paths"]["work_dir"]) / "sources" / label / "ingest-report.json"
                )
            )
            provenance.require_scrub(config, report, label)
            if report["source"] != label or report["status"] != "complete":
                raise chunk.problem(
                    "select qual source",
                    label,
                    "source report mismatched or incomplete",
                    "a complete report for this source",
                    "complete ingest before chunking",
                )
            reports.append(report)
            if sources[label]["llm_eligible"]:
                eligible.add(label)
        cap = (
            args.sample_words
            if args.sample_words is not None
            else config["profile"]["qual_sample_words"]
        )
        selected = sample.select(rows, eligible, cap, config["profile"]["qual_max_record_words"])
        if getattr(args, "articles", None):
            if not articles_llm_eligible(config):
                raise chunk.problem(
                    "select qual articles",
                    args.articles,
                    "articles_llm_eligible is not true",
                    "[profile] articles_llm_eligible = true before article text is chunked",
                    "set articles_llm_eligible in the config or chunk without --articles",
                )
            articles = [
                article_records.validate(r) for r in chunk.read_json(args.articles, lines=True)
            ]
            selected.extend(
                sample.articles(
                    articles,
                    config["profile"]["qual_sample_words"],
                    config["profile"]["qual_max_record_words"],
                )
            )
        prov = provenance.build(
            config,
            config["paths"]["domain_map"],
            config["paths"]["editorial_rules"],
            timestamp=max((r["generated_at"] for r in reports), default=None),
            readers={
                r["source"]: {"reader": r["reader"], "reader_version": r["reader_version"]}
                for r in reports
                if r["reader"]
            },
        )
        value = chunk.build(selected, args.pass_name, args.max_tokens, cap, args.out, prov)
        print(f"qual chunk: {len(value['chunks'])} chunks")
    elif command == "status":
        states = chunk.counts(chunk.load(args.manifest))
        print("qual status: " + ", ".join(f"{key}={count}" for key, count in states.items()))
    elif command == "ground":
        report = ground.run(args.manifest, args.findings, args.out, args.threshold)
        print(f"qual ground: kept={report['kept']}, dropped={len(report['dropped'])}")
    elif command == "reconcile":
        value = reconcile.run(args.candidate, args.existing, args.out)
        print(
            "qual reconcile: "
            + ", ".join(f"{key}={len(value[key])}" for key in ("new", "matched", "borderline"))
        )
    elif command == "merge":
        value = merge.run(args.existing, args.add, args.out)
        print(
            f"qual merge: findings={len(value['findings'])}, passes={len(value['passes'])}, "
            f"residual={value['residual']}, unresolved_failed={value['unresolved_failed']}"
        )
    return 0
