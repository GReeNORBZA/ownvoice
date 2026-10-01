"""Concurrent Stage Q dispatch and per-finding schema drops."""

import json

import pytest

from ownvoice.qual import dispatch
from tests import test_dispatch_contract as contract
from tests.test_dispatch_contract import corpus  # noqa: F401  (shared fixture)

ITEM = {
    "dimension": "tone",
    "register": "client",
    "observation": "Steady tone",
    "verbatim_quote": "Steady words [CAP] today.",
    "record_id": "a" * 16,
    "chunk_id": "c",
    "confidence": "high",
}
LONG = {**ITEM, "verbatim_quote": " ".join(["word"] * 26)}


def replaced(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


# The shared stand-in appends to one events file and derives attempts from it,
# which races under concurrency. Here each call writes its own event file, and
# Stage Q calls sleep briefly and record wall-clock start and end.
STAND_IN = replaced(
    replaced(
        replaced(
            contract.STAND_IN,
            "prior = [json.loads(line) for line in events.read_text().splitlines()] "
            "if events.exists() else []",
            "prior = [json.loads(p.read_text()) for p in sorted(events.glob('*.json'))] "
            "if events.exists() else []",
        ),
        'with events.open("a") as stream:\n    stream.write(json.dumps(event) + "\\n")',
        "import time\nevents.mkdir(exist_ok=True)\n"
        "(events / f'{os.getpid()}-{time.time_ns()}.json').write_text(json.dumps(event))",
    ),
    'if mode == "exhaust" or (framing == 1 and attempt == 0):',
    "import time\n"
    "    event['start'] = time.time()\n"
    "    time.sleep(0.5)\n"
    "    event['end'] = time.time()\n"
    "    long = {**item, 'verbatim_quote': ' '.join(['word'] * 26)}\n"
    "    if mode == 'drop' and framing == 1:\n"
    "        out = json.dumps(item) + '\\n' + json.dumps(long) + '\\n'\n"
    "    elif mode == 'drop':\n"
    "        out = ''\n"
    '    elif mode == "exhaust" or (framing == 1 and attempt == 0):',
)


@pytest.fixture
def stand_in(corpus):  # noqa: F811
    corpus.model.write_text(STAND_IN)
    return corpus


def recorded(run):
    return [json.loads(path.read_text()) for path in sorted(run.events.glob("*.json"))]


def only_run(run):
    generated = list(run.directory.glob("synthesis-*"))
    assert len(generated) == 1
    return generated[0]


def test_parse_findings_drops_only_schema_invalid_objects():
    items, rejections = dispatch.parse_findings(json.dumps(ITEM) + "\n" + json.dumps(LONG) + "\n")
    assert [item["verbatim_quote"] for item in items] == [ITEM["verbatim_quote"]]
    assert len(rejections) == 1 and rejections[0].startswith("line 2: ")
    assert "25 words" in rejections[0]


@pytest.mark.parametrize(
    "response",
    ["This is prose.", json.dumps(ITEM) + "\nnot json", "[1, 2]", json.dumps(LONG)],
)
def test_parse_findings_rejects_prose_and_all_invalid_responses(response):
    with pytest.raises((ValueError, TypeError)):
        dispatch.parse_findings(response)


def test_parse_findings_accepts_empty_response():
    assert dispatch.parse_findings("\n  \n") == ([], [])


@pytest.mark.parametrize("value", ["0", "9", "x"])
def test_concurrency_is_bounded(stand_in, value):
    result = contract.run(stand_in, "claude", "normal", "--concurrency", value)
    assert result.returncode != 0
    assert not stand_in.events.exists()


@pytest.mark.parametrize("adapter", ["claude", "codex"])
def test_concurrent_dispatch_overlaps_calls_and_keeps_results(stand_in, adapter):
    result = contract.run(stand_in, adapter, "normal", "--concurrency", "4")
    assert result.returncode == 0, result.stderr
    q = [row for row in recorded(stand_in) if row["stage"] == "Q"]
    # Same calls as sequential dispatch: framing 1 retries once after prose.
    assert sorted((row["chunk"][0], row["framing"], row["attempt"]) for row in q) == [
        ("A", 1, 0),
        ("A", 1, 1),
        ("A", 2, 0),
        ("B", 1, 0),
        ("B", 1, 1),
        ("B", 2, 0),
    ]
    for pass_name in ("A", "B"):
        calls = [row for row in q if row["chunk"][0] == pass_name]
        assert any(
            a["start"] < b["end"] and b["start"] < a["end"]
            for i, a in enumerate(calls)
            for b in calls[i + 1 :]
        ), "expected overlapping Stage Q calls"
    run = only_run(stand_in)
    for pass_name in ("A", "B"):
        manifest = json.loads((run / f"{pass_name}.manifest.json").read_text())
        assert manifest["chunks"][0]["status"] == "done"
        assert manifest["chunks"][0]["attempts"] == 2
        report = json.loads((run / f"{pass_name}.grounded.jsonl.report.json").read_text())
        assert report["kept"] == 1
    findings = json.loads((run / "findings-set.json").read_text())
    assert findings["residual"] == 0 and findings["unresolved_failed"] == 0
    assert "Steady words" not in result.stderr + result.stdout
    assert "Zyxora" not in result.stderr + result.stdout


def test_schema_invalid_finding_is_dropped_without_retry(stand_in):
    result = contract.run(stand_in, "claude", "drop", "--concurrency", "2")
    assert result.returncode == 0, result.stderr
    q = [row for row in recorded(stand_in) if row["stage"] == "Q"]
    assert all(row["attempt"] == 0 for row in q) and len(q) == 4
    assert result.stderr.count("dropped 1 schema-invalid findings") == 2
    assert "invalid return" not in result.stderr
    assert "word word" not in result.stderr + result.stdout
    run = only_run(stand_in)
    for pass_name in ("A", "B"):
        manifest = json.loads((run / f"{pass_name}.manifest.json").read_text())
        assert (manifest["chunks"][0]["status"], manifest["chunks"][0]["attempts"]) == ("done", 1)
        report = json.loads((run / f"{pass_name}.grounded.jsonl.report.json").read_text())
        assert report["kept"] == 1
    payload = next(row for row in recorded(stand_in) if row["stage"] == "S")["payload"]
    assert payload["provenance"]["stage_q_dropped_findings"] == 2
