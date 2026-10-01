"""One conservative ceiling for both LLM-bound profile artefacts."""

import json
import math
from copy import deepcopy

from ownvoice.errors import DiagnosticError
from ownvoice.style.exemplars import summarize

TOKENS_PER_WORD = 1.8
JSON_CHARS_PER_TOKEN = 3.5
STAGE_S_TOKEN_BUDGET = 64000
STAGE_S_OVERHEAD_ALLOWANCE = 3000
STAGE_Q_CALL_CAP = 68


def estimate_synthesis(payload, overhead):
    """Count Stage S prose, all remaining JSON, and prompt/delimiter overhead."""
    metadata = deepcopy(payload)
    word_count = len(metadata["rules"].split())
    metadata["rules"] = ""
    for register in metadata.get("exemplars", {}).get("registers", {}).values():
        for item in register["items"]:
            word_count += len(item["text"].split())
            item["text"] = ""
    for item in (metadata.get("edit_delta") or {}).get("examples", []):
        for key in ("before", "after"):
            word_count += len(item[key].split())
            item[key] = ""
    # Use the dispatch serialization, including escaped characters and all keys.
    chars = len(json.dumps(metadata))
    overhead_estimate = max(
        STAGE_S_OVERHEAD_ALLOWANCE,
        math.ceil(len(overhead.split()) * TOKENS_PER_WORD),
        math.ceil(len(overhead) / JSON_CHARS_PER_TOKEN),
    )
    return (
        math.ceil(word_count * TOKENS_PER_WORD)
        + math.ceil(chars / JSON_CHARS_PER_TOKEN)
        + overhead_estimate
    )


def estimate(stats, exemplars):
    metadata = deepcopy(exemplars)
    word_count = 0
    for register in metadata["registers"].values():
        for item in register["items"]:
            word_count += item["word_count"]
            item["text"] = ""
    # Match the on-disk serialization, retaining text keys and quoting overhead.
    chars = sum(
        len(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)) + 1
        for value in (stats, metadata)
    )
    return math.ceil(word_count * TOKENS_PER_WORD) + math.ceil(chars / JSON_CHARS_PER_TOKEN)


def enforce(stats, exemplars, options):
    budget = options["token_budget"]
    if estimate(stats, exemplars) <= budget:
        return exemplars
    reduced = deepcopy(exemplars)
    minimum = options["exemplars_min"]
    removed = 0
    for register in reduced["registers"].values():
        removed += max(0, len(register["items"]) - minimum)
        register["items"] = register["items"][:minimum]
        summarize(register)
    tokens = estimate(stats, reduced)
    if tokens > budget:
        raise DiagnosticError(
            "profile: token budget exceeded",
            "stats-llm.json + exemplars.json",
            f"estimated {tokens:,} tokens, budget {budget:,} ([profile].token_budget). "
            f"Reduced exemplars to the minimum {minimum} per register "
            f"({removed} items removed); still over by {tokens - budget:,}",
            f"at most {budget:,} estimated tokens",
            None,
            "lower exemplar_words_per_register or raise token_budget",
        )
    return reduced
