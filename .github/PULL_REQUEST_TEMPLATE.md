## What and why

<!-- One or two sentences. Link the issue if there is one ("Closes #12"). -->

## Kind of change

<!-- The pull request title follows Conventional Commits, for example "fix(lints): ..." -->

- [ ] `feat` new behaviour
- [ ] `fix` bug fix
- [ ] `docs` documentation only
- [ ] `test`, `refactor`, `build`, `ci` or `chore`
- [ ] scenario data (`data/`)

## Checks

- [ ] `uv run pre-commit run --all-files` passes (ruff, mypy, gitleaks, file checks).
- [ ] `uv run pytest` passes, and new behaviour has tests.
- [ ] Docs are updated where behaviour changed (`README.md`, `docs/`).
- [ ] No secrets, `.env` contents or provider keys anywhere in the diff.

## Benchmark data and prompts (skip if untouched)

- [ ] Every benchmark text was written, or reviewed and approved, by the native-speaker author,
      and each column's `provenance` says which (`hand` or `assistant_draft`).
- [ ] `uv run afandem data lint data/` was run; any remaining `assistant_draft` errors are expected
      and listed here.
- [ ] No scenario text is quoted in this description or in review comments.
- [ ] A change to `config/prompts/` or to tool descriptions is called out: it changes
      `prompt_version` and invalidates the response cache.
