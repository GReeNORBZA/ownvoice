"""BR4-002: deterministic article sampling and the independent article word cap."""

import copy
import hashlib
from itertools import pairwise, permutations

import pytest

from ownvoice.io import PRIVATE_LINE, write_jsonl
from ownvoice.qual import chunk, sample
from ownvoice.schemas import manifest
from tests.test_qual import corpus, ok  # noqa: F401  (shared fixture and CLI helper)


def article_budget_rows():
    from ownvoice.schemas import article_records

    # Input, record-id and SHA orders differ. SHA order is 2, 3, 1, 4.
    return [
        article_records.build(
            record_id=f"{identifier:016x}",
            source="articles",
            recipient_class="article",
            year=None,
            word_count=count,
            text=" ".join(["synthetic"] * count),
            truncated=False,
        )
        for identifier, count in ((4, 10), (3, 80), (2, 90), (1, 20))
    ]


def test_article_sha_order_and_cumulative_cap_skip_to_fit():
    rows = article_budget_rows()
    original = copy.deepcopy(rows)
    expected_ids = [f"{identifier:016x}" for identifier in (2, 1, 4)]
    for permuted in permutations(rows):
        selected = sample.articles(permuted, 120, 100)
        assert [row["record_id"] for row in selected] == expected_ids
        assert [row["word_count"] for row in selected] == [90, 20, 10]
        assert sum(row["word_count"] for row in selected) == 120
    assert rows == original


@pytest.mark.parametrize("pass_name", ["A", "B"])
def test_article_chunk_selection_independent_of_email_budget(corpus, pass_name):  # noqa: F811
    root, config, _ = corpus
    config.write_text(
        config.read_text() + "\n[profile]\nqual_sample_words = 120\nqual_max_record_words = 100\n"
    )
    rows = article_budget_rows()
    by_id = {row["record_id"]: row for row in rows}
    expected_groups = (
        [[f"{identifier:016x}" for identifier in (2, 1, 4)]]
        if pass_name == "A"
        else [[f"{1:016x}"], [f"{identifier:016x}" for identifier in (2, 4)]]
    )
    max_tokens = 10000 if pass_name == "A" else 220
    orders = [
        rows,
        sorted(rows, key=lambda row: row["record_id"]),
        sorted(rows, key=lambda row: hashlib.sha256(row["record_id"].encode()).digest()),
    ]
    for order_index, ordered in enumerate(orders):
        articles_path = root / "articles.jsonl"
        write_jsonl(articles_path, ordered)
        for email_cap in (120, 1):
            output = root / f"articles-{pass_name}-{order_index}-{email_cap}" / "manifest.json"
            ok(
                config,
                "qual",
                "chunk",
                "--records",
                root / "work" / "records.jsonl",
                "--articles",
                articles_path,
                "--pass",
                pass_name,
                "--sample-words",
                email_cap,
                "--max-tokens",
                max_tokens,
                "--out",
                output,
            )
            value = manifest.validate(chunk.read_json(output))
            article_chunks = [c for c in value["chunks"] if c["source"] == "articles"]
            assert [c["record_ids"] for c in article_chunks] == expected_groups
            email_chunks = [c for c in value["chunks"] if c["source"] != "articles"]
            assert bool(email_chunks) is (email_cap == 120)
            for c in value["chunks"]:
                assert c["est_tokens"] <= max_tokens
                assert all(rid in by_id for rid in c["record_ids"]) is (c["source"] == "articles")
            for c in article_chunks:
                assert c["registers"] == ["article"]
                text = chunk.read_text(c["text_path"])[len(PRIVATE_LINE) + 1 :]
                assert [span["record_id"] for span in c["records"]] == c["record_ids"]
                for span in c["records"]:
                    assert text[span["start"] : span["end"]] == by_id[span["record_id"]]["text"]
            if pass_name == "B":
                # Each boundary is necessary; each accepted group fits the ceiling.
                for left, right in pairwise(article_chunks):
                    combined = [by_id[rid] for rid in left["record_ids"] + right["record_ids"][:1]]
                    assert chunk.estimate(combined) > max_tokens
                assert chunk.estimate([by_id[rid] for rid in expected_groups[1]]) <= max_tokens
