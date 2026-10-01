# Contributing

Issues and pull requests are welcome. A few rules keep the project's main promise, that nobody's mail ends up in this repository.

## Never commit real mail

- Fixtures under `tests/fixtures/` are synthetic: reserved domains (`example.com`, `example.org`, `example.net`) and invented names only. Never paste a real message, header, name or address into a test, issue or pull request, even a scrubbed one.
- Run `scripts/install-hooks.sh` once. The pre-commit hook runs `ownvoice guard --staged`, which refuses mailbox files, generated artefacts, privately marked files and non-reserved email addresses.
- CI runs `ownvoice guard --tree .` on every pull request.

## Checks

```sh
uv run --python 3.12 --with ruff ruff check .
uv run --python 3.12 --with ruff ruff format --check .
uv run --python 3.12 python -m compileall -q ownvoice
uv run --python 3.12 --with pytest python -m pytest -q
```

Add tests with every behaviour change, next to the module they cover. Keep the package free of third-party runtime dependencies; PST reading shells out to `pffexport` or `readpst`.

## Diagnostics

Every error a command reports states the operation, the item it failed on, what it observed and expected, the underlying cause and the next step. Follow the existing `DiagnosticError` pattern in `ownvoice/errors.py`, and never put message text, names or addresses into a diagnostic.
