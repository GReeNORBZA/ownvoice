"""--resume-run repeats only Stage S on a run whose Stage Q passes completed."""

import json

from tests import test_dispatch_contract as contract
from tests.test_dispatch_contract import corpus  # noqa: F401  (shared fixture)


def stage_counts(ctx):
    calls = contract.events(ctx)
    return sum(row["stage"] == "Q" for row in calls), sum(row["stage"] == "S" for row in calls)


def failed_run(ctx):
    result = contract.run(ctx, "claude", "bad_name")
    assert result.returncode != 0
    assert "validate profile synthesis" in result.stderr
    runs = list(ctx.directory.glob("synthesis-*"))
    assert len(runs) == 1
    assert not (ctx.directory / "voice-profile.md").exists()
    return runs[0]


def test_resume_repeats_only_stage_s(corpus):  # noqa: F811
    run = failed_run(corpus)
    q_before, s_before = stage_counts(corpus)
    # The failed run retried Stage S up to qual_retries (2) times.
    assert q_before == 6 and s_before == 3
    result = contract.run(corpus, "claude", "normal", "--resume-run", str(run))
    assert result.returncode == 0, result.stderr
    assert stage_counts(corpus) == (q_before, s_before + 1)
    assert list(corpus.directory.glob("synthesis-*")) == [run]
    profile = (corpus.directory / "voice-profile.md").read_text()
    assert "qualitative profile" in profile
    payload = [row for row in contract.events(corpus) if row["stage"] == "S"][-1]["payload"]
    assert payload["provenance"]["unresolved_failed"] == 0
    assert set(payload["provenance"]["sample_sizes"]) == {"A", "B"}
    assert payload["findings"]


def test_resume_refuses_stale_or_foreign_runs(corpus, tmp_path):  # noqa: F811
    run = failed_run(corpus)
    foreign = tmp_path / "synthesis-elsewhere"
    foreign.mkdir()
    result = contract.run(corpus, "claude", "normal", "--resume-run", str(foreign))
    assert result.returncode != 0
    assert "not a completed Stage Q run" in result.stderr
    # The run was planned under a different config than the current profile inputs.
    manifest = run / "A.manifest.json"
    value = json.loads(manifest.read_text())
    value["config_digest"] = "0" * 64
    manifest.write_text(json.dumps(value))
    result = contract.run(corpus, "claude", "normal", "--resume-run", str(run))
    assert result.returncode != 0
    assert "run planned under different inputs: config_digest" in result.stderr
    _, s_calls = stage_counts(corpus)
    assert s_calls == 3
