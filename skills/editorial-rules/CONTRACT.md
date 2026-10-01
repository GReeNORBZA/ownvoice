# Editorial rules contract

The owner file and blank template contain standalone editorial preferences, not measured voice profiles. The shipped owner file is the author's rules, included as a worked example; users start from the template. Both begin with `# Editorial rules` and require these H2 headings:

- `## Voice and register`
- `## Publishing tiers`
- `## Open-source release gate`
- `## Images and diagrams`
- `## Process`
- `## Inferred, unconfirmed`

Exactly one fenced `ownvoice-rules` block contains TOML with integer `schema_version = 1`. The template contains only that key. Optional spelling is `en-GB-ise`, `en-US` or `none`. Ban entries require a unique id, kind (`word`, `phrase`, `regex`, `char`), pattern, media, severity (`error`, `warn`, `info`) and message. Media are email, article, blog, linkedin, doc and proposal. Limits support `exclamations_max`, `emoji_max`, `em_dashes_max` (nonnegative integers) and `headings_allowed` (boolean), with register overrides under `registers`. Swearing tables list allowed words per medium and globally forbidden words under `never`. The shared rules parser validates this contract. `editorial-rules.ai-tells.example.md` is a generic example ban pack for common AI-writing tells, written against this same contract; copy its entries into a rules file rather than installing it as one.

Prose preserves editorial intent. Inferred observations remain unconfirmed and must never generate machine rules. Do not include card identifiers, fix identifiers, private names, hosts, network addresses, filesystem locations or dangling references. No corpus frequencies or examples identifying correspondents belong here. Synthesis embeds the prose verbatim and records the rules digest; lint consumes only the machine block.

Installation copies skill content and harness adapters, never symlinks. Each installed directory carries `.ownvoice-installed` with tool version and git SHA. Existing unstamped directories require explicit `--force`. Rules default to the template, with `--rules owner` selecting the owner file. The configured editorial rules destination is created only if absent, including when force is requested. `--profile-dir` supplies a bootstrap directory for editorial rules when no configuration exists; an existing configuration remains authoritative. Set `OWNVOICE_CONFIG` to select configuration. Use `--verbose` for resolved installation destinations.
