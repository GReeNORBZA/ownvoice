"""Edit tendencies, private proposals and blind comparison dispatch."""

import hashlib
import json
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

from ownvoice import provenance
from ownvoice.config import load_config
from ownvoice.delta.align import align
from ownvoice.delta.classify import classify
from ownvoice.delta.compare import compare
from ownvoice.delta.discover import discover
from ownvoice.delta.normalize import load, normalize, read_text
from ownvoice.errors import DiagnosticError
from ownvoice.extract import scrub
from ownvoice.io import write_json, write_marked_toml
from ownvoice.layout import Layout
from ownvoice.schemas import edit_delta
from ownvoice.style.metrics import METRIC_IDS, measure


def scrub_text(text, names, owner_names=(), **kwargs):
    masked, spans, counts = scrub.scrub(text, names, owner_names, **kwargs)
    contractions = {
        f"{pronoun}'{suffix}"
        for pronoun, suffixes in (
            ("i", ("m", "ve", "ll", "d")),
            ("we", ("re", "ve", "ll", "d")),
            ("you", ("re", "ve", "ll", "d")),
            ("they", ("re", "ve", "ll", "d")),
            ("he", ("s", "ll", "d")),
            ("she", ("s", "ll", "d")),
            ("it", ("s", "ll", "d")),
        )
        for suffix in suffixes
    }
    counts["residual_capitalised"] = [
        token
        for token in counts["residual_capitalised"]
        if token.lower().replace("’", "'") not in contractions
    ]
    return masked, spans, counts


def scrubber(config):
    names_path = Layout(Path(config["paths"]["work_dir"])).names
    names = set(read_text(names_path).splitlines()[1:]) if names_path.exists() else set()
    deny = (
        scrub.read_terms(config["ingest"]["deny_terms_file"])
        if config["ingest"]["deny_terms_file"]
        else ()
    )
    wordlist, groups = scrub.shipped("wordlist"), scrub.shipped("groups")

    def clean(text):
        return scrub_text(
            text, names, config["owner"]["names"], deny_terms=deny, wordlist=wordlist, groups=groups
        )

    return clean


def compute(chains, clean, llm_isms=None):
    operations = Counter(dict.fromkeys(("join", "split", "replace", "insert", "delete"), 0))
    examples, substitutions, measurements = [], Counter(), []
    pairs = 0
    for chain in chains:
        texts = [normalize(t) for t in chain["texts"]]
        if chain["origin"] == "llm":
            measurements.append((measure(texts[0]), measure(texts[-1])))
        index = 0
        for before, after in pairwise(texts):
            pairs += 1
            for opcode, left, right in align(before, after):
                op, tags, replacements = classify(opcode, left, right, llm_isms)
                operations[op] += 1
                old, _, old_scrub = clean(" ".join(left))
                new, _, new_scrub = clean(" ".join(right))
                if not old_scrub["residual_capitalised"] and not new_scrub["residual_capitalised"]:
                    if tags:
                        examples.append(
                            (
                                chain["id"],
                                index,
                                {
                                    "chain_id": chain["id"],
                                    "before": " ".join(old.split()[:60]),
                                    "after": " ".join(new.split()[:60]),
                                    "tags": tags,
                                },
                            )
                        )
                    for a, b in replacements:
                        a, _, sa = clean(a)
                        b, _, sb = clean(b)
                        if not sa["residual_capitalised"] and not sb["residual_capitalised"]:
                            substitutions[a, b] += 1
                index += 1
    aggregate = {}
    for metric in METRIC_IDS:
        before = sum(a[metric] for a, _ in measurements) / len(measurements) if measurements else 0
        after = sum(b[metric] for _, b in measurements) / len(measurements) if measurements else 0
        aggregate[metric] = {"before": before, "after": after, "delta": after - before}
    return {
        "chains": [{"id": c["id"], "versions": c["versions"]} for c in chains],
        "pairs": pairs,
        "aggregate": aggregate,
        "operations": dict(operations),
        "examples": [
            x[2] for x in sorted(examples, key=lambda x: (-len(x[2]["tags"]), x[0], x[1]))[:20]
        ],
        "substitutions": [
            {"before": a, "after": b, "count": n}
            for (a, b), n in sorted(substitutions.items(), key=lambda x: (-x[1], x[0]))
            if n >= 2
        ],
    }


def run(args):
    if args.delta_command == "compare":
        write_json(args.out, compare(args.pairs))
        return 0
    config, _ = load_config(args.config)
    layout = Layout(Path(config["paths"]["work_dir"]))
    if args.delta_command == "discover":
        write_marked_toml(
            args.out or layout.work_dir / "chains.proposed.toml", discover(args.dir, args.git)
        )
        return 0
    chains = load(args.chains)
    lexicon = config["profile"]["llm_ism_lexicon"]
    terms = scrub.read_terms(lexicon) if lexicon else None
    result = edit_delta.build(
        **provenance.build(
            config, config["paths"]["domain_map"], config["paths"]["editorial_rules"]
        ),
        **compute(chains, scrubber(config), terms),
    )
    output = Path(args.out).expanduser() if args.out else layout.profile_dir / "edit-delta.json"
    if output.exists():
        try:
            previous = edit_delta.validate(json.loads(read_text(output)))
        except ValueError as exc:
            raise DiagnosticError(
                "read previous edit-delta",
                output,
                str(exc),
                "valid JSON",
                exc,
                "restore or move the previous output before retrying",
            ) from exc
        if previous["chains"] != result["chains"]:
            print(
                DiagnosticError(
                    "compare edit-delta version hashes",
                    output,
                    "version hashes differ from previous output",
                    "unchanged version hashes",
                    None,
                    "review changed chain inputs; this rerun replaces the previous output",
                ),
                file=sys.stderr,
            )
    write_json(output, result)
    for chain in chains:
        args.logger.event(
            record_id=hashlib.sha256(chain["id"].encode()).hexdigest()[:16], rule_id="delta.chain"
        )
    return 0
