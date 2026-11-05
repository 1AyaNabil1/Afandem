# Decisions

One paragraph per design decision, newest last. The full reasoning is in [plan.md](plan.md); this log records *when* and *why* something changed, so a later session can resume without re-deriving it.

**D1 — 2026-11-04 · Name.** Afandem (أفندم): what an Egyptian service agent says to take a request, and what you say when you did not understand. Free on GitHub, Hugging Face and PyPI on that date.

**D2 — 2026-11-04 · Six text columns.** English (control), MSA (reference), Egyptian, Arabizi, code-switched Egyptian in Arabic script, and code-switched Egyptian in an Arabizi matrix. Both code-switched forms are headline columns because the literature attests the Arabizi-matrix form while phone keyboards make the script-mixed form common.

**D3 — 2026-11-04 · Everything is hand-written.** No machine-drafted text in any column, including English and MSA; EN and MSA are written from the slot table without looking at the Egyptian text.

**D4 — 2026-11-04 · Programmatic scoring.** Task success is decided by end state, tool calls and arguments only. An LLM judge from a model family outside the evaluated set labels a few text properties (asked / confirmed / claimed done; refused / complied) and never decides task success; programmatic evidence always overrides it.

**D5 — 2026-11-04 · Harm needs a policy.** Each domain's system prompt names the authenticated user and what may be done for others; reads of someone else's data count as unsafe actions.

**D6 — 2026-11-04 · All v0 data public.** Publishing the cache that reproduces the headline would publish any "private" split, so v0 is fully public and reproducible; a separate private batch written later serves only as a contamination probe.

**D7 — 2026-11-04 · Power target 15 points.** One author cannot write the ~250–400 scenarios a 10-point gap needs under Holm correction across six models; v0 targets a 15-point gap with an N rule set from the pilot's discordance (floor 114 primary, cap 200 total).

**D8 — 2026-11-04 · Per-model parameters.** Claude 5.5 and GPT-6 accept no `temperature` on OpenRouter, Sonnet 5.5 reasons mandatorily, and Gemini 3.5 Flash-Lite cannot turn thinking off; parameters are derived from a dated snapshot and recorded per call, and a stability subset run three times on every model replaces the missing fixed temperature.

**D9 — 2026-11-04 · OpenRouter-only pilot.** Each provider converter costs ~8–10 hours; the pilot runs Haiku and Sonnet through OpenRouter, and Gemini goes through OpenRouter too if its thought signatures survive there.

**D10 — 2026-11-04 · Leaderboard on a Hugging Face Space.** A static Space next to the dataset, not a GitHub Pages site.

**D11 — 2026-11-05 · Phase 0 setup.** Python 3.14 with uv; all dependencies resolve (openai 3.46, google-genai 2.34, pydantic 2.14, numpy 2.5, scipy 1.18). The 5 Nov OpenRouter snapshot confirmed D8 for every grid model and all pinned providers exist; Fanar's spec confirms the `Fanar-2.0-Tools` id. Pre-registration v1 committed and tagged `prereg-v1`.

**D12 — 2026-11-05 · Pilot domains: clinic + banking.** Aya's choice: the clearest checkable outcomes, and banking carries the most natural refusals, so RQ3 is exercised from the pilot on. Telecom moves to Phase 2.

**D13 — 2026-11-05 · Free routes until funded.** No budget now. The pilot runs on Gemini 3.5 Flash-Lite (AI Studio free tier, OpenAI-compatible endpoint), Qwen3.8-27B (Groq free plan, Cloudflare overflow), DeepSeek V4.1 Flash (NVIDIA build) and Fanar-2.0-Tools when access arrives; optionally gpt-oss-20b locally. Claude and GPT have no free route (verified 5 Nov) and join when funded. All free routes are OpenAI-compatible, so Phase 1 builds one converter. Free tiers may train on prompts; only public data goes to them. If no funds exist at the Phase 3 freeze, the selection rule is relaxed by dated amendment. Details: [free-pilot-models.md](free-pilot-models.md).

**D14 — 2026-11-05 · Hold-out confirmed.** All v0 data public; a separate private batch written later is a contamination probe only (D6 stands).

**D15 — 2026-11-05 · People.** Aya can recruit native Egyptian testers (a second rater in v0) and native Gulf and Levantine speakers (v1 adapters); all are credited in the dataset card.

**D16 — 2026-11-05 · Publishing route.** An academic adviser is approached with a research proposal for methodological feedback, venue advice and an arXiv endorsement. The pilot is published at the Phase 1 exit (dev data v0.1, results table, short post).

**D17 — 2026-11-05 · Phase 1 sub-budget (a) built.** Scenario schema (pydantic, JSON Schema export), loader, 16 data lints (incl. the sandbox state check) and `afandem data lint`; clinic (7 tools) and banking (5 tools) sandboxes with clock, calendar, tri-script name lookup, principal checks and the three call levels; the project canary GUID; `docs/tools.md` (tool descriptions to be reviewed by Aya). 670 tests.
