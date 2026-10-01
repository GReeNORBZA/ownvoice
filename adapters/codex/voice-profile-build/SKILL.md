---
name: voice-profile-build
description: Build a private measured voice profile with bounded qualitative extraction and checked synthesis.
---

Follow sibling PROMPT.md and contract.json. The ownvoice package must be installed.
Resolve private paths with `ownvoice config show --format json`.
Run `python dispatch.py --adapter codex` from this skill directory (add --config
or --profile-dir only when selecting explicit private locations; add --concurrency
N, 1-8, to run Stage Q calls in parallel). The sibling
script is installed with the neutral prompt. In the source tree, the equivalent
entry point is this adapter's dispatch.py.

The code loops over `codex exec` in a read-only sandbox, with network off,
web search disabled, ignored user configuration, disabled shell/app/agent
features, empty MCP configuration, ephemeral sessions and an empty temporary
cwd. This is the restrictive adapter mode, not a claim that Codex has a verified
true no-tools mode. Model-provider transport remains necessary. Local readable
files are not isolated by a read-only sandbox. Unsupported flags fail closed.
See the official configuration reference:
https://developers.openai.com/codex/config-reference

Chunk text is inlined as delimited data. Do not read chunks or finding bodies
in the orchestrator. Observe counts only. Run A then B and stop, one synthesis
call, mechanical checks, private publication, then chunk cleanup.

`profile --articles` supplies bound article finals to their own Stage Q chunks.
Both passes are planned before calls, with a 68-call cap and only the email
sample reduced. Stats-only runs send no article text. Stage S receives a separate
CROSS_REGISTER block and returns core_voice as {group_id, pattern, quotes} items,
each with 2-3 exact group quotes labelled by at least two registers. The script
checks these and writes the unnumbered Core voice section before section 2,
or the fixed unavailable text. The existing precedence order remains unchanged.
