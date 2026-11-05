# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05 (late afternoon).

**Phase:** 1 (pilot). Sub-budgets (a) and (b) done; (c) in progress (scoring v1, report, golden traces). Pilot domains clinic + banking; free routes only until funded; publish the pilot at the Phase 1 exit. The repo is public and pushed (Aya cleared the IP question on 5 Nov); commits follow Conventional Commits (history reworded on 5 Nov, `prereg-v1` re-pointed before any pilot run).

**What works:**
- `uv run pytest` (1,100 tests, 97% coverage).
- `afandem data lint <path> [--allow-drafts]`.
- `afandem run --fake | --target <route>`, then `afandem show <run_dir>` and `afandem summary <run_dir>`.
- `scripts/probe_providers.py [route]` and `scripts/export_cache.py`.
- CI: 11 jobs behind `ci-ok`, CodeQL, a release workflow whose strict data lint refuses drafts, and Dependabot (first PR merged 5 Nov). Details in [ci.md](ci.md).

**Live routes (probed 5 Nov, [providers.md](providers.md)):**
- Working: `gemini_free` (Gemini 3.5 Flash-Lite), `groq_qwen` (Qwen3.8-27B), `groq_gptoss` (gpt-oss-120b) and `ollama_cloud` (Gemma 4 31B).
- `fanar_tools`: the key works, but QCRI has not yet enabled `Fanar-2.0-Tools`; Aya has e-mailed support.
- `nvidia_deepseek`: timed out on every request.
- `cloudflare_qwen`: `.env` holds the token ID, not the token. Roll the token and paste the `cfat…` value. A narrower token with Workers AI Read only is advised.

**Data:**
- `data/clinic/clinic-0001…0010`: assistant drafts (`provenance: assistant_draft`, decision D19), with dialect wording attested in [attestations.md](attestations.md). The private copy with review IDs is in the Brain, file `09`.
- Prompt v1 in `config/prompts/`, drafted by the assistant at Aya's request.

**Running / just run:** `runs/drafts-week3-2026-11-05` covers the ten drafts × EGY + EN on four free models (the week-3 number, on drafts, so a first look rather than a result).

**Waiting on Aya:**
1. Review the ten drafts in the authoring tool, column by column ("I rewrote or approved this column" flips a column to `hand`). Decide the two convention conflicts in attestations.md: the one-hamza «أجل» versus the attested «أأجل», and the house Arabizi profile versus what real writing shows.
2. If drafted items are to count as they are, a dated pre-registration amendment is needed (the assistant can prepare it).
3. Cloudflare token (above), optional.
4. GitHub settings from [ci.md](ci.md):
   - a ruleset on `main` requiring `ci-ok`;
   - private vulnerability reporting and Dependabot security updates;
   - labels `data` and `results`.
5. Optional: a Fanar key regenerated (the old one appeared in a screenshot).

**Next for the build:**
- Finish sub-budget (c): normalisers, forms matching for `inform`, metrics, `afandem score` / `report`, golden traces, the discovering oracle.
- The remaining 20 pilot scenarios (5 clinic, 15 banking), drafted or hand-written, as Aya decides.
- The full six-column pilot run.

**Standing practice:** after every meaningful change, add an Egyptian Arabic X post with Chrome screenshots at the top of the Brain note `08 — X Thread (Egyptian Arabic).md` (images in `x-media/`).

**Open notes:**
- `tests/fixtures/scenarios/clinic/clinic-0042.json` (the spec example) and `tests/fixtures/smoke/` (placeholder texts) never go into `data/`.
- Lints not built yet: calendar, harmful-text, solvability (the discovering oracle) and the 2–5-days-ahead rule.
