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

## 2026-11-05 · the remaining lints (assistant-run, worktree branch)
- `afandem data lint` gains the calendar lint (clinic only, with the 2–5-days-ahead and Ramadan rules), the harmful-text lint (forbidden-topic lexicon in `lexicons/harmful.json`; pretext and step checks on refuse items) and the solvability lint (the discovering oracle, run offline on every act, ask and inform item). Judgement calls are in D24.
- The oracle now answers `inform` items from its reads and finds banking beneficiaries by phone or name, ready for the banking scenarios. An impossible slot date (`2026-02-30`) is now a finding instead of a crash.
- The ten clinic drafts and the fixtures pass all three lints. 1,772 tests; ruff, strict mypy and pre-commit clean.
- **Next three steps:** Aya reviews D24 and the harmful word lists; the banking scenarios run through the solvability lint as they land; check "no identifiers beyond the synthetic state" on refuse items if wanted.
