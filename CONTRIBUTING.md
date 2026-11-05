# Contributing to Afandem

Thank you for helping. Bug reports, fixes to the harness, the lints and the docs, and reports about
scenarios are all welcome. Please open an issue first for anything larger than a small fix, so we
can agree on the approach before you spend time on it.

## Benchmark texts: the one rule that is different here

Afandem measures how models handle the way Egyptians actually write, so the texts are the
instrument.

- **Every benchmark text is written, or reviewed and approved, by the project's native-speaker
  author.** That covers all six columns (English and MSA included), the follow-ups and the
  confirmations. Nothing is machine-translated.
- **Provenance is recorded per column.** `hand` means the author wrote or approved the text.
  `assistant_draft` marks text an AI assistant drafted at the author's request: it may be run, but
  `afandem data lint` reports it as an error and it stays out of the measured set until the author
  rewrites or approves it ([decision D19](docs/decisions.md)). CI lints `data/` with
  `--allow-drafts`, which turns only those findings into warnings; the release workflow lints
  without the flag, so a release never contains drafts.
- **Contributors don't add or reword scenario texts.** If a text reads unnaturally, or an expected
  outcome looks wrong, open a
  [scenario or data issue](https://github.com/1AyaNabil1/Afandem/issues/new?template=scenario-issue.yml)
  and the author makes the change herself.
- **Never paste scenario items** into issues, pull requests, review comments or chats with a model.
  Refer to them by id, column and field. This limits training-data contamination.

How scenarios are authored is described in [`docs/authoring.md`](docs/authoring.md) and the
[dataset specification](docs/dataset-spec.md).

## Set up

You need [uv](https://docs.astral.sh/uv/), Git, and [Node.js](https://nodejs.org/) (any current LTS)
for the authoring-tool tests; without Node those tests are skipped locally, while CI always runs
them. uv installs the pinned Python (3.14, from `.python-version`; 3.13 is also supported).

```bash
git clone https://github.com/1AyaNabil1/Afandem.git
cd Afandem
uv sync                          # creates .venv from uv.lock, dev tools included
uv run pre-commit install        # runs the hooks on every commit
```

No API keys are needed for development: everything below runs offline against a fake model. Real
runs read keys from `.env` (copy `.env.example`; never commit it), loaded with
`uv run --env-file .env afandem run ...`.

## Checks

CI runs these on every push and pull request (details in [`docs/ci.md`](docs/ci.md)). To run them
yourself:

```bash
uv run ruff format --check && uv run ruff check     # lint
uv run mypy                                         # strict types
uv run pytest                                       # tests (add --cov=afandem for coverage)
uv run python -m afandem.scenarios.schema_export --check
uv run afandem data lint tests/fixtures/scenarios
uv run afandem data lint data --allow-drafts        # once data/ holds scenarios
uv run afandem run --fake --scenarios tests/fixtures/smoke --runs-dir runs
uv run pre-commit run --all-files                   # every hook, including gitleaks
```

New behaviour comes with tests. Tests use placeholder texts (`<egy text>`) or quote the
specification; they never contain new benchmark texts.

## Commits and pull requests

Commit messages and pull request titles follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <summary in the imperative, lower case, no full stop>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build` (packaging and dependencies),
`ci`, `chore`. Useful scopes: `cli`, `lints`, `sandbox`, `agent`, `providers`, `scoring`,
`author`, `data`. Mark a breaking change with `!` (`feat(cli)!: ...`) and explain it in the body.
Examples: `fix(lints): count Arabic-Indic digits in follow-ups`, `ci: cache pre-commit hooks`.

Pull requests target `main`, fill in the template, and need the `ci-ok` check to pass. Keep each
pull request to one change; a change to `config/prompts/` or to a tool description gets its own
pull request, because it changes `prompt_version` and so every cache key.

## Results from other models

External results are accepted by pull request with the traces and cache shards that CI replays.
The rules will be in `CONTRIBUTING-results.md`, published with the first results; until then, use
the [results submission form](https://github.com/1AyaNabil1/Afandem/issues/new?template=results-submission.yml)
to say you plan to submit.

## Security

Please report vulnerabilities privately, as described in [`SECURITY.md`](SECURITY.md), not in an
issue.

## Licences

By contributing you agree that your contribution is released under the project's licences: MIT
for code (`LICENSE`) and CC BY 4.0 for data (`data/LICENSE`).
