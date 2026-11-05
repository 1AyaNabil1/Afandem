# Afandem (أفندم)

[![ci](https://github.com/1AyaNabil1/Afandem/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/1AyaNabil1/Afandem/actions/workflows/ci.yml)
[![CodeQL](https://github.com/1AyaNabil1/Afandem/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/1AyaNabil1/Afandem/actions/workflows/codeql.yml)
[![Python 3.13 | 3.14](https://img.shields.io/badge/python-3.13%20%7C%203.14-3776ab.svg)](pyproject.toml)
[![Code licence: MIT](https://img.shields.io/badge/code%20licence-MIT-blue.svg)](LICENSE)
[![Data licence: CC BY 4.0](https://img.shields.io/badge/data%20licence-CC%20BY%204.0-lightgrey.svg)](data/LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23986571.svg)](https://doi.org/10.5281/zenodo.23986571)

**Does an LLM agent still do the right thing when you talk to it the way Egyptians actually type?**

Afandem is an open benchmark for *tool-using* LLM agents in Arabic. It takes the same request — book a clinic appointment, change a phone bundle, block a card — and writes it six ways: English, Modern Standard Arabic, Egyptian Arabic, Arabizi (Arabic in Latin letters and digits: `3ayez a7gez`), and code-switched Egyptian+English in both of its real forms (Arabic script with English words, and Arabizi with English words). Every version has the same checkable outcome, so a difference in what the agent *does* — which tool it calls, with which arguments, whether it asks when it should ask and refuses when it should refuse — can be attributed to the language variety.

The name is what an Egyptian service agent says to take your request — and what you say when you did not understand.

## What it measures

- **RQ1 — the gap.** How much do task success, tool choice, argument accuracy and call validity change from MSA (and English) to Egyptian, Arabizi and code-switched Egyptian?
- **RQ2 — where it breaks.** Understanding, cultural grounding (dates like «بعد بكرة», numbers like «ألف وربع», names, money, phones), or action (wrong tool, invented arguments, acting instead of asking)?
- **RQ3 — safety parity.** Are harmful requests refused equally in every variety, and are harmless-but-alarming requests over-refused in dialect?

## How it works (planned)

- Small, deterministic tool sandboxes (clinic, telecom, banking) with a fixed clock and a stated policy, so the correct end state is known.
- Every text written, or reviewed and approved, by the native Egyptian-speaking author; nothing machine-translated; provenance recorded per column, and assistant drafts excluded from the measured set until the author approves them.
- Scoring is programmatic (end state, tool calls, arguments); an LLM judge is used only for a few text labels and never for task success.
- Paired design, pre-registered hypotheses, confidence intervals everywhere, and a run-to-run noise floor next to every consistency number.
- Full traces and a response cache are published, so every reported number can be reproduced offline.

## Status

**Phase 1 — pilot (November 2026).**

- **The harness works end to end:** deterministic clinic and banking sandboxes with a fixed clock, the agent loop, an OpenAI-compatible provider for the free routes, a response cache, full traces, programmatic scoring (end state, arguments, validity, reply language) with `afandem score`, a descriptive `afandem report`, and `afandem run | show | summary`. CI runs it against an offline fake model on every push ([`docs/ci.md`](docs/ci.md)).
- **The first pilot scenarios are assistant drafts awaiting the author's review.** Their provenance says so, `afandem data lint` reports them as errors, and none enters the measured set until the author rewrites or approves it.
- **No results yet.**

The design is in [`docs/plan.md`](docs/plan.md), with the [dataset](docs/dataset-spec.md), [harness](docs/harness-spec.md) and [methodology](docs/methodology.md) specifications. The hypotheses, analysis and sample-size rule are fixed in advance in [`docs/preregistration.md`](docs/preregistration.md) (tag `prereg-v1`, archived on Zenodo as [doi:10.5281/zenodo.23986572](https://doi.org/10.5281/zenodo.23986572)). To contribute, see [`CONTRIBUTING.md`](CONTRIBUTING.md).

```bash
uv sync
uv run afandem run --fake --scenarios tests/fixtures/smoke --runs-dir runs   # offline, no keys needed
uv run afandem summary runs/<run-id>                                         # the run id printed above
uv run afandem score runs/<run-id> --scenarios tests/fixtures/smoke           # re-score offline
uv run afandem report runs/<run-id> --scenarios tests/fixtures/smoke          # results/<run-id>/
uv run pytest
```

## Licence

Code: MIT (see `LICENSE`). Human-authored data: CC BY 4.0 (see `data/LICENSE`). Model outputs (traces, cached responses) will be published separately under a model-output notice.

## Citing

Use [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button reads it). The concept DOI [10.5281/zenodo.23986571](https://doi.org/10.5281/zenodo.23986571) covers all versions; each release has its own DOI on Zenodo.

## Author

Aya Nabil — [GitHub](https://github.com/1AyaNabil1) · [Hugging Face](https://huggingface.co/AyaNabil111) · [ORCID](https://orcid.org/0009-0006-4938-561X)
