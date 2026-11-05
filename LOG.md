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
