"""Bounded LLM projection, with no per-source statistics or unapproved phrases."""

import math

from ownvoice.schemas import common, stats_llm


def project(stats, *, eligible, never_hit_min_words):
    registers = {}
    global_rates = stats["registers"]["_global"]["function_words"]
    for name, source in stats["registers"].items():
        row = {key: source[key] for key in ("n", "low_confidence", "derived_from")}
        row["metrics"] = {
            metric: {p: value[p] for p in ("p25", "p50", "p75")}
            for metric, value in source["metrics"].items()
        }
        row["spelling"] = {key: source["spelling"][key] for key in common.SPELLING}
        row["llm_ism_hits"] = source["llm_ism_hits"][:10]
        if name == "_global" and source["never_hit_basis_words"] >= never_hit_min_words:
            row["llm_ism_never_hit"] = source["llm_ism_never_hit"]
        if eligible:
            for key in ("greetings", "signoffs"):
                row[key] = source[key][:5]
            row["ngrams"] = {key: values[:15] for key, values in source["ngrams"].items()}
            for key in ("discourse_markers", "hedges"):
                row[key] = dict(sorted(source[key].items(), key=lambda x: (-x[1], x[0]))[:5])
            if name != "_global":
                rates = source["function_words"]
                ranked = sorted(
                    rates,
                    key=lambda word: (
                        -abs(math.log(rates[word] / global_rates[word]))
                        if rates[word] and global_rates[word]
                        else -math.inf
                        if global_rates[word]
                        else 0,
                        word,
                    ),
                )
                row["function_words"] = {word: rates[word] for word in ranked[:10]}
        registers[name] = row
    return stats_llm.build(
        **{key: stats[key] for key in common.PROVENANCE if key in stats},
        registers=registers,
        contrast=[r for r in stats["contrast"] if r["status"] == "diverging"],
    )
