import hashlib
from copy import deepcopy

import pytest

from ownvoice.config import DEFAULTS
from ownvoice.errors import DiagnosticError
from ownvoice.schemas import exemplars
from ownvoice.style.exemplars import apportion, build, select_register, shingles
from tests.test_schemas import PROVENANCE, samples


def pool(count, length=20, start=0, source="corporate"):
    rows = []
    for i in range(start, start + count):
        row = deepcopy(samples()["records"])
        # Unique alphabetic words, not numeric suffixes discarded by the tokenizer.
        token = "word" + chr(97 + i // 26 // 26) + chr(97 + i // 26 % 26) + chr(97 + i % 26)
        row.update(
            record_id=f"{i:016x}", source=source, word_count=length, text=" ".join([token] * length)
        )
        rows.append(row)
    return rows


def options(**changes):
    return {**DEFAULTS["profile"], **changes}


def ids(result):
    return [r["record_id"] for r in result["items"]]


def ordered(rows):
    return sorted(rows, key=lambda r: hashlib.sha256(r["record_id"].encode()).hexdigest())


def test_hash_spaced_picks_quota_clamps_and_order_independence():
    for count, quota in ((30, 10), (375, 15), (550, 20)):
        rows = pool(count)
        result = select_register(rows, {"corporate"}, options())
        # One occupied stratum: hand-computed midpoint positions in SHA-256 order.
        positions = [(2 * i + 1) * count // (2 * quota) for i in range(quota)]
        expected = [ordered(rows)[i]["record_id"] for i in positions]
        assert ids(result) == expected
        assert result == select_register(list(reversed(rows)), {"corporate"}, options())
        assert 10 <= result["selection"]["selected"] <= 20
        assert result["selection"]["words"] <= 800


def test_tertiles_use_all_records_boundary_ties_and_fractional_schema():
    rows = pool(3, 10) + pool(3, 20, 3) + pool(3, 30, 6)
    rows[-1]["sensitive"] = True
    result = select_register(rows, {"corporate"}, options())
    # Inclusive ranks 8/3 and 16/3 interpolate 10->20 and 20->30.
    assert [s["boundaries"] for s in result["selection"]["strata"]] == [
        [10, 50 / 3],
        [50 / 3, 70 / 3],
        [70 / 3, 30],
    ]
    assert [s["eligible"] for s in result["selection"]["strata"]] == [3, 3, 2]
    assert result["selection"]["strata"][2]["eligibility_rate"] == 2 / 3
    exemplars.validate(build(rows, {"corporate"}, options(), PROVENANCE))
    tied = pool(2, 10) + pool(2, 20, 2)
    # Inclusive cuts land exactly on 10 and 20. Equality goes to the lower stratum.
    result = select_register(tied, {"corporate"}, options())
    assert [r["stratum"] for r in result["items"]].count(0) == 2
    assert [r["stratum"] for r in result["items"]].count(1) == 2
    assert result["selection"]["coverage"] == "partial"


def test_largest_remainder_capacity_and_source_floor():
    # Reserve [2,2,2], then allocate four shares 2.4,1.2,0.4. The tie goes to index 0.
    assert apportion([60, 30, 10], 10, [2, 2, 2]) == [5, 3, 2]
    assert apportion([1, 100, 100], 10, [1, 2, 2]) == [1, 5, 4]
    rows = pool(29) + pool(1, start=29, source="current")
    result = select_register(rows, {"corporate", "current"}, options())
    # Reserve one each, remaining eight round 7.733/0.267 to 8/0.
    assert result["selection"]["by_source"] == {"corporate": 9, "current": 1}
    expected_old = [ordered(rows[:29])[(2 * i + 1) * 29 // 18]["record_id"] for i in range(9)]
    assert ids(result) == [expected_old[0], rows[-1]["record_id"], *expected_old[1:]]
    with pytest.raises(DiagnosticError) as caught:
        apportion([10, 10, 10], 2, [2, 2, 2])
    for part in (
        "allocate exemplar quota",
        "exemplars_min",
        "floors total 6",
        "quota 2",
        "expected",
        "next step:",
    ):
        assert part in str(caught.value)


def test_round_robin_cap_stops_without_skipping_to_shorter_candidate():
    rows = pool(150, 20) + pool(150, 50, 150) + pool(150, 80, 300)
    result = select_register(rows, {"corporate"}, options())
    # k=18 gives six per stratum. Five complete rounds=750, then 20=770.
    # Next 50 cannot fit: stop, rather than seeking another 20-word candidate.
    expected = []
    groups = [ordered(rows[start : start + 150]) for start in (0, 150, 300)]
    for rank in range(6):
        for stratum in range(3):
            if len(expected) == 16:
                break
            expected.append(groups[stratum][(2 * rank + 1) * 150 // 12]["record_id"])
    assert ids(result) == expected
    assert result["selection"]["words"] == 770
    assert [r["stratum"] for r in result["items"]] == [0, 1, 2] * 5 + [0]


def test_jaccard_skip_next_hash_candidate_and_wrap():
    rows = pool(30)
    hashed = ordered(rows)
    # q=10, midpoint positions 1,4,...,28. Make 4 and 28 duplicate pick 1.
    hashed[4]["text"] = hashed[1]["text"]
    hashed[28]["text"] = hashed[1]["text"]
    hashed[29]["text"] = hashed[1]["text"]
    expected_positions = [1, 5, 7, 10, 13, 16, 19, 22, 25, 0]
    result = select_register(rows, {"corporate"}, options())
    assert ids(result) == [hashed[i]["record_id"] for i in expected_positions]
    assert shingles("One two three four five six seven eight") == {
        ("one", "two", "three", "four", "five"),
        ("two", "three", "four", "five", "six"),
        ("three", "four", "five", "six", "seven"),
        ("four", "five", "six", "seven", "eight"),
    }


def test_jaccard_threshold_is_strict_and_exhaustion_terminates():
    rows = pool(30, 8)
    hashed = ordered(rows)
    hashed[1]["text"] = "one two three four five six seven eight"
    hashed[4]["text"] = "one two three four five six seven nine"
    # Four shingles each, intersection three / union five = exactly 0.6, so retain.
    result = select_register(rows, {"corporate"}, options())
    assert ids(result)[:2] == [hashed[1]["record_id"], hashed[4]["record_id"]]
    for row in rows:
        row["text"] = hashed[1]["text"]
    result = select_register(rows, {"corporate"}, options())
    assert ids(result) == [hashed[1]["record_id"]]


@pytest.mark.parametrize(
    "change",
    ["confidence", "inline_reply", "template", "sensitive", "residual", "source", "short", "long"],
)
def test_every_eligibility_filter(change):
    rows = pool(2)
    row = rows[1]
    if change == "confidence":
        row["strip"]["confidence"] = "low"
    elif change == "inline_reply":
        row["strip"]["inline_reply"] = True
    elif change in ("template", "sensitive"):
        row[change] = True
    elif change == "residual":
        row["scrub"]["residual_capitalised"] = ["Synthetic"]
    elif change == "source":
        row["source"] = "unapproved"
    else:
        row["word_count"] = 7 if change == "short" else 81
    result = select_register(rows, {"corporate"}, options())
    assert ids(result) == [rows[0]["record_id"]]
    assert result["low_confidence"]


def test_thin_takes_all_even_similar_and_no_source_is_not_low_confidence():
    rows = pool(3, 8) + pool(2, 80, 3)
    rows[1]["text"] = rows[0]["text"]
    result = select_register(rows, {"corporate"}, options())
    assert set(ids(result)) == {r["record_id"] for r in rows}
    assert result["low_confidence"]
    assert result["selection"]["selected"] == 5
    assert result["selection"]["words"] == 184
    assert select_register([], {"corporate"}, options())["items"] == []
    for register in build(rows, set(), options(), PROVENANCE)["registers"].values():
        assert register["items"] == []
        assert register["selection"]["status"] == "no_llm_eligible_source"
        assert not register["low_confidence"]
