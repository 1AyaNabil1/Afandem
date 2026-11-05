# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05 (evening).

**Phase:** 1 (pilot). Sub-budgets (a), (b) and (c) built: scorer v1 (normalisers, forms matching, metrics, rule classifier), `afandem score` / `report`, golden traces and the discovering oracle (decision D22, for review). Pilot domains clinic + banking; free routes only until funded; publish the pilot at the Phase 1 exit. The repo is public and pushed (Aya cleared the IP question on 5 Nov); commits follow Conventional Commits (history reworded on 5 Nov, `prereg-v1` re-pointed before any pilot run).

**What works:**
- `uv run pytest` (1,472 tests, ~97% coverage).
- `afandem data lint <path> [--allow-drafts]`.
- `afandem run --fake | --target <route>`, then `afandem score <run_dir> --scenarios data`, `afandem report <run_dir> --scenarios data`, plus `show` and `summary`.
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

**First look (drafts, not results):** [results/drafts-week3-2026-11-05/report.md](../results/drafts-week3-2026-11-05/report.md): ten drafts × EGY + EN × Gemini, Gemma, gpt-oss and Qwen, 80/80 items `ok`, $0. Primary set EN→EGY: Gemini 9/9→9/9; the other three each lose one item. Argument accuracy drops more than tool selection (e.g. gpt-oss 94%→74%). Gemini replied in Arabic to 9 of 10 English users. Every failure was read by hand: all are model failures (one v0 scorer gap is fixed in v1).

**Waiting on Aya:**
1. Review the ten drafts in the authoring tool, column by column ("I rewrote or approved this column" flips a column to `hand`). Decide the two convention conflicts in attestations.md: the one-hamza «أجل» versus the attested «أأجل», and the house Arabizi profile versus what real writing shows.
2. If drafted items are to count as they are, a dated pre-registration amendment is needed (the assistant can prepare it).
3. Cloudflare token (above), optional.
4. GitHub settings from [ci.md](ci.md):
   - a ruleset on `main` requiring `ci-ok`;
   - private vulnerability reporting and Dependabot security updates;
   - labels `data` and `results`.
5. Optional: a Fanar key regenerated (the old one appeared in a screenshot).
6. Outreach (Brain note `10 — Accounts & Profiles` has every link). Done: SIGARAB (form and group) and the Cohere Labs application. OpenReview needs a **vouch** from someone with a confirmed institutional e-mail; the profile was resubmitted on 5 Nov. The pre-registration is on Zenodo (release of `prereg-v1`, doi:10.5281/zenodo.23986572; concept DOI 10.5281/zenodo.23986571; D24), and `CITATION.cff` is in the repo. The Hugging Face dataset `AyaNabil111/afandem` exists, **private**, holding only a skeleton card (no data).

**Next for the build:**
- Calibrate the claims-done lexicon and the turn-1 rule classifier against Aya's labels (κ ≥ 0.6 gate).
- The remaining 20 pilot scenarios (5 clinic, 15 banking), drafted or hand-written, as Aya decides.
- The full six-column pilot run.

**Standing practice:** after every meaningful change, add an Egyptian Arabic X post with Chrome screenshots at the top of the Brain note `08 — X Thread (Egyptian Arabic).md` (images in `x-media/`).

**Open notes:**
- `tests/fixtures/scenarios/clinic/clinic-0042.json` (the spec example) and `tests/fixtures/smoke/` (placeholder texts) never go into `data/`.
- Lints not built yet: calendar, harmful-text, solvability (the discovering oracle) and the 2–5-days-ahead rule.
