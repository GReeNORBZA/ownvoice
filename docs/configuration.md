# Configuration

ownvoice reads two private TOML files: `config.toml` and a recipient map, `domain-map.toml`. The optional edit-delta step reads a third, `chains.toml`. This page describes each format and ends with a first-run walkthrough.

Complete examples ship in the repository:

- [`examples/config.example.toml`](../examples/config.example.toml)
- [`examples/example-domain-map.toml`](../examples/example-domain-map.toml)

All three files describe your own mail and correspondents. Keep them, your mailboxes and everything under `work_dir` outside every git working tree.

## Where ownvoice looks for its configuration

ownvoice uses the first of these that is set:

1. `--config PATH`, given before the command: `ownvoice --config PATH ingest`.
2. The `OWNVOICE_CONFIG` environment variable.
3. `~/.config/ownvoice/config.toml`.

`config.toml` names the domain map and the editorial rules file in its `[paths]` table. Relative paths in `config.toml` resolve against the directory that holds `config.toml`, and `~` is expanded.

To check both files:

```sh
ownvoice config show              # resolved output paths, on stderr
ownvoice config show --format json  # the same paths as JSON, on stdout
```

`config show` validates `config.toml` and `domain-map.toml` together and reports every problem in one pass, with the key and line number for each. It exits 0 when both are valid and 2 when either has a problem. It never prints owner or correspondent addresses.

## config.toml

### Top level

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `schema_version` | integer | yes | Must be `1`. |

The file must also contain an `[owner]` table, a `[paths]` table and at least one `[[source]]` table. `[ingest]`, `[profile]` and `[llm]` are optional.

### [owner]

All three keys are required.

| Key | Type | Notes |
|-----|------|-------|
| `addresses` | list of strings, at least one | Your sending addresses. For mbox and eml sources, a message is selected when its From address matches one of these (case-insensitive). |
| `names` | list of strings, at least one | The forms of your own name. They are kept in greetings and sign-offs and never masked. |
| `timezone` | string | An IANA timezone key, for example `Europe/London`. Used for weekday and hour buckets. |

### [paths]

All three keys are required and must be nonempty. Any other key in this table is an error.

| Key | Notes |
|-----|-------|
| `work_dir` | Directory for all private outputs. It must not be inside a git working tree. Profile outputs go under `work_dir/profile/ownvoice/`. |
| `domain_map` | Path to `domain-map.toml`. The file must exist and be valid for any command that loads configuration. |
| `editorial_rules` | Path to your editorial rules Markdown file. `scripts/install-skills.sh` creates it from a template if it does not exist. `ingest`, `profile` and `lint` record its hash, so the file must exist before you run them. |

### [[source]]

One table per mailbox. Repeat the table for each mailbox. When the same message appears in more than one source, the earlier source wins.

| Key | Type | Required | Default | Notes |
|-----|------|----------|---------|-------|
| `label` | string | yes | | Unique. 1 to 32 characters from `a-z`, `0-9` and `-`. Used to name outputs and in `--only`, `--reparse`, `--restart` and `--sources`. |
| `kind` | string | yes | | `pst`, `mbox` or `eml`. An `eml` path may be a single file or a directory searched recursively for `*.eml`. |
| `path` | string | yes | | Path to the mailbox. |
| `reader` | string | no | `pffexport` | `pst` only: `pffexport` or `readpst`. Setting it on another kind is an error. |
| `owner_addresses` | list of strings | no | `[]` | Extra From addresses for this source, added to `[owner].addresses`. |
| `sent_folders` | list of strings, at least one | no | `[ingest].sent_folders` | PST folder names to select mail from. Only PST ingestion uses folders. |
| `timezone` | string | no | `[owner].timezone` | IANA key for this source's buckets. |
| `era` | inline table | no | none | `{ from_year = 2015, to_year = 2020 }`. Integers from 1 to 9999, with `from_year <= to_year`. Messages dated outside the range are rejected. |
| `allow_inside_git_tree` | boolean | no | `false` | ingest refuses a source inside a git working tree unless this is `true`. |
| `llm_eligible` | boolean | no | `false` | See [LLM eligibility](#llm-eligibility-and-the-llm-table). |

How messages are selected depends on the kind:

- **pst**: the reader exports the whole PST, then ownvoice keeps only mail in folders named in `sent_folders` (case-insensitive). It does not filter by sender. Mail filed in other folders is excluded. `pffexport` comes from the `pff-tools` package and `readpst` from `pst-utils`.
- **mbox and eml**: a message is kept when its From address is in `[owner].addresses` or the source's `owner_addresses`, or when its `X-Gmail-Labels` header includes `Sent`. Messages whose `X-Gmail-Labels` header includes any label in `[ingest].takeout_excluded_labels` are rejected.

OST files are not supported.

### [ingest]

Every key is optional. Unset keys take the defaults shown.

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `sent_folders` | list of strings, at least one | `["Sent Items", "Sent", "Sent Mail"]` | Default PST folder names for every PST source. |
| `readpst_jobs` | integer, 0 or more | `0` | `readpst` only: parallel jobs passed to `readpst -j`. `0` means none, which keeps output deterministic. |
| `checkpoint_every` | integer, 1 or more | `500` | Messages between resume checkpoints. |
| `mobile_footers` | list of strings | `["Sent from my iPhone", "Sent from my iPad", "Get Outlook for iOS", "Get Outlook for Android"]` | Footer lines stripped from bodies. |
| `valedictions` | list of strings | `["Kind regards", "Regards", "Best", "Thanks", "Thank you", "Cheers", "Speak soon"]` | Sign-off phrases used to find the sign-off and signature. |
| `reply_prefixes` | list of strings | `["RE:", "Re:", "AW:", "SV:", "RV:", "Antw:"]` | Subject prefixes that mark a reply. |
| `takeout_excluded_labels` | list of strings | `["Chat", "Drafts", "Spam", "Trash"]` | mbox and eml only: `X-Gmail-Labels` values whose messages are rejected. |
| `extra_attribution_patterns` | list of regular expressions | `[]` | Extra patterns for quoted-reply attribution lines, such as a non-English "wrote:" line. Each must compile. |
| `deny_terms_file` | string | `""` | Optional path to a file of extra terms to mask. |
| `sensitive_terms` | string | `"builtin"` | `"builtin"` uses the shipped list; a path extends the shipped list with your file; `"none"` turns the list off. An empty string is an error. |
| `softeners` | string | `""` | Optional path to a file that extends the shipped softener list. |

Lists of strings must not contain empty strings.

### [profile]

Every key is optional. Unset keys take the defaults shown.

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `exemplars_min` | integer, 1 or more | `10` | Minimum exemplars per register. |
| `exemplars_max` | integer, 1 or more | `20` | Maximum exemplars per register. Must be at least `exemplars_min`. |
| `exemplar_words_per_register` | integer, 1 or more | `800` | Cap on verbatim exemplar words per register. |
| `token_budget` | integer, 1 or more | `25000` | Ceiling for the estimated size of `stats-llm.json` plus `exemplars.json`. |
| `thin_register_min` | integer, 1 or more | `30` | Registers with fewer records are flagged low confidence. |
| `current_source` | string | `""` | Source label used as the default where sources differ. Empty means the last `[[source]]`. Must name an existing source. |
| `never_hit_min_words` | integer, 1 or more | `50000` | Corpus words needed before a never-used phrase counts as a lint error. |
| `qual_sample_words` | integer, 1 or more | `5000` | Words sampled per source and register for the qualitative pass. |
| `qual_max_record_words` | integer, 1 or more | `2000` | Longer records are not sampled for the qualitative pass. |
| `qual_retries` | integer, 0 or more | `2` | Retries per failed qualitative chunk. |
| `llm_ism_lexicon` | string | `""` | Optional path to a file that replaces the shipped list of LLM-typical words. |
| `baseline_before` | string | not set | Optional `"YYYY-MM-DD"` date. When set, `profile` uses only records dated before it, and the article register is built from long emails. Leave the key out for no cutoff. |
| `articles_llm_eligible` | boolean | not set (false) | Optional. When `true`, scrubbed text from your draft chains can reach the model: article sample chunks, article exemplars and phrase tables, and edit-delta before-and-after examples. Leave it out to keep article and draft text local. See [LLM eligibility](#llm-eligibility-and-the-llm-table). |

### LLM eligibility and the [llm] table

ownvoice itself makes no network calls. The skills it installs run inside your agent harness, and they read ownvoice outputs. `llm_eligible` decides which of your text those outputs contain:

- `llm_eligible = false` (the default): the source contributes only aggregate statistics, such as metric quantiles and counts. No text from it appears in exemplars, phrase tables or qualitative sample chunks.
- `llm_eligible = true`: scrubbed text from the source can appear in exemplars, phrase tables and qualitative sample chunks, which the skills pass to whatever model provider your harness uses.

If no source is eligible, the profile is statistics only.

Article and draft text has its own switch, `[profile] articles_llm_eligible`, which email eligibility never implies:

- Not set or `false` (the default): chain finals and drafts contribute only statistics. No article text appears in article exemplars, article phrase tables or qualitative sample chunks, and the edit-delta chains, examples and substitutions are withheld from model input. `qual chunk --articles` refuses to run.
- `true`: scrubbed article text can appear in qualitative sample chunks (up to `qual_sample_words` words, each piece cut at `qual_max_record_words`), in up to `exemplar_words_per_register` words of article exemplars, and in up to 20 edit-delta examples of at most 60 words per side.

When any source has `llm_eligible = true`, or `articles_llm_eligible = true`, every `[llm]` key must be a nonempty string, and `attestation` must contain a valid `YYYY-MM-DD` date. Otherwise the table is optional and each key, if present, must be a string.

| Key | Notes |
|-----|-------|
| `provider` | The model provider and product your harness uses. |
| `retention_terms` | The provider's data-retention terms you rely on. |
| `training_use` | The provider's terms on training use you rely on. |
| `attestation` | A dated statement that you have the right to process the eligible sources with that provider. |

These values are copied into profile provenance.

### Changing configuration later

Outputs record digests of the configuration, the domain map, the editorial rules and the scrub term lists. After a change, ownvoice refuses outputs that no longer match and names the fix: `ingest --reparse LABEL` when the scrub term lists (`sensitive_terms`, `deny_terms_file`) changed, or rerunning the command (for example `profile`) when other configuration changed. After editing the domain map, reparse the affected sources yourself (step 5 below).

## domain-map.toml

The domain map assigns each recipient a class. Each message then gets one recipient class, which becomes its register.

| Key | Type | Required | Default | Notes |
|-----|------|----------|---------|-------|
| `schema_version` | integer | yes | | Must be `1`. |
| `classes` | list of strings | no | all eight classes | If present, must list each class below exactly once. It cannot add or remove classes. |
| `precedence` | list of strings | no | `["cold", "client", "vendor", "professional-warm", "colleague", "personal", "unknown"]` | If present, must list every class except `group` exactly once. |
| `group_threshold` | integer, 1 or more | no | `4` | A message with this many recipients or more is classed `group`. |
| `[addresses]` | table | no | empty | Exact address to class. |
| `[domains]` | table | no | empty | Domain to class. |
| `[x500]` | table | no | empty | X.500 organisation to class. |
| `[names]` | table | no | empty | Display name to class. |

Every value in the four mapping tables must be one of the recipient classes. Keys are matched case-insensitively, so two keys that differ only in case are an error.

### How a message is classified

1. ownvoice counts the To and Cc recipients, plus Bcc where the sent copy records it. If the count is at least `group_threshold`, the message is `group`.
2. Otherwise each recipient is resolved by the first step that matches:
   1. An SMTP address: an exact `[addresses]` entry, then the longest matching `[domains]` suffix. `example.com` matches `example.com` and `mail.example.com`.
   2. A legacy Exchange X.500 address (`/O=Example Org/OU=.../CN=...`): the `/O=` value is looked up in `[x500]`.
   3. The display name, looked up in `[names]`.
   4. Otherwise the recipient is `unknown`.
3. The message takes the first class in `precedence` that any of its recipients has.

`group` is assigned only by recipient count. Because it is not in `precedence`, mapping an entry to `group` has no effect.

Older Exchange PSTs often record recipients inside your own organisation only as an X.500 address, with no SMTP address. Map your organisation's `/O=` value to `colleague` in `[x500]` to classify them.

What each reader provides: `pffexport` gives addresses and display names, so all steps apply. `readpst` gives display names only, plus any token containing `@`. mbox and eml give addresses and display names.

Addresses and display names are used in memory only and are never written to records.

### Recipient classes

The set of classes is fixed. You cannot add, rename or remove classes.

| Class | Meaning |
|-------|---------|
| `personal` | Friends and family. |
| `professional-warm` | Professional contacts you know well. |
| `colleague` | People inside your own organisation. |
| `client` | Clients and customers. |
| `vendor` | Suppliers. |
| `cold` | First contact with people you do not know. |
| `group` | Messages at or above `group_threshold` recipients. |
| `unknown` | Recipients nothing in the map matches. |

`profile` also builds an `article` register for long-form writing. It is not a recipient class and cannot appear in the domain map.

## chains.toml

A chain is a sequence of versions of one piece of writing, oldest first. `ownvoice edit-delta --chains chains.toml` measures what changed between versions. `ownvoice profile --articles chains.toml` uses the final version of each chain as long-form writing for the article register. Chain text stays out of model input unless `articles_llm_eligible = true`.

```toml
schema_version = 1

[[chain]]
id = "example-post"
origin = "llm"
versions = [
  "drafts/example-post-draft.md",
  "drafts/example-post-second.md",
  "posts/example-post.md",
]

[[chain]]
id = "another-post"
origin = "owner"
git = { repo = "~/src/site", path = "posts/another-post.md", follow = true }
```

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `schema_version` | integer | yes | Must be `1`. |
| `[[chain]]` | array of tables | yes | At least one. |
| `id` | string | yes | Nonempty and unique. |
| `origin` | string | yes | `llm` if the first version was written by a model, otherwise `owner`. Before-and-after metric changes are measured on `llm` chains. |
| `versions` | list of strings | one of `versions` or `git` | At least two paths, oldest first. |
| `git` | inline table | one of `versions` or `git` | `repo` (path to a git repository), `path` (file path inside it) and `follow` (boolean, required). Each commit that touched the file becomes one version, oldest first. With `follow = true`, renames are followed. |

Relative paths in `versions` and `git.repo` resolve against the directory that holds `chains.toml`. Unknown keys are an error. Every chain must expand to at least two versions. `git` chains need `git` installed.

Version files are read as Markdown: YAML front matter, HTML comments, link targets and emphasis markers are removed before comparison.

### Proposing chains automatically

```sh
ownvoice edit-delta discover --dir ~/writing [--git] [--out PATH]
```

`discover` groups Markdown files under `--dir` by the `title` in their front matter and writes a proposed chain for each title with two or more files. Files are ordered by their front-matter `date`, then by last commit time when `--git` is given, then by path. Every proposed chain has `origin = "owner"`. The default output is `work_dir/chains.proposed.toml`. Review the order and origin of each chain, then save it as your `chains.toml`. ownvoice never uses the proposal file directly.

## Editorial rules and media

The editorial rules file (`[paths].editorial_rules`) is Markdown that contains exactly one fenced block tagged `ownvoice-rules`. `scripts/install-skills.sh` installs a template: Markdown section headings plus a minimal block containing only `schema_version = 1`. The block also accepts `spelling`, `[[ban]]`, `[limits]` and `[swearing]`; `skills/editorial-rules/CONTRACT.md` describes them.

The set of media is fixed:

| Medium |
|--------|
| `email` |
| `article` |
| `blog` |
| `linkedin` |
| `doc` |
| `proposal` |

These are the values accepted by `ownvoice lint --medium`, by each ban's `media` list, and as keys of the `limits` and `swearing` tables in the rules block. `swearing` also accepts `never`.

## First run

This walkthrough assumes a single mbox export at `~/mail/sent.mbox`.

### 1. Install

ownvoice needs Python 3.12 or newer and has no Python runtime dependencies. From a checkout:

```sh
uv tool install .
# or
python -m pip install .
```

mbox and eml need nothing else. For PST, install `pff-tools` (for `pffexport`) or `pst-utils` (for `readpst`).

### 2. Write the configuration

```sh
mkdir -p ~/.config/ownvoice
cp examples/config.example.toml ~/.config/ownvoice/config.toml
cp examples/example-domain-map.toml ~/.config/ownvoice/domain-map.toml
```

Edit `config.toml`: set `[owner]`, keep one `kind = "mbox"` source pointing at your mailbox with `llm_eligible = false`, and delete the example PST source. The domain map can start with only `schema_version = 1`; you fill it in at step 5.

Check both files:

```sh
ownvoice config show
```

### 3. Install the skills and the editorial rules file

`ingest` records the hash of the editorial rules file, so create it before ingesting:

```sh
scripts/install-skills.sh --claude-dir ~/.claude/skills
# or --codex-dir DIR, or both
```

The installer copies the skills (`voice-profile-build`, `write-in-voice` and `editorial-rules`) into each directory you give, and writes the editorial rules template to `[paths].editorial_rules`. It never overwrites an existing rules file. Options:

| Option | Notes |
|--------|-------|
| `--claude-dir DIR`, `--codex-dir DIR` | Skill directories to install into. At least one is required. |
| `--rules template` | The default. Installs the commented template. |
| `--rules owner` | Installs the rules file shipped in `skills/editorial-rules/editorial-rules.md` instead. |
| `--profile-dir DIR` | Where to put `editorial-rules.md` when no configuration file exists yet. |
| `--force` | Overwrite skill directories that were not created by the installer. Review their contents first. |
| `--verbose` | Print each copy. |

The installer reads `OWNVOICE_CONFIG`, or `~/.config/ownvoice/config.toml`; it does not take `--config`. Edit the rules block in the installed file before you rely on `lint`.

### 4. Ingest

```sh
ownvoice ingest
```

This writes scrubbed records under `work_dir`, prints progress to stderr, and lists the most frequent recipient domains and X.500 organisations that the domain map did not match. The same list is saved to `work_dir/unmapped-domains.json`, along with a count of unresolved display names.

Useful options:

| Option | Notes |
|--------|-------|
| `--only LABEL[,LABEL...]` | Ingest only these sources. |
| `--reparse LABEL` | Discard this source's records and parse it again. For PST this needs the export kept by `--keep-extracted`. |
| `--restart LABEL` | Discard this source's records and state and start again, re-exporting a PST. |
| `--keep-extracted` | Keep the PST export after parsing, so a later `--reparse` is fast. Delete it with `ownvoice clean --extracted LABEL` or `ownvoice clean --all`. |
| `--source KIND:PATH --label LABEL --owner ADDRESS` | Ingest a mailbox that is not in `config.toml`. `--owner` may be repeated and is required. The source is never LLM-eligible. |

An interrupted ingest resumes from its last checkpoint when you run it again.

### 5. Extend the domain map and reparse

Add the domains and organisations from step 4 to `domain-map.toml` under `[domains]` and `[x500]`. Add `[addresses]` or `[names]` entries where a domain is too coarse. Then reparse the source:

```sh
ownvoice config show
ownvoice ingest --reparse LABEL
```

Repeat until the unmapped list contains nothing you want classified.

### 6. Find draft chains (optional)

If you keep drafts of your long-form writing, propose chains, review them, and measure your edits:

```sh
ownvoice edit-delta discover --dir ~/writing
# review work_dir/chains.proposed.toml and save it as chains.toml
ownvoice edit-delta --chains chains.toml
```

`edit-delta` writes `work_dir/profile/ownvoice/edit-delta.json` unless you give `--out`.

### 7. Decide LLM eligibility

Before profiling, decide which sources may contribute text to model input, and fill in `[llm]` if any may. See [LLM eligibility](#llm-eligibility-and-the-llm-table). Exemplar selection depends on this setting.

### 8. Profile

```sh
ownvoice profile
# with articles and edit tendencies:
ownvoice profile --articles chains.toml --edit-delta ~/.local/share/ownvoice/profile/ownvoice/edit-delta.json
```

Outputs go to `work_dir/profile/ownvoice/`: `profile-stats.json`, `stats-llm.json` and `exemplars.json`. Options:

| Option | Notes |
|--------|-------|
| `--sources LABEL[,LABEL...]` | Profile only these sources. |
| `--records PATH` | Profile a specific `records.jsonl` instead of the configured sources. |
| `--articles PATH` | A `chains.toml` whose final versions build the article register. |
| `--edit-delta PATH` | An `edit-delta.json` to include. It must match the current configuration. |
| `--out-dir DIR` | Write outputs somewhere other than `work_dir/profile/ownvoice/`. |
| `--allow-partial` | Accept a source whose ingest report is partial. |
| `--allow-stale-dump` | Accept a retained PST export older than seven days. |

### 9. Lint a draft

```sh
ownvoice lint draft.md \
  --stats ~/.local/share/ownvoice/profile/ownvoice/profile-stats.json \
  --register client --medium email
```

`--register` must be a register present in `profile-stats.json`, such as a recipient class or `article`. `--medium` is one of the media listed above. Optional: `--source LABEL` to compare against one source, `--rules PATH` to use a rules file other than `[paths].editorial_rules`, `--out PATH` for the JSON report (default `lint.json` next to the draft), and `--format json` to print JSON instead of text.

The installed `voice-profile-build` and `write-in-voice` skills build on these outputs inside your agent harness.
