---
name: voice-profile-build
description: Build a private measured voice profile with bounded qualitative extraction and checked synthesis.
---

Follow sibling PROMPT.md and contract.json. The ownvoice package must be installed.
Resolve private paths with `ownvoice config show --format json`.
Workflow: run `python dispatch.py --adapter claude` from this skill directory
(add --config or --profile-dir only when selecting explicit private locations;
add --concurrency N, 1-8, to run Stage Q calls in parallel).
The sibling script is installed with the neutral prompt. In the source tree,
the equivalent entry point is this adapter's dispatch.py.

The Workflow dispatch code grants no built-in tools (`--tools ""`), no MCP tools
(strict empty MCP configuration), disables skills and session persistence,
and runs each call with an empty temporary cwd. It inlines delimited chunk
data and returns only counts to the orchestrator. Never dispatch from prose
or read the corpus in the orchestrating conversation. A/B then stop, one
synthesis call, mechanical checks, private publication, then chunk cleanup.

`profile --articles` supplies bound article finals to their own Stage Q chunks.
Both passes are planned before calls, with a 68-call cap and only the email
sample reduced. Stats-only runs send no article text. Stage S receives a separate
CROSS_REGISTER block and returns core_voice as {group_id, pattern, quotes} items,
each with 2-3 exact group quotes labelled by at least two registers. The script
checks these and writes the unnumbered Core voice section before section 2,
or the fixed unavailable text. The existing precedence order remains unchanged.
