"""Stage S replies: one outer fence is tolerated; a rejected reply is kept privately."""

import json

import pytest

from ownvoice.errors import DiagnosticError
from ownvoice.io import PRIVATE_LINE
from ownvoice.qual import dispatch
from tests import test_dispatch_contract as contract
from tests.test_dispatch_contract import corpus  # noqa: F401  (shared fixture)

SECTIONS = {"1": "Rules first.", "2": {"client": "Client guidance."}, "3": "Edits.", "5": "Avoid."}


@pytest.mark.parametrize(
    "wrap", ["{}", "```json\n{}\n```", "```\n{}\n```\n", "  ```JSON\n{}\n```  "]
)
def test_outer_fence_is_tolerated(wrap):
    reply = wrap.replace("{}", json.dumps(SECTIONS))
    assert dispatch.parse_sections(reply, {"client"})["1"] == "Rules first."


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "Here is the profile:\n```json\n" + json.dumps(SECTIONS) + "\n```",
        "```json\n" + json.dumps(SECTIONS) + "\n```\nHope this helps.",
    ],
)
def test_prose_or_partial_fences_still_rejected(reply):
    with pytest.raises(DiagnosticError, match="parse synthesis response"):
        dispatch.parse_sections(reply, {"client"})


def test_rejected_reply_is_kept_privately(corpus):  # noqa: F811
    result = contract.run(corpus, "claude", "bad_name")
    assert result.returncode != 0
    (run,) = corpus.directory.glob("synthesis-*")
    saved = (run / "S.response.md").read_text()
    assert saved.startswith(PRIVATE_LINE + "\n")
    assert json.loads(saved.split("\n", 1)[1])["3"] == "Zyxora"
    assert "Zyxora" not in result.stderr + result.stdout
