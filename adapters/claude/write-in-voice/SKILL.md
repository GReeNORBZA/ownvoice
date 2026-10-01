---
name: write-in-voice
description: Draft in the owner's measured voice and perform at most three real lint passes.
---

Follow sibling PROMPT.md and contract.json in full. The ownvoice package must be
installed. Resolve private paths with `ownvoice config show --format json`.
Use sibling workflow.py for brief validation, register selection and the bounded
lint loop, with this claude session providing the model callback. An interactive
session follows the same loop in PROMPT.md, including exit-4 handling.
No subagent or external model process is needed for drafting. Keep model input
limited to workflow.brief_sections output: Core voice, the chosen register under
§2, §3 edit-delta tendencies and §5 anti-patterns, plus rules and exemplars.
The sibling workflow.py brief-sections subcommand provides the same extraction.
Sections end at equal or higher headings. Exclude §0, §1, §4, §6, Per-source
contrast and other registers. Missing Core voice gives the fixed rebuild note;
a missing chosen register, §3 or §5 stops with a diagnostic.
Retain the final private lint JSON and
deliver the last linted draft with the one-line result and remaining findings.
