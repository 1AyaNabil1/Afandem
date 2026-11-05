# Security policy

## Supported versions

Security fixes go into `main` and the latest release. Afandem is a research harness at version
0.x, so older releases are not patched.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability** (or go straight to
   [the advisory form](https://github.com/1AyaNabil1/Afandem/security/advisories/new)).
3. Describe the problem, how to reproduce it, and what an attacker could do with it.

Only the maintainer sees the report. Afandem has a single maintainer, who aims to acknowledge a
report within 7 days and to keep you informed until it is resolved. Once a fix is released, the
advisory is published with credit to you, unless you prefer not to be named.

## Scope

In scope:

- the `afandem` package and CLI (`src/afandem/`), including the providers, the response cache,
  the trace writer and the tool sandboxes;
- the offline authoring tool (`tools/author/`);
- the CI and release workflows (`.github/workflows/`), for example a way to run code with
  repository write access or to leak a token;
- a credential committed anywhere in the repository's history.

Out of scope:

- how the models under test behave on the benchmark (unsafe tool calls, failures to refuse):
  that is what Afandem measures, so please report it as a
  [results submission](https://github.com/1AyaNabil1/Afandem/issues/new?template=results-submission.yml)
  or an ordinary issue;
- vulnerabilities in third-party model providers or their APIs (report those to the provider);
- problems that need an already compromised machine or a malicious local `.env`.

## How the project protects itself

- No secret is stored in the repository. CI uses only the workflow's own short-lived
  `GITHUB_TOKEN`, with read-only permissions unless a job needs more.
- gitleaks runs in pre-commit and in CI; GitHub secret scanning and push protection are on.
- Dependencies are locked in `uv.lock`, audited in CI with pip-audit, and updated weekly by
  Dependabot; GitHub Actions are pinned to full commit SHAs.
- CodeQL scans the Python code, the authoring tool's JavaScript and the workflows.
