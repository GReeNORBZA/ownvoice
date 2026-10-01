"""Conservative deterministic comparison, never model adjudication."""

from difflib import SequenceMatcher
from pathlib import Path

from ownvoice.io import write_json
from ownvoice.qual import chunk, ground
from ownvoice.schemas import common, finding, findings_set, qual_diff, qual_report


def empty(prov):
    return findings_set.build(
        **{k: prov[k] for k in common.PROVENANCE if k in prov},
        findings=[],
        changelog=[],
        passes=[],
        residual=0,
        unresolved_failed=0,
    )


def existing(path, prov):
    return findings_set.validate(chunk.read_json(path)) if Path(path).exists() else empty(prov)


def normalized(text):
    return " ".join(text.casefold().split())


def observation_comparison(left, right):
    left, right = normalized(left), normalized(right)
    ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return ("matched" if left == right else "borderline" if ratio >= 0.65 else "new"), ratio


def run(candidate, existing_path, out):
    report = qual_report.validate(chunk.read_json(ground.report_path(candidate)))
    if chunk.digest(chunk.read_text(candidate)) != report["grounded_sha256"] or report["pending"]:
        raise chunk.problem(
            "reconcile qual findings",
            candidate,
            "grounded digest mismatch or pending chunks",
            "unchanged grounded findings from a finished pass",
            "finish dispatch and rerun qual ground",
        )
    prior = existing(existing_path, report)
    expected = "A" if not prior["passes"] else "B" if prior["passes"] == ["A"] else None
    if report["pass"] != expected:
        raise chunk.problem(
            "reconcile qual pass",
            candidate,
            "pass is repeated or out of order",
            "A then B, stopping after B",
            "use the findings set preceding this pass",
        )
    result = {"new": [], "matched": [], "borderline": []}
    candidates = [finding.validate(row) for row in chunk.read_json(candidate, lines=True)]
    if len(candidates) != report["kept"]:
        raise chunk.problem(
            "reconcile qual findings",
            candidate,
            "kept count differs from report",
            "the complete grounded output",
            "rerun qual ground",
        )
    for row in candidates:
        same = [
            f
            for f in prior["findings"]
            if (f["dimension"], f["register"]) == (row["dimension"], row["register"])
        ]
        exact = next(
            (
                f
                for f in same
                if observation_comparison(f["observation"], row["observation"])[0] == "matched"
            ),
            None,
        )
        # Exact normalized observations match. Similar wording is only borderline,
        # so negation and other semantic changes can never silently collapse.
        near = max(
            same,
            key=lambda f: observation_comparison(f["observation"], row["observation"])[1],
            default=None,
        )
        if exact:
            result["matched"].append({"finding": row, "finding_id": exact["finding_id"]})
        elif (
            near
            and observation_comparison(near["observation"], row["observation"])[0] == "borderline"
        ):
            result["borderline"].append({"finding": row, "finding_id": near["finding_id"]})
        else:
            result["new"].append(row)
    value = qual_diff.build(
        **{k: report[k] for k in common.PROVENANCE if k in report},
        **{"pass": report["pass"]},
        existing_sha256=chunk.digest(chunk.read_text(existing_path))
        if Path(existing_path).exists()
        else "0" * 64,
        unresolved_failed=report["unresolved_failed"],
        **result,
    )
    write_json(out, value)
    return value
