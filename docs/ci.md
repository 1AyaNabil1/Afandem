# CI, security and releases

How the GitHub Actions workflows check, scan and release Afandem, what to run locally, and the
repository settings the owner turns on by hand. The workflows live in `.github/workflows/`.

| Workflow | Runs on | Purpose |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to `main`, every pull request, Mondays 05:17 UTC, manual, and called by `release.yml` | lint, types, tests, data, smoke run, security, build, pre-commit; one aggregate check `ci-ok` |
| [`codeql.yml`](../.github/workflows/codeql.yml) | push to `main`, every pull request, Wednesdays 04:23 UTC, manual | CodeQL code scanning for Python, JavaScript and the workflows |
| [`release.yml`](../.github/workflows/release.yml) | a pushed tag `v*` | the CI checks plus a release gate, then build, attest, GitHub Release, and PyPI once enabled |
| [`dependabot.yml`](../.github/dependabot.yml) | Mondays 06:00 Cairo time | grouped update pull requests for the Actions and the Python dependencies |

No workflow uses a stored secret. Jobs get the run's own short-lived `GITHUB_TOKEN`, read-only by
default, with write scopes only on the jobs that need them (table below). `HF_TOKEN` will be
needed only by a future `sync-space.yml` (the Hugging Face leaderboard Space, Phase 3); see
[Future secrets](#future-secrets).

## `ci.yml`

| Job (check name) | What it checks | Artifacts | Typical time |
|---|---|---|---|
| `lint` | `uv lock --check` (the lockfile matches `pyproject.toml`), `ruff format --check`, `ruff check` (findings appear as annotations on the diff) | | under 1 min |
| `typecheck` | `mypy` in strict mode on `src/`, `tests/`, `scripts/` (settings in `pyproject.toml`) | | about 1 min |
| `test (ubuntu-latest, py3.13)`, `test (ubuntu-latest, py3.14)`, `test (macos-latest, py3.14)` | `pytest` with branch coverage (fails under 90 %; about 97 % today), Node.js 26 set up so the authoring-tool tests run, and a step that fails if any test was skipped (an `xfail` is fine). The job summary shows the result line and the files below 100 % coverage. | `test-reports-<os>-py<ver>`: `junit.xml`, `coverage.xml`, `htmlcov/`, the pytest log | 1–2 min on Ubuntu, 2–4 min on macOS |
| `data` | the committed JSON Schema matches the pydantic models (`schema_export --check`); `afandem data lint tests/fixtures/scenarios`; `afandem data lint data --allow-drafts` once `data/` holds scenarios, with the counts in the job summary | | under 1 min |
| `smoke` | `afandem run --fake` on `tests/fixtures/smoke` (no keys, no network) into the runner's temp directory, then `afandem summary` into the job summary | `smoke-run`: the run directory (`traces.jsonl`, `index.json`, `run.json`, `tools.json`) | under 1 min |
| `security` | gitleaks secret scan (pull request commits, pushed commits, full history on the weekly run); `pip-audit` on every locked package in every dependency group (`uv export` with hashes) | gitleaks report, if it finds anything | about 1 min |
| `build` | `uv build` (sdist and wheel), `twine check --strict`, then installs the wheel in a clean environment and imports it | `dist` | under 1 min |
| `pre-commit` | `pre-commit run --all-files`: gitleaks, ruff, mypy, JSON/TOML/YAML checks, end-of-file and whitespace, large files, the forbidden-strings hook; hook environments are cached | | 1 min cached, 3–4 min on a cold cache |
| `ci-ok` | runs after all the jobs above, even when one fails, and succeeds only if every one of them succeeded | | seconds |

A full run takes about 4–5 minutes of wall time; the jobs run in parallel and the macOS test job is
usually the last to finish.

**Why `--allow-drafts`.** The first pilot scenarios carry `provenance: "assistant_draft"`.
`afandem data lint` reports that as an error on purpose ([decision D19](decisions.md)), so the
drafts can never enter the measured set unnoticed. CI lints with `--allow-drafts`, which reports
only `assistant_draft` findings as warnings (any other provenance value, and every other rule,
still fails the job), so pushes stay green while the author reviews the drafts. `release.yml` lints
again without the flag.

**Why the smoke fixtures are not linted.** `tests/fixtures/smoke/` holds placeholder texts that
fail the language lints by design. They are validated against the schema by the smoke run itself
and by `tests/test_smoke_fixtures.py`.

**Conventions shared by every workflow.**

- *Concurrency*: one run per workflow and ref. A new push to a pull request or branch cancels the
  older run; on `main` every commit keeps its own run, so every commit on `main` has a result.
  Releases are never cancelled.
- *Permissions*: `contents: read` at the top of each workflow. Wider scopes are granted per job:
  `pull-requests: read` (`security`, so gitleaks can list a pull request's commits),
  `security-events: write` (CodeQL upload), `id-token: write` and `attestations: write` (release
  provenance), `contents: write` (creating the GitHub Release), `id-token: write` (PyPI trusted
  publishing). `ci-ok` has no permissions at all. Checkouts never keep the token
  (`persist-credentials: false`).
- *Timeouts*: every job has `timeout-minutes` (5 to 30).
- *Caching*: `astral-sh/setup-uv` caches uv's package cache, keyed on `uv.lock`; the `pre-commit`
  job caches `~/.cache/pre-commit`, keyed on `.pre-commit-config.yaml`. In `release.yml` the gate
  and the build that produces the shipped files never restore a cache (the reused CI checks do,
  but nothing they build is shipped).
- *Pinning*: every action is pinned to a full commit SHA, with its version in a trailing comment;
  Dependabot proposes updates. uv is pinned in each workflow's `env.UV_VERSION`, Node.js in
  `ci.yml`'s `env.NODE_VERSION`, and the tools run through `uvx` carry exact versions
  (`pip-audit@2.10.1`, `twine@7.0.0`). The gitleaks version in `ci.yml` matches the `rev` in
  `.pre-commit-config.yaml`; change both together.

### Pinned actions

| Action | Version | Commit |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `astral-sh/setup-uv` | v10.3.3 | `68559e99cc807c1eb7e9238fd43a15bba460eec2` |
| `actions/setup-node` | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/download-artifact` | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `actions/cache` | v6.1.0 | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| `gitleaks/gitleaks-action` | v3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` |
| `github/codeql-action` (`init`, `analyze`) | v4.39.3 | `33d7b85da1a04171e211befe2c739303b9a4c066` |
| `actions/attest-build-provenance` | v4.2.2 | `4d101475d8b20a2381f78447822ac1eab6504dd8` |
| `pypa/gh-action-pypi-publish` | v1.14.3 | `7245906fb61fa33a13554f9d5fb856fe61758086` |

To check a pin by hand: `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` gives the tag's object;
for an annotated tag, follow it with `gh api repos/<owner>/<repo>/git/tags/<sha>`.

## `codeql.yml`

Three analyses, one job each: `analyze (python)` (`src/`, `tests/`, `scripts/`),
`analyze (javascript-typescript)` (the authoring tool in `tools/author/`) and `analyze (actions)`
(the workflows themselves). None needs a build (`build-mode: none`). They use the
`security-extended` query suite, and results appear under **Security → Code scanning**. This is
CodeQL's *advanced setup*: the repository's *default setup* must stay off, because GitHub rejects
uploads from a workflow while default setup is on. Each analysis takes about 2–5 minutes.

## `release.yml`

On a pushed tag `vX.Y.Z`:

1. `checks` calls `ci.yml`, so a release passes exactly the checks a pull request does.
2. `release gate`, in parallel: the tag must equal `v` + the `version` in `pyproject.toml`, and
   `afandem data lint data` runs **without** `--allow-drafts`, so any `assistant_draft` text
   blocks the release.
3. `build and attest`: `uv build` with no cache, `twine check --strict`, and a signed
   [build provenance attestation](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations)
   for the sdist and the wheel (anyone can verify it with
   `gh attestation verify <file> --repo 1AyaNabil1/Afandem`).
4. `GitHub release`: creates the release with the sdist and wheel attached and notes generated
   from the merged pull requests, grouped by label as set in `.github/release.yml`. A PEP 440
   pre-release tag (`v0.2.0rc1`, `v0.2.0b1`) is marked as a pre-release.
5. `publish to PyPI`: skipped until trusted publishing is set up (below).

Cutting a release (the owner, from a clean `main` with `ci-ok` green):

```bash
uv version 0.1.0                 # writes pyproject.toml and updates uv.lock
git commit -am "build: release 0.1.0"
git tag -a v0.1.0 -m "v0.1.0"
git push origin main v0.1.0
```

A release takes about 6–8 minutes. If it fails after the GitHub Release exists, delete the release
and the tag, fix, and tag again.

Before the first PyPI upload: the installed wheel imports, but its CLI still expects a repository
checkout. `afandem --help` and `afandem --version` fail outside one, because building the
argument parser reads `config/routes.json`.

### Turning on PyPI trusted publishing

No PyPI token is ever stored. The name `afandem` was free on PyPI on 5 November 2026.

1. On [pypi.org](https://pypi.org/manage/account/publishing/), add a **pending publisher**:
   project name `afandem`, owner `1AyaNabil1`, repository `Afandem`, workflow `release.yml`,
   environment `pypi`.
2. In the repository: **Settings → Environments → New environment** `pypi`. Optionally add
   yourself as a required reviewer and limit deployments to tags matching `v*`.
3. **Settings → Secrets and variables → Actions → Variables → New repository variable**
   `PYPI_PUBLISH` = `true`. The `publish to PyPI` job runs from the next release on. Unset the
   variable to switch it off again.

## Dependabot

Weekly, on Mondays: one grouped pull request for all GitHub Actions (`ci(deps): ...`) and one for
all minor and patch updates of Python packages (`build(deps): ...`); major updates arrive one per
pull request. A new release must be 7 days old before Dependabot proposes it. The pins from the
harness specification (§2) are respected: `pydantic` stays on its minor (its JSON Schema output
feeds the cache keys), and `openai` and `google-genai` stay on their majors.

Not covered by Dependabot, so check them now and then: `UV_VERSION` and `NODE_VERSION` in the
workflows, the `uvx` tool versions, and the hook revisions in `.pre-commit-config.yaml`
(`uv run pre-commit autoupdate`, then keep `GITLEAKS_VERSION` in `ci.yml` in step).

## Repository settings for the owner

None of these are changed by the workflows. As of 5 November 2026: no branch protection or
ruleset exists, CodeQL default setup is not configured, private vulnerability reporting is off,
Dependabot security updates are off, and secret scanning with push protection is on.

**Protect `main`** (Settings → Rules → Rulesets → New branch ruleset, target the default branch):

- *Require status checks to pass*: add **`ci-ok`** only. It already depends on every CI job,
  including each test matrix entry, so the list never needs editing when jobs change. Tick
  *Require branches to be up to date before merging*. Optionally also require
  `analyze (python)`, `analyze (javascript-typescript)` and `analyze (actions)`.
- *Require a pull request before merging*, with 0 required approvals (a single maintainer cannot
  approve their own pull requests), and *Require review from Code Owners* off for the same reason.
- *Block force pushes* and *Restrict deletions*.
- Optionally *Require linear history* and squash merging only (Settings → General → Pull
  Requests), with the pull request title (a Conventional Commit) as the commit message.
- *Bypass list*: the Repository admin role, so you can still push directly in an emergency. A
  direct push skips the required check, so prefer pull requests.

**Security** (Settings → Advanced Security, called Code security on some layouts):

- *Private vulnerability reporting*: **enable** (`SECURITY.md` points to it).
- *Dependabot alerts* and *Dependabot security updates*: **enable**.
- *Secret scanning* and *Push protection*: already on; keep them.
- *CodeQL analysis*: leave **default setup off**; `codeql.yml` is the advanced setup.

**Actions** (Settings → Actions → General):

- *Workflow permissions*: **Read repository contents and packages permissions**, and leave
  *Allow GitHub Actions to create and approve pull requests* unticked.
- *Actions permissions*: allow GitHub-owned actions, actions from verified creators, and these
  others: `astral-sh/setup-uv@*`, `gitleaks/gitleaks-action@*`, `pypa/gh-action-pypi-publish@*`.
  Tick **Require actions to be pinned to a full-length commit SHA**; every workflow already
  complies.
- *Fork pull request workflows*: require approval for first-time contributors.

**Labels** used by the issue forms and the release notes: create `data` and `results`
(`gh label create data`, `gh label create results`). Dependabot creates `dependencies` itself.

## Future secrets

`HF_TOKEN` (fine-grained, write access to the Space and the dataset only) will be the only
stored secret, used by a future `sync-space.yml` alone (harness specification §2 and §11). Store it
as an *environment* secret on a dedicated environment (for example `huggingface`), not as a
repository secret, so no other workflow can read it.

## Running the checks locally

Everything CI runs works locally (Python 3.14 and Node.js on the path):

```bash
uv lock --check
uv sync --locked
uv run ruff format --check && uv run ruff check
uv run mypy
uv run pytest --cov=afandem --cov-branch --cov-fail-under=90
uv run python -m afandem.scenarios.schema_export --check
uv run afandem data lint tests/fixtures/scenarios
uv run afandem data lint data --allow-drafts       # once data/ holds scenarios; without the flag as a release would
uv run afandem run --fake --scenarios tests/fixtures/smoke --runs-dir runs
uv build && uvx twine@7.0.0 check --strict dist/*
uv export --locked --all-groups --no-emit-project --format requirements.txt -o "${TMPDIR:-/tmp}/req.txt" \
  && uvx pip-audit@2.10.1 -r "${TMPDIR:-/tmp}/req.txt" --require-hashes --disable-pip --strict
uv run pre-commit run --all-files
```

To lint the workflows themselves, download the [actionlint](https://github.com/rhysd/actionlint)
release binary for your platform (it uses `shellcheck` when installed) and run it from the
repository root; `uvx zizmor --offline .github/workflows` audits them for security problems.
