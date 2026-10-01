"""C15 diagnostic-site inventory, including schema and config boundaries.

Frozen expressions bind operation, identity and remediation at each site.
This is a static coverage inventory, not a claim of runtime fault injection.
"""

ERROR_SITES = [
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('resume profile synthesis', path, 'not a completed Stage Q run in this profile directory', 'a synthesis-* run holding A/B manifests and findings-set.json', 'run voice-profile-build without --resume-run')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('resume profile synthesis', manifest, 'run planned under different inputs: ' + ', '.join(stale), 'the current config, domain map, rules and tool digests', 'run voice-profile-build without --resume-run')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('resume profile synthesis', row['chunk_id'], 'chunk text digest changed', 'the original masked chunk', 'run voice-profile-build without --resume-run')",
    ),
    (
        "ownvoice/provenance.py",
        "DiagnosticError('validate scrub policy', label, 'recorded scrub-list digests are missing or stale', 'current sensitive_terms and deny_terms_file content digests', None, f'run ownvoice ingest --reparse {label}')",
    ),
    (
        "ownvoice/provenance.py",
        "DiagnosticError('validate artefact policy', identity, 'recorded config digest is stale', 'current file-backed input content digests', None, f'run ownvoice {command} with the current config')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('validate artefact policy', path, 'recorded edit-delta config digest is stale', 'current file-backed input content digests', 'run ownvoice edit-delta with the current config, then ownvoice profile --edit-delta')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis profiled records', directory / 'profile-stats.json', 'profiled_records SHA-256 binding is missing', 'a file and SHA-256 bound by profile', 'rerun ownvoice profile with the selected inputs before synthesis')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis profiled records', path, 'SHA-256 bound path escapes profile directory', 'a bound file inside the profile directory', 'rerun ownvoice profile with the selected inputs before synthesis')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis profiled records', path, f'SHA-256 {actual}', f'SHA-256 {binding['sha256']}', 'rerun ownvoice profile with the selected inputs before synthesis')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('bind synthesis profiled records', path, str(exc), 'a readable SHA-256 bound records file', exc, 'rerun ownvoice profile with the selected inputs before synthesis', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis edit delta', path, 'bound path escapes profile directory', 'a private artefact inside the profile directory', 'rerun ownvoice profile with --edit-delta to restore the binding')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis edit delta', path, f'SHA-256 {actual}', f'SHA-256 {binding['sha256']}', 'rerun ownvoice profile with --edit-delta to restore the binding')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('bind synthesis edit delta', path, str(exc), 'a readable bound artefact', exc, 'rerun ownvoice profile with --edit-delta to restore the bound artefact', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('merge ingest source', label, 'excluded: no completed per-source records and report', 'a complete checkpoint with records.jsonl and a complete ingest-report.json', None, f'run ingest --only {label} to complete this source')",
    ),
    (
        "ownvoice/cli.py",
        "DiagnosticError('parse command arguments', self.prog, message, 'arguments matching --help', None, f'run {self.prog} --help')",
    ),
    (
        "ownvoice/cli.py",
        "DiagnosticError('log record event', 'record_id', 'invalid identifier', '16 hex characters', None, 'pass the hashed record id, never message content')",
    ),
    (
        "ownvoice/cli.py",
        "DiagnosticError('log rule event', 'rule_id', 'invalid identifier', 'an opaque rule id', None, 'pass a rule id, never message content')",
    ),
    (
        "ownvoice/cli.py",
        "DiagnosticError('parse command arguments', 'edit-delta --chains', 'no chains supplied', '--chains PATH or discover/compare subcommand', None, 'run ownvoice edit-delta --help')",
    ),
    (
        "ownvoice/commands/clean.py",
        "chunk.problem('clean qual chunks', manifest_path, 'manifest not found', 'an existing manifest', 'supply the manifest written by qual chunk')",
    ),
    (
        "ownvoice/commands/clean.py",
        "DiagnosticError('clean extracted PST', label, 'unknown source label', 'a configured source label', None, 'use a configured label or clean --all')",
    ),
    (
        "ownvoice/commands/clean.py",
        "DiagnosticError('clean qual chunks', path, str(exc), 'a removable listed file', exc, 'restore file permissions and retry cleanup', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/commands/edit_delta.py",
        "DiagnosticError('read previous edit-delta', output, str(exc), 'valid JSON', exc, 'restore or move the previous output before retrying')",
    ),
    (
        "ownvoice/commands/edit_delta.py",
        "DiagnosticError('compare edit-delta version hashes', output, 'version hashes differ from previous output', 'unchanged version hashes', None, 'review changed chain inputs; this rerun replaces the previous output')",
    ),
    (
        "ownvoice/commands/guard.py",
        "DiagnosticError('check release boundary', 'guard --names-file', 'no names file supplied', 'a private names file for release checks', None, 'supply --names-file PATH')",
    ),
    (
        "ownvoice/commands/guard.py",
        "DiagnosticError('check publish boundary', path, f'rule {rule} violation', 'publishable content', None, 'remove the private material from this path and retry guard', exit_code=ExitCode.GUARD)",
    ),
    (
        "ownvoice/commands/guard.py",
        "DiagnosticError('read guard names', path, str(exc), 'UTF-8 names, one per line', exc, 'encode the private names file as UTF-8 and retry')",
    ),
    (
        "ownvoice/commands/lint.py",
        "DiagnosticError('parse lint statistics', args.stats, str(exc), 'valid profile JSON', exc, 'regenerate profile-stats.json with ownvoice profile')",
    ),
    (
        "ownvoice/commands/lint.py",
        "DiagnosticError('select lint ' + field, value, 'unknown ' + field, 'available: ' + ', '.join(sorted(choices)), None, 'choose an available ' + field)",
    ),
    (
        "ownvoice/commands/lint.py",
        "DiagnosticError('read lint input', path, str(exc), 'readable UTF-8 input', exc, 'correct the input path or encoding and retry lint', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('select profile sources', '--sources', 'empty or unknown source labels', 'configured source labels', None, 'use labels shown by config show')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('validate profile sources', path, 'records reference unconfigured source labels', 'configured source labels only', None, 'restore the matching config or rerun ingest')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('compute profile', path, '0 usable records', 'at least 1 high-confidence record', None, 'run ingest and inspect the source reports before retrying profile')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('read profile input', path, type(exc).__name__, 'readable UTF-8 JSONL' if lines else 'readable UTF-8 JSON', exc, 'restore the private ingest output and retry profile', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('read profile lexicon', path, str(exc), 'a readable UTF-8 term list', exc, 'correct the configured lexicon path or encoding and retry profile')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('validate profile report', label, 'source label does not match report', 'a matching source report', None, 'restore the source report or rerun ingest')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('compute profile', label, f'partial source; failed folders: {folders}', 'a complete source or --allow-partial', None, 'repair and re-ingest the named folders or pass --allow-partial')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('compute profile', label, 'source status=failed', 'complete or explicitly allowed partial source', None, 'repair the source and rerun ingest')",
    ),
    (
        "ownvoice/commands/profile.py",
        "DiagnosticError('compute profile', label, f'retained dump age={int(age)} seconds', 'at most 604800 seconds or --allow-stale-dump', None, f'run ownvoice clean --extracted {label} or pass --allow-stale-dump')",
    ),
    (
        "ownvoice/commands/qual.py",
        "chunk.problem('select qual records', args.records, 'unknown sources or duplicate record ids', 'unique records from configured sources', 'restore matching ingest records and config')",
    ),
    (
        "ownvoice/commands/qual.py",
        "chunk.problem('select qual source', label, 'source report mismatched or incomplete', 'a complete report for this source', 'complete ingest before chunking')",
    ),
    (
        "ownvoice/commands/qual.py",
        "chunk.problem('select qual articles', args.articles, 'articles_llm_eligible is not true', '[profile] articles_llm_eligible = true before article text is chunked', 'set articles_llm_eligible in the config or chunk without --articles')",
    ),
    ("ownvoice/config.py", "v.error('config', 'non-table input', 'a TOML document')"),
    (
        "ownvoice/config.py",
        "v.error('paths', 'unknown path field', 'work_dir, domain_map and editorial_rules only')",
    ),
    ("ownvoice/config.py", "v.error('domain-map', 'non-table input', 'a TOML document')"),
    (
        "ownvoice/config.py",
        "DiagnosticError('validate config', f'{self.path} {identity_key or key} line {line}', observed, expected, cause, f'fix {identity_key or key} at line {line} and retry config show', exit_code=exit_code)",
    ),
    ("ownvoice/config.py", "self.error(key, 'missing or invalid value', expected)"),
    (
        "ownvoice/config.py",
        "v.error('llm', 'incomplete [llm]: ' + ', '.join(missing), 'provider, retention_terms, training_use and a dated attestation when llm_eligible = true')",
    ),
    (
        "ownvoice/config.py",
        "self.error(key, 'timezone not found', 'an IANA timezone key, e.g. America/Edmonton', exc, exit_code=ExitCode.OPERATOR if available_timezones() else ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/config.py",
        "v.error(f'{section}.{key}', 'unknown recipient class', 'a class listed in classes', identity_key=identity)",
    ),
    (
        "ownvoice/config.py",
        "v.error(f'{section}.{key}', 'empty or case-insensitive duplicate key', 'a nonempty unique key', identity_key=identity)",
    ),
    (
        "ownvoice/config.py",
        "DiagnosticError('load TOML', path, str(exc), 'a readable UTF-8 TOML document', exc, 'correct the file and retry config show')",
    ),
    (
        "ownvoice/config.py",
        "v.error('ingest.extra_attribution_patterns', f'regex {index} does not compile', 'valid regular expressions', exc)",
    ),
    (
        "ownvoice/delta/discover.py",
        "DiagnosticError('discover article chains', root, 'directory does not exist', 'a readable directory', None, 'correct --dir and retry', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/delta/normalize.py",
        "DiagnosticError('read article version', path, str(exc), 'readable UTF-8 text', exc, 'restore the version file and retry', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/delta/normalize.py",
        "DiagnosticError('read git chain', identity, getattr(exc, 'stderr', None) or str(exc), 'git installed and a readable repository/path history', exc, 'install git or correct the chain repo/path and retry', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/delta/normalize.py",
        "DiagnosticError('expand article chain', chain['id'], f'{len(texts)} versions', 'at least two versions', None, 'add version history or correct the chain path')",
    ),
    (
        "ownvoice/errors.py",
        "DiagnosticError(f'internal error (this is a bug): {operation}', identity, f'{type(cause).__name__}: {cause}', 'successful command execution', cause, 'please report with --verbose output', exit_code=ExitCode.INTERNAL)",
    ),
    (
        "ownvoice/errors.py",
        "DiagnosticError('run command', command, 'not implemented yet', 'an implemented command', None, 'install a version implementing this command', exit_code=ExitCode.INTERNAL)",
    ),
    (
        "ownvoice/extract/scrub.py",
        "DiagnosticError('read scrub lexicon', path, str(exc), 'a readable UTF-8 term list', exc, 'correct the configured lexicon path or encoding and retry ingest')",
    ),
    (
        "ownvoice/guard/__init__.py",
        "DiagnosticError('select guard tree', root, 'directory does not exist', 'an existing directory', None, 'supply --tree with an existing directory')",
    ),
    (
        "ownvoice/guard/__init__.py",
        "DiagnosticError('read git publish boundary', root, detail, 'successful git ' + arguments[0], exc, 'check the repository and index, then retry guard', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/guard/__init__.py",
        "DiagnosticError('read guard input', path, str(exc), 'a readable file', exc, 'check the path and permissions, then retry guard', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/guard/__init__.py",
        "DiagnosticError('install pre-commit hook', hook.resolve(), 'an existing different hook', 'no hook or the identical ownvoice hook', None, 'integrate the existing hook explicitly before installing')",
    ),
    (
        "ownvoice/guard/__init__.py",
        "DiagnosticError('install pre-commit hook', root, str(exc), 'a writable git hooks directory', exc, 'check repository permissions and retry the installer', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/checkpoint.py",
        "DiagnosticError('read ingest state', path, type(exc).__name__, 'readable valid JSON', exc, 'restore the private state or use ingest --restart LABEL', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/checkpoint.py",
        "DiagnosticError('read ingest prefix', path, type(exc).__name__, 'the committed JSONL prefix', exc, 'restore the private source output or use ingest --restart LABEL', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/checkpoint.py",
        "DiagnosticError('flush ingest prefix', self.outputs['checkpoint'], str(exc), 'durable records and rejects before checkpoint', exc, 'check disk space and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/checkpoint.py",
        "DiagnosticError('reset ingest source', path, str(exc), 'removable source parse state', exc, 'check source output permissions and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "DiagnosticError('preflight ingest', identity, observed, expected, cause, 'correct the source or work_dir in config.toml and retry ingest')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(work, 'work_dir is inside a git working tree', 'work_dir outside git')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(work, 'destination is not writable', 'a writable directory')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(work, f'{shutil.disk_usage(ancestor).free} bytes free', f'at least {int(1.5 * pst_bytes)} bytes (1.5 times selected PST sizes)')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--source', 'invalid KIND:PATH', 'mbox:PATH or eml:PATH')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--label', 'missing or invalid label', LABEL_PATTERN)",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--owner', 'no owner supplied', 'at least one --owner address')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--source', 'label or owner without source', 'the complete ad hoc form')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--only', 'unknown source label', 'configured source labels')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--' + flag + ' ' + label, 'unknown or unselected source label', 'a configured source label included in --only')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, 'source is inside a git working tree', 'source outside git or allow_inside_git_tree = true')",
    ),
    ("ownvoice/ingest/preflight.py", "problem(identity, 'OST unsupported', 'PST, mbox or eml')"),
    (
        "ownvoice/ingest/preflight.py",
        "problem('--label', 'duplicate source label', 'a unique label')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, str(exc), 'an executable PST reader', exc)",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, 'source is unreadable', 'a readable source')",
    ),
    ("ownvoice/ingest/preflight.py", "problem(identity, 'no .eml files', 'a nonempty eml source')"),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, str(exc), 'an existing readable source', exc)",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "DiagnosticError('ingest', identity, f'{reader} not found on PATH (reader = \"{reader}\" for {path})', 'an installed executable on PATH', None, f'Install {package} (Debian/Ubuntu: apt install {package}), set reader = \"{other}\", or export the mailbox to mbox', exit_code=ExitCode.DEPENDENCY)",
    ),
    ("ownvoice/ingest/preflight.py", "problem(identity, 'source is 0 bytes', 'size > 0 bytes')"),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, 'eml target is inside git', 'all source files outside git')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, 'source file is unreadable', 'readable source files')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "problem(identity, 'content does not match kind', f'{kind} content magic')",
    ),
    (
        "ownvoice/ingest/preflight.py",
        "DiagnosticError('inspect PST reader version', identity, f'{reader} -V exited {result.returncode}: {result.stderr}', 'exit 0', subprocess.CalledProcessError(result.returncode, [reader, '-V']), f'reinstall {package} and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    ("ownvoice/ingest/preflight.py", "problem(identity, 'source is 0 bytes', 'size > 0 bytes')"),
    (
        "ownvoice/ingest/preflight.py",
        "DiagnosticError('inspect PST reader version', identity, f'{reader} {source['_reader_version']}', expected, None, 'validate this version against the real-PST fixtures before relying on it')",
    ),
    (
        "ownvoice/ingest/pst.py",
        "DiagnosticError('ingest PST', source['label'], observed, expected, cause, 'Check the file is a PST (not an OST renamed to .pst) and readable; run with --verbose for the full command line', exit_code=ExitCode.OPERATOR if operator else ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "DiagnosticError('delete PST export', path, 'symlink or git working tree target', 'an owned private extract directory', None, 'correct work_dir and inspect the target before retrying')",
    ),
    (
        "ownvoice/ingest/pst.py",
        "DiagnosticError('reparse PST', source['label'], 'no matching retained export', 'extract/.done with the current fingerprint', None, f'--restart {source['label']} re-exports the PST')",
    ),
    (
        "ownvoice/ingest/pst.py",
        "problem(self.source, f'read {identifier}: {type(exc).__name__}', 'a readable selected folder', type(exc).__name__)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "problem(source, f'{reader} on {source['path']} exited {process.returncode}, stderr {stderr.decode(errors='replace')!r} ({reader} {source['_reader_version']})', 'exit 0', cause)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "problem(source, f'execute {reader} on {source['path']}: {exc}', 'exit 0', exc)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "problem(source, 'no folder matched sent_folders', 'at least one matching folder; check sent_folders in config.toml', operator=True)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "DiagnosticError('delete PST export', path, str(exc), 'a removable directory', exc, 'restore directory permissions and retry clean', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/pst.py",
        "problem(source, 'cannot read extract/.done', 'a valid private stamp', exc)",
    ),
    (
        "ownvoice/ingest/report.py",
        "DiagnosticError('assess ingest confidence', label, f'low-confidence share exceeds 10%; top rules: {top}', 'at most 10%', None, 'inspect the private records and configure attribution patterns')",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('parse message', f'{label}/{locator}', reason, 'a decodable owner-sent mail body', safe_cause, 'inspect the source privately and retry ingest with --verbose')",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('read ingest source', source['label'], str(exc), 'readable source files', exc, 'restore source access and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('collect correspondent names', source['label'], str(exc), 'readable source headers', exc, 'restore source access and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('fingerprint ingest source', label, str(exc), 'readable source metadata', exc, 'restore source access and retry ingest', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/ingest/run.py",
        "DiagnosticError('ingest', source['label'], f'no owner-sent messages in {source['path']} ({selected} of {source_report['messages_seen']} messages matched owner_addresses or sent_folders)', 'at least 1', None, 'Check the file copied completely and the addresses/folders in config.toml')",
    ),
    (
        "ownvoice/ingest/run.py",
        "pst.problem(source, f'{len(paths.errors)} unreadable selected folders', 'all selected folders readable')",
    ),
    (
        "ownvoice/io.py",
        "DiagnosticError('write private artefact', path, 'path is inside a git working tree', 'a destination outside git working trees', None, 'choose a private output directory outside the repository')",
    ),
    (
        "ownvoice/io.py",
        "DiagnosticError('write private artefact', path, str(exc), 'an atomically written 0600 file in a 0700 directory', exc, 'check the destination permissions and serializable input', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/io.py",
        "DiagnosticError('inspect private marker', path, str(exc), 'a readable file', exc, 'check the file exists and is readable', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/layout.py",
        "DiagnosticError('resolve source layout', 'source.label', 'invalid source label', LABEL_PATTERN, None, 'correct source.label in config.toml')",
    ),
    (
        "ownvoice/provenance.py",
        "DiagnosticError('hash provenance file', path, str(exc), 'a readable file', exc, 'check the configured file path and permissions', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/chunk.py",
        "DiagnosticError(operation, identity, observed, expected, cause, next_step)",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('build qual chunks', out, 'pass or budget outside limits', 'pass A|B, positive sample words and 1..10000 max tokens', 'correct --pass, --sample-words and --max-tokens')",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('build qual chunks', out, 'sample group exceeds token ceiling', f'every chunk <= {max_tokens} estimated tokens', 'lower --sample-words or qual_max_record_words, or raise --max-tokens up to 10000')",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('record qual attempt', chunk_id, 'unknown, complete or exhausted chunk', 'an unfinished chunk within its retry budget', 'inspect qual status and retry only eligible chunks')",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('load qual manifest', path, 'duplicate chunks or inconsistent pass', 'unique chunks in the declared pass', 'regenerate the manifest with qual chunk')",
    ),
    (
        "ownvoice/qual/chunk.py",
        "DiagnosticError('read qual input', path, type(exc).__name__, 'readable UTF-8 text', exc, 'restore the private input path and permissions', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('parse qual input', path, str(exc), 'valid JSONL' if lines else 'valid JSON', 'repair the input JSON syntax', exc)",
    ),
    (
        "ownvoice/qual/chunk.py",
        "problem('resolve qual manifest target', path, 'target escapes its private file directory', 'regular files directly under chunks/ or raw/ beside the manifest', 'regenerate the manifest before reading or cleaning chunks')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('run profile helper', arguments[0], f'exit {status}', 'exit 0', output.getvalue(), 'repair the helper input before rebuilding the profile', exit_code=ExitCode(status))",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('budget synthesis input', 'Stage S', f'estimated {estimated_total:,} tokens', f'at most {ceiling:,} estimated tokens', 'reduce exemplars or qualitative sample size before rebuilding')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('dispatch qual chunk', row['chunk_id'], 'text digest changed', 'the original masked chunk', 'regenerate the manifest and chunks')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('preflight profile synthesis', names, 'names.txt is missing', 'an existing names.txt', 'run ingest to create the private names list before building a profile')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('preflight profile synthesis', directory, 'profile dir is inside a git working tree', 'a private profile directory outside git', 'choose an external --profile-dir')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis inputs', directory / filename, 'input provenance is stale', 'current config, domain map, rules and tool digests', 'rerun ownvoice profile with the current config before synthesis')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('parse synthesis response', 'Stage S', 'response violates section contract', 'JSON sections 1, 2 (every register), 3, 5 with nonempty Markdown and no H1/H2', 'correct the model response contract and regenerate', exc)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('archive voice profile', path, 'previous profile lacks marker or generation date', 'a generated private voice profile', 'move the unrecognized file aside privately')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('archive voice profile', historical, 'timestamp already has different content', 'an immutable historical profile', 'inspect the conflicting private history')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('validate profile synthesis', 'Stage S', f'draft rejected after {attempts} attempts; spans in {diagnostic}', 'a grounded, names-free draft matching the section contract', 'inspect the private diagnostic and regenerate the profile')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('call profile model', adapter, f'exit {result.returncode}; stderr: {result.stderr}', 'exit 0', 'check the harness authentication and restrictive-mode support', cause)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('call profile model', adapter, f'call did not complete; details in {diagnostic}', 'exit 0 and a final text response', None, 'inspect the private diagnostic and repair the harness before retrying', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('build voice profile', exc.filename or 'private profile directory', str(exc), 'readable inputs and writable private output', exc, 'check the named path and permissions, then retry with --verbose', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('select synthesis exemplar', item['record_id'], 'source is not eligible', 'an eligible source', 'rerun ownvoice profile before synthesis')",
    ),
    (
        "ownvoice/qual/ground.py",
        "chunk.problem('ground qual findings', '--threshold', 'threshold outside limits', 'a finite ratio greater than 0 and at most 1', 'correct --threshold')",
    ),
    (
        "ownvoice/qual/ground.py",
        "chunk.problem('ground qual chunk', path, 'marker, digest or record spans do not match', 'the original marked chunk with its recorded digest and spans', 'regenerate chunks and rerun the pass')",
    ),
    (
        "ownvoice/qual/ground.py",
        "chunk.problem('ground qual chunk', path, 'record span map inconsistent with chunk', 'one valid text span per listed record', 'regenerate chunks and rerun the pass')",
    ),
    (
        "ownvoice/qual/merge.py",
        "chunk.problem('merge qual findings', existing_path, 'existing set changed or pass out of order', 'the reconciled set, A then B only', 'rerun reconcile against the current set or stop after B')",
    ),
    (
        "ownvoice/qual/merge.py",
        "chunk.problem('merge qual finding', add, 'referenced finding absent', 'an existing finding id', 'regenerate the reconciliation diff')",
    ),
    (
        "ownvoice/qual/reconcile.py",
        "chunk.problem('reconcile qual findings', candidate, 'grounded digest mismatch or pending chunks', 'unchanged grounded findings from a finished pass', 'finish dispatch and rerun qual ground')",
    ),
    (
        "ownvoice/qual/reconcile.py",
        "chunk.problem('reconcile qual pass', candidate, 'pass is repeated or out of order', 'A then B, stopping after B', 'use the findings set preceding this pass')",
    ),
    (
        "ownvoice/qual/reconcile.py",
        "chunk.problem('reconcile qual findings', candidate, 'kept count differs from report', 'the complete grounded output', 'rerun qual ground')",
    ),
    (
        "ownvoice/qual/synthesis_check.py",
        "problem('check profile synthesis', 'draft.md', f'guard exit={status}; offending names={offending_names!r}; absent quotes={absent!r}', 'guard exit 0, no names and every quote in masked source text', 'correct the listed spans and regenerate the profile', output.getvalue() or None)",
    ),
    (
        "ownvoice/schemas/ac14.py",
        "c.constraint(errors, 'ac14.brief', bool(value['brief']), 'at least one brief')",
    ),
    (
        "ownvoice/schemas/ac14.py",
        "c.constraint(errors, f'ac14.brief[{index}].id', brief['id'] not in ids, 'a unique brief id')",
    ),
    (
        "ownvoice/schemas/ac14.py",
        "c.constraint(errors, f'ac14.brief[{index}].{key}', bool(item.strip()), 'a nonempty string')",
    ),
    (
        "ownvoice/schemas/chains.py",
        "c.constraint(errors, 'chains.chain', bool(value['chain']), 'at least one chain')",
    ),
    (
        "ownvoice/schemas/chains.py",
        "c.constraint(errors, field + '.id', bool(chain['id'].strip()) and chain['id'] not in ids, 'a nonempty unique id')",
    ),
    (
        "ownvoice/schemas/chains.py",
        "c.constraint(errors, field + '.versions', ('versions' in chain) != ('git' in chain), 'exactly one of versions or git')",
    ),
    (
        "ownvoice/schemas/chains.py",
        "c.constraint(errors, field + '.versions', len(chain['versions']) >= 2 and all((x.strip() for x in chain['versions'])), 'at least two nonempty version paths, oldest first')",
    ),
    (
        "ownvoice/schemas/chains.py",
        "c.constraint(errors, field + '.git.' + key, bool(chain['git'][key].strip()), 'a nonempty path')",
    ),
    ("ownvoice/schemas/common.py", "fail(' or '.join((t.__name__ for t in types)))"),
    (
        "ownvoice/schemas/common.py",
        "DiagnosticError('validate artefact', field, observed, expected, None, f'correct field {field} using its version-one schema')",
    ),
    ("ownvoice/schemas/common.py", "fail('an object')"),
    (
        "ownvoice/schemas/common.py",
        "fail('only schema-defined fields', 'unknown field at object boundary')",
    ),
    (
        "ownvoice/schemas/common.py",
        "DiagnosticError('validate artefact', field, 'constraint not satisfied', expected, None, f'correct field {field}')",
    ),
    ("ownvoice/schemas/common.py", "fail('one of ' + repr(detail))"),
    (
        "ownvoice/schemas/common.py",
        "DiagnosticError('validate artefact', f'{field}.{key}', 'field is missing', 'a required field', None, f'supply field {key}')",
    ),
    ("ownvoice/schemas/common.py", "fail('an array' if kind == 'array' else 'an object')"),
    (
        "ownvoice/schemas/common.py",
        "fail(f'{expected_type} in {minimum}..{(maximum if maximum is not None else 'unbounded')}')",
    ),
    ("ownvoice/schemas/common.py", "fail(detail)"),
    (
        "ownvoice/schemas/common.py",
        "fail('a known recipient class, article or _global', 'unknown register key')",
    ),
    ("ownvoice/schemas/common.py", "fail(f'an array of {len(detail)} items')"),
    ("ownvoice/schemas/common.py", "fail('UTC ISO-8601 timestamp')"),
    ("ownvoice/schemas/common.py", "fail('UTC ISO-8601 timestamp')"),
    (
        "ownvoice/schemas/edit_delta.py",
        "c.constraint(errors, 'edit-delta.examples', len(value['examples']) <= 20, 'at most 20 examples')",
    ),
    (
        "ownvoice/schemas/edit_delta.py",
        "c.constraint(errors, f'edit-delta.examples[{index}].{key}', len(example[key].split()) <= 60, 'at most 60 words')",
    ),
    (
        "ownvoice/schemas/finding.py",
        "c.constraint(errors, 'finding.verbatim_quote', len(value['verbatim_quote'].split()) <= 25, 'at most 25 words')",
    ),
    (
        "ownvoice/schemas/ingest_report.py",
        "c.constraint(errors, 'ingest-report.messages_seen', value['messages_seen'] == value['records_written'] + sum(value['rejected_by_reason'].values()), 'messages_seen == records_written + rejected counts')",
    ),
    (
        "ownvoice/schemas/ingest_report.py",
        "c.constraint(errors, 'ingest-report.recipient_resolution.recipients', resolution['recipients'] == sum((resolution[key] for key in c.STAGES)), 'recipients == smtp + x500 + names + unknown')",
    ),
    (
        "ownvoice/schemas/ingest_report.py",
        "c.constraint(errors, 'ingest-report.merged_records', value['merged_records'] == sum(value['sources'].values()) - value['cross_source_duplicates'], 'merged_records == sum source records - cross_source_duplicates')",
    ),
    (
        "ownvoice/schemas/names.py",
        "c.constraint(errors, 'names.marker', value.startswith(PRIVATE_LINE + '\\n'), 'the private marker on the first line')",
    ),
    (
        "ownvoice/schemas/names.py",
        "c.constraint(errors, 'names.lines', value.endswith('\\n'), 'newline-terminated names')",
    ),
    (
        "ownvoice/schemas/unmapped_domains.py",
        "c.constraint(errors, f'unmapped-domains.x500_orgs[{index}].org', '/' not in row['org'], 'the org component only, without an X.500 distinguished name')",
    ),
    (
        "ownvoice/schemas/unmapped_domains.py",
        "c.constraint(errors, f'unmapped-domains.{key}', len(value[key]) <= 50, 'at most 50 entries')",
    ),
    (
        "ownvoice/style/budget.py",
        "DiagnosticError('profile: token budget exceeded', 'stats-llm.json + exemplars.json', f'estimated {tokens:,} tokens, budget {budget:,} ([profile].token_budget). Reduced exemplars to the minimum {minimum} per register ({removed} items removed); still over by {tokens - budget:,}', f'at most {budget:,} estimated tokens', None, 'lower exemplar_words_per_register or raise token_budget')",
    ),
    (
        "ownvoice/style/exemplars.py",
        "DiagnosticError('allocate exemplar quota', '[profile].exemplars_min/exemplars_max', f'required floors total {sum(quotas)}, quota {total}', 'a quota large enough for every stratum and source floor', None, 'raise exemplars_min and exemplars_max to accommodate the source floors')",
    ),
    (
        "ownvoice/style/rules_block.py",
        "DiagnosticError('read editorial rules', path, str(exc), 'readable UTF-8 Markdown', exc, 'correct the rules path or encoding and retry lint')",
    ),
    (
        "ownvoice/style/rules_block.py",
        "DiagnosticError('validate editorial rules', f'{identity}:{field}', 'missing or invalid value', expected, cause, 'correct the ownvoice-rules machine block and retry lint')",
    ),
    (
        "ownvoice/style/tokenize.py",
        "DiagnosticError('read bundled style lexicon', path, str(exc), 'a readable UTF-8 term list', exc, 'restore the package data and retry the command')",
    ),
]

# DD29 article binding, planning and Core voice boundaries.
ERROR_SITES += [
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis profiled articles', path, 'bound path escapes profile directory', 'a bound file inside the profile directory', 'rerun ownvoice profile --articles with the selected chains')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('bind synthesis profiled articles', path, f'SHA-256 {actual}', f'SHA-256 {binding['sha256']}', 'rerun ownvoice profile --articles with the selected chains')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('validate core voice', ', '.join(sorted(set(invalid))), 'response contains an empty core_voice list' if value == [] else 'response contains ungrounded or invalid patterns, or structural Markdown quotes', 'at least one pattern, each with 2-3 exact group quotes from at least two registers and no Markdown block boundaries in quotes', 'regenerate Stage S using only the named cross-register groups')",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "DiagnosticError('bind synthesis profiled articles', path, str(exc), 'a readable SHA-256 bound articles file', exc, 'rerun ownvoice profile --articles with the selected chains', exit_code=ExitCode.DEPENDENCY)",
    ),
    (
        "ownvoice/qual/dispatch.py",
        "chunk.problem('plan qualitative calls', run, f'planned calls {planned_calls} at email sample {email_sample_words} words', f'at most {call_cap} calls', 'reduce the article input or revise the qualitative sample before rebuilding')",
    ),
]
