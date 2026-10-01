import json
import math
from copy import deepcopy

from ownvoice.schemas import exemplars as schema
from ownvoice.style.budget import enforce, estimate
from ownvoice.style.exemplars import build, summarize
from tests import test_profile
from tests.test_exemplars import options, pool
from tests.test_schemas import PROVENANCE


def test_synthesis_estimate_counts_all_components_without_mutation():
    from ownvoice.style.budget import estimate_synthesis

    payload = {
        "stats": {"registers": {"client": {}, "article": {}}},
        "exemplars": {"registers": {"client": {"items": [{"text": "one two"}]}}},
        "rules": "three four",
        "edit_delta": {"examples": [{"before": "five", "after": "six"}]},
        "findings": [{"observation": "synthetic finding"}],
        "provenance": {"source": "synthetic"},
    }
    original = deepcopy(payload)
    metadata = deepcopy(payload)
    metadata["exemplars"]["registers"]["client"]["items"][0]["text"] = ""
    metadata["rules"] = ""
    metadata["edit_delta"]["examples"][0].update(before="", after="")
    expected = math.ceil(6 * 1.8) + math.ceil(len(json.dumps(metadata)) / 3.5) + 3000
    assert estimate_synthesis(payload, "prompt and delimiters") == expected
    assert payload == original
    for key in ("stats", "findings", "provenance"):
        enlarged = deepcopy(payload)
        enlarged[key] = "x" * 10000
        assert estimate_synthesis(enlarged, "prompt") > expected
    assert estimate_synthesis(payload, "word " * 3000) > expected


def test_estimate_exact_formula_and_successful_reduction():
    examples = build(pool(375), {"corporate"}, options(), PROVENANCE)
    stats = {"synthetic": "statistics"}
    metadata = deepcopy(examples)
    for register in metadata["registers"].values():
        for item in register["items"]:
            item["text"] = ""
    chars = sum(
        len(json.dumps(v, sort_keys=True, ensure_ascii=False, indent=2)) + 1
        for v in (stats, metadata)
    )
    assert estimate(stats, examples) == math.ceil(300 * 1.8) + math.ceil(chars / 3.5)
    reduced = deepcopy(examples)
    register = reduced["registers"]["colleague"]
    register["items"] = register["items"][:10]
    summarize(register)
    ceiling = estimate(stats, reduced)
    assert estimate(stats, examples) > ceiling
    assert enforce(stats, examples, options(token_budget=ceiling)) == reduced
    assert examples["registers"]["colleague"]["selection"]["selected"] == 15
    assert enforce(stats, examples, options(token_budget=estimate(stats, examples))) is examples


class TestBudgetProfile:
    def setup_method(self):
        self.harness = test_profile.ProfileTests()
        self.harness.setUp()

    def teardown_method(self):
        self.harness.doCleanups()

    def test_subprocess_budget_failure_numbers_and_no_outputs(self):
        h = self.harness
        h.configure(eligible=True)
        h.config.write_text(
            h.config.read_text().replace("[profile]", "[profile]\ntoken_budget = 1")
        )
        h.inputs([h.row(1, "one two three four five six seven eight")])
        result = h.cli()
        assert result.returncode == 2
        for text in (
            "profile: token budget exceeded",
            "stats-llm.json + exemplars.json",
            "estimated",
            "budget 1",
            "minimum 10 per register",
            "items removed",
            "still over by",
            "expected",
            "next step:",
            "raise token_budget",
        ):
            assert text in result.stderr
        import re

        match = re.search(r"estimated ([\d,]+) tokens.*still over by ([\d,]+)", result.stderr)
        assert match
        assert int(match[1].replace(",", "")) - 1 == int(match[2].replace(",", ""))
        assert not (h.work / "profile/ownvoice/exemplars.json").exists()
        assert not (h.work / "profile/ownvoice/stats-llm.json").exists()

    def test_private_contract_byte_identical_reruns_and_shared_ceiling(self):
        h = self.harness
        h.configure(eligible=True)
        rows = pool(30, source="old")
        h.inputs(rows)
        result = h.cli()
        assert result.returncode == 0, result.stderr
        root = h.work / "profile/ownvoice"
        path = root / "exemplars.json"
        examples = schema.validate(json.loads(path.read_text()))
        stats = json.loads((root / "stats-llm.json").read_text())
        assert estimate(stats, examples) <= options()["token_budget"]
        assert examples["registers"]["colleague"]["selection"]["selected"] == 10
        assert path.stat().st_mode & 0o777 == 0o600
        assert root.stat().st_mode & 0o777 == 0o700
        before = {p.name: p.read_bytes() for p in root.glob("*.json")}
        result = h.cli()
        assert result.returncode == 0, result.stderr
        assert before == {p.name: p.read_bytes() for p in root.glob("*.json")}

    def test_historical_report_does_not_override_current_eligibility(self):
        h = self.harness
        h.configure(eligible=True)
        h.inputs(pool(3, source="old"))
        report = h.work / "sources/old/ingest-report.json"
        value = json.loads(report.read_text())
        value["llm_eligible"] = False
        from ownvoice.io import write_json

        write_json(report, value)
        result = h.cli()
        assert result.returncode == 0, result.stderr
        value = json.loads((h.work / "profile/ownvoice/exemplars.json").read_text())
        assert all(
            r["selection"]["status"] != "no_llm_eligible_source"
            for r in value["registers"].values()
        )
        assert len(value["registers"]["colleague"]["items"]) == 3
