# Log

One entry per working session: date, hours, what was done, the next three steps. At each phase exit add an actual-vs-estimate line. **Rule:** if a phase (or a Phase 1 sub-budget) runs 30% over its estimate before its exit test passes, apply that phase's cut list before continuing.

| Phase | Estimate | Actual so far |
|---|---|---|
| 0 Setup | 11–17 h | see below |
| 1 Pilot | 125–170 h (a ≤ 35 · b ≤ 40 · c ≤ 45) | — |
| 2 v0 data | 105–140 h | — |
| 3 Runs, analysis, publication | 80–125 h | — |

## 2026-11-04 · design (assistant-run)
- Plan written and audited (three rounds + a consistency check); README, `docs/plan.md`, the three specifications and licences pushed.

## 2026-11-05 · Phase 0 setup (assistant-run, ~0 h of Aya's time)
- uv project on Python 3.14; all dependencies resolve; `afandem` CLI skeleton with `--version` and `run --fake`; three tests.
- CI (lint, strict types, tests, fake run, gitleaks); pre-commit (gitleaks, ruff, mypy, a forbidden-strings check).
- `.env.example`, `.gitignore`, `docs/providers.md`, `docs/decisions.md`, `docs/STATE.md`, this log.
- OpenRouter models snapshot + per-model parameter config; Fanar OpenAPI snapshot.
- `scripts/probe_providers.py` ready; not run (no keys yet).
- `docs/preregistration.md` v1 committed and tagged `prereg-v1`.
- **Next three steps (Aya):** accounts and keys (OpenRouter, two Google projects, Hugging Face token, Fanar request); run the probe script; deposit the pre-registration externally.

## 2026-11-05 · Phase 1 start (assistant-run)
- Her decisions: pilot clinic + banking; free routes only; publish the pilot; hold-out as recommended; testers and Gulf/Levantine speakers she recruits; an academic adviser approached with a research proposal.
- Free tool-calling routes researched and documented (`docs/free-pilot-models.md`); probe script rewritten for them.
- Sub-budget (a): scenario schema, loader, JSON Schema, 16 lints, `afandem data lint`; clinic and banking sandboxes; canary GUID; `docs/tools.md`. 670 tests; ruff and strict mypy clean. Committed locally, not pushed (IP-clause check pending).
- **Next three steps:** free API keys + probes; review tool descriptions; author the first 10 clinic scenarios with the authoring tool.

## 2026-11-05 · Phase 1 sub-budget (b) (assistant-run; Aya: API keys)
- Contract: internal message model and the OpenAI-compatible converter (`providers/base.py`, `providers/wire.py`).
- Providers: HTTP provider with retries, outcome mapping and per-route pacing; `config/routes.json` (free routes + paid OpenRouter); SQLite response cache, immutable shard export; probe script reads the routes.
- Run machinery: agent loop with follow-up rule v1, FakeModel oracle + overrides, scorer v0 (end state), trace writer (`--resume`, `--retry-errors`, `--budget`), runner, `afandem run | show | summary`; real routes wired with per-repeat cache salts.
- Live probes (keys from Aya): Gemini free, Groq Qwen, Ollama Cloud Gemma 4 work; Fanar model not enabled; NVIDIA timed out; Cloudflare token invalid. Groq needed an explicit user agent. End-to-end live run on Groq through the CLI OK.
- 1,084 tests; ruff and strict mypy clean. Committed locally, not pushed (IP clause pending).
- **Next three steps:** Aya writes `config/prompts/` and the first 10 clinic scenarios; week-3 number on Gemini + Qwen (EGY + EN, hand-scored); sub-budget (c) normalisers and metrics.

## 2026-11-05 · prompts, scenarios, CI/CD, outreach (assistant-run; Aya: keys, reviews, pushes)
- Prompt v1 (system + clinic/banking policy blocks) written at Aya's request; `assistant_draft` provenance added (schema, lint, authoring tool with per-column approval).
- gpt-oss-120b on Groq added and verified; Groq `tool_use_failed` mapped to a recorded malformed call (a model failure, not an exclusion).
- Ten clinic pilot scenarios drafted, dialect wording attested against ~270k public Egyptian texts (app-store reviews, an archived tweet corpus); drafts excluded from the measured set until approved.
- CI/CD: 11-job pipeline behind `ci-ok`, CodeQL, release workflow, Dependabot, repo hygiene; installed-wheel CLI bug fixed. History reworded to Conventional Commits; tag re-pointed.
- Brain: `07 — Publishing & Outreach`, `08 — X Thread (Egyptian Arabic)` with dated update posts and screenshots in `x-media/`, `09 — Attestations with review IDs (private)`.
- First real run started: ten drafts × EGY + EN on Gemini, Qwen, gpt-oss and Gemma (free).
- **Next three steps:** scoring v1 + report (in progress); Aya reviews the ten drafts; the remaining 20 pilot scenarios.
- Later the same day: scorer v1 + `score`/`report` + golden traces + discovering oracle (1,472 tests). First run on the drafts (80 items, 247 calls, $0) scored and reported in `results/drafts-week3-2026-11-05/` as a first look; X posts with report screenshots added to the Brain.

## 2026-11-05 · outreach profiles (assistant-run in Aya's Chrome)
- ORCID (0009-0006-4938-561X) filled in: biography, keywords, Egypt, links (GitHub, Afandem, LinkedIn, Hugging Face), and the Alexandria University degree under Education. At Aya's request, the mislabelled Alexandria "AI Engineer" employment entry was deleted, and Pixonal is left off research profiles ("Independent Researcher" only).
- GitHub: Hugging Face link added; the ORCID iD already shows. The bio stays "Mid-Level AI Engineer" (Aya's choice). LinkedIn is unchanged (Aya's choice).
- Not reached because they were still signed out: Hugging Face (and its forum), OpenReview, Zenodo, Kaggle, X, Bluesky, Hacker News and arXiv. Reddit is blocked by the browser extension. The profile text to reuse is in Brain note 07, "Now" checklist.
- Later: profiles updated on Hugging Face, arXiv (name changed to Aya Nabil at Aya's request; default category cs.CL), Kaggle, Hacker News and Bluesky. The sigarab.org membership form was submitted. The Cohere Labs application was filled in and left for Aya to edit and submit. Zenodo: name and affiliation set, ORCID linked, Afandem switched on (release webhook confirmed on GitHub). A mis-click briefly switched on E-Commerce_Pipeline; it was switched off, and no webhook remains. All links are in Brain note `10 — Accounts & Profiles`.
- Evening: Aya submitted the Cohere Labs application and joined the SIGARAB Google Group. OpenReview rejected the profile (no institutional e-mail, so it needs a vouch). At Aya's request it was resubmitted with the name Aya Nabil, ORCID and LinkedIn links, an Alexandria University education entry and expertise lines; it is back in the moderation queue. Adding a second e-mail (blocked at the confirmation step) and setting the preferred name are left for after activation.
- Night: GitHub release for `prereg-v1` published (18:05 UTC). Zenodo archived it as doi:10.5281/zenodo.23986572 (concept 10.5281/zenodo.23986571). The record's creator (it had GitHub's "@pixonaldata"), title and keywords were corrected on Zenodo. Added `CITATION.cff` (validated with cffconvert), a DOI badge and a Citing section in the README, and D24. Created the **private** Hugging Face dataset `AyaNabil111/afandem` with a skeleton card (metadata per dataset-spec §8, canary, section headings only, no data).
- **Next three steps:** an OpenReview vouch; Aya reviews the ten drafts; the remaining 20 pilot scenarios.

## 2026-11-05 · the 30 pilot drafts, the remaining lints, the κ check (assistant-run)
- Found and fixed a harness gap before any banking run: no tool or prompt line told the model the customer's own account ids (D23; prompt fe89ad7e0f42).
- Drafted clinic-0011…0015 (two refusals, the inform twin, an `idiom_violent` control, an out-of-scope prescription request) and, through an agent, banking-0001…0015, both attested against public Egyptian writing (≈392k texts for banking, incl. Egyptian banking-app reviews and an archived r/Egypt corpus). All 30 are `assistant_draft`, lint-clean (0 errors) and solvable by the discovering oracle.
- Merged the calendar, harmful-text and solvability lints (D25, built by an agent in a worktree; D24 was taken by the Zenodo deposit).
- κ check: `scripts/calibrate_rules.py` drew 60 replies (10 per column) from a six-column run of the first ten clinic drafts; a blind agent labelled them. Turn-1 κ 0.87 [0.76, 0.96], claims-done κ 0.96 [0.88, 1.00]; two rule bugs found (D26). Provisional until Aya reviews the labels (Brain note 13).
- Normaliser 2: «امبارح»/yesterday as -1 day. Review sheet script; Brain notes 11 (all 30 drafts), 12 (draft amendment 1), 13 (κ labels); three X posts with screenshots in note 08.
- Runs: `drafts-clinic-six-2026-11-05` (Groq stopped at its daily quota); `drafts-pilot-2026-11-05` (all 30 × 6 × 4) started.
- **Next three steps:** resume the Groq targets of the pilot run on 6 Nov and report it as a first look; Aya reviews the drafts, the κ labels and amendment 1; fix the two rule bugs and re-check κ on a fresh sample.
