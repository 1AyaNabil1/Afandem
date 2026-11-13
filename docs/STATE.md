# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-13 (evening).

**Phase:** 1 (pilot). Sub-budgets (a), (b) and (c) are built, and so are all the lints in the spec's table. All 30 pilot scenarios exist as **assistant drafts** (15 clinic, 15 banking), lint-clean and solvable, waiting for Aya's review. The rule-classifier κ check is met on blind assistant labels and is provisional until she reviews them (D26). Free routes only until funded; the pilot is published at the Phase 1 exit. The repo is public; commits follow Conventional Commits.

**What works:**
- `uv run pytest` (1,800 tests; the count is on branch `fix/scorer-1.2-arabizi-choice`, local only, commit `742dc08`, not yet merged or pushed).
- `afandem data lint <path> [--allow-drafts]`, now with calendar (including the 2–5-days-ahead rule), harmful-text and solvability lints (D25).
- `afandem run --fake | --target <route>`, `score`, `report`, `show`, `summary`.
- Scripts:
  - `scripts/probe_providers.py` and `scripts/export_cache.py`;
  - `scripts/calibrate_rules.py sample|kappa`: the blind κ check;
  - `scripts/review_sheet.py`: a Markdown review sheet of every scenario.
- CI: 11 jobs behind `ci-ok`, CodeQL, the release workflow (strict lint refuses drafts) and Dependabot. See [ci.md](ci.md).
- Versions: prompt `fe89ad7e0f42` (D23: the banking policy block now lists the customer's own accounts and cards), scorer 1.2 (on the branch above; D27 adds the Arabizi choice phrase `ay wa7ed`; `main` is still 1.1), normaliser 2 (adds «امبارح»/yesterday as -1 day).

**Live routes ([providers.md](providers.md)):**
- Working: `gemini_free` (Gemini 3.5 Flash-Lite; 503 "high demand" errors are retried and pass), `groq_gptoss` (gpt-oss-120b) and `groq_qwen` (Qwen3.8-27B).
- **`ollama_cloud` (Gemma 4 31B): HTTP 402 "Add usage credits or subscribe" since 13 Nov.** It is a credit or usage limit; the cause is not checked on the Ollama account page. Cached calls still replay free; new requests fail and the harness stops the route (outcome `quota`).
- The Groq routes run out of their **daily token quota** (Qwen: a rolling 200k tokens, about 54 items at ~3,600 tokens each; gpt-oss got through 160+ items on 13 Nov, its limit is not known); the harness stops them cleanly (exit code 4, outcome `quota`).
- `fanar_tools`: waiting for QCRI to enable `Fanar-2.0-Tools` (the 13 Nov probe returned HTTP 422).
- `nvidia_deepseek`: times out.
- `cloudflare_qwen`: needs the real token, not the token ID.

**Data:**
- `data/clinic/clinic-0001…0015` and `data/banking/banking-0001…0015`.
  - All columns are `assistant_draft` (D19). Every Egyptian, Arabizi and code-switched expression is attested in [attestations.md](attestations.md) and [attestations-banking.md](attestations-banking.md); the private copies with review IDs are in Brain note `09`.
  - Mix per domain is the pilot plan: act 3, inform 2, none 1, ask 2, controls 3, refuse 3, out-of-scope 1.
- Brain note `11 — Scenario Drafts for Review.md` shows all 30 with six columns each (regenerate with `scripts/review_sheet.py data --out …`).

**Runs (drafts, first looks, not results):**
- `drafts-week3-2026-11-05`: 10 clinic × EGY+EN × 4 models. Reported in `results/`.
- `drafts-clinic-six-2026-11-05`: 10 clinic × 6 columns × 4 models; 182 scored; the Groq models stopped at their quota.
  - Gemini 60/60.
  - Gemma: EN 9/10, CS-Latin 7/10.
  - gpt-oss: Arabizi 3/8 vs MSA 7/8 (partial).
- `drafts-pilot-2026-11-05`: all 30 × 6 × 4 started at night.
  - Gemma finished all 180. Gemini stopped at its daily quota at 164 (28/28 EN … 26/27 Arabizi). Groq had no quota left.
  - Banking ran clean: one Gemini Arabizi transfer made before asking which account; one Qwen English reply invented a failed beneficiary lookup without calling the tool.
  - One draft fault was found: clinic-0014 had two free slots in its «بعد الضهر» window, so a model that correctly asked "which time?" could not succeed. It is now revision 2 with one free slot in the window.
- **`drafts-pilot-2026-11-13` (started 13 Nov, 30 × 6 × 4 = 720 items; the 6 Nov run never happened).** The cache key hashes the request, not the run id, so the 5 Nov calls replay free. Command: `uv run --env-file .env afandem run --target gemini_free --target ollama_cloud --target groq_gptoss --target groq_qwen --scenarios data --run-id drafts-pilot-2026-11-13`. **It exited at 20:12 EET with code 4 (quota)**, 564 of 720 items scored-ready: Gemini 180/180 (done); Gemma 168/180 (402); gpt-oss 162/180 (daily quota); Qwen 54/180 (daily quota). Nothing is running now, so a retry is safe.
  - **Gemma:** it stopped at clinic-0014 `en` with the 402, so clinic-0014's other five columns and all six of clinic-0015 were never tried. A plain `--retry-errors` would hit clinic-0014 first and stop again. Clinic-0015 was done on 5 Nov and should replay free: run `ollama_cloud` alone on clinic-0015 with the same run id (first check that `--scenarios` accepts one file, and that a narrower run with an existing run id adds items rather than rewriting; see `plan_items`/`item_status`). Clinic-0014 revision 2's six Gemma columns need Ollama credits. Expect Gemma at 174/180 without paying.
  - **Groq:** re-run the command above with `--retry-errors` once a day. Estimate: Qwen needs about 460k more tokens (about 3 more daily windows), so the Groq routes finish around **16–17 Nov**.
  - **One writer only** (plan §5: the cache is SQLite with one writer process). Before any `--retry-errors` or the Gemma clinic-0015 run, check that `pgrep -f "afandem run"` prints nothing. The run's exit code was only in a session scratchpad log, so judge the end by that check plus the trace counts in `runs/drafts-pilot-2026-11-13/traces.jsonl`. `--retry-errors` resumes an interrupted or quota-stopped run.
  - **Do not score until the Groq routes are complete.** The traces say scorer 1.1 because the process loaded it before the 1.2 edit; `afandem score` writes 1.2 (run it from the branch, or after merging).
  - Then `afandem score` and `afandem report` (a first look, not a result).
- Calibration files for D26 are in `runs/drafts-clinic-six-2026-11-05/calibration/`.

**Waiting on Aya:**
1. **Review the 30 drafts** in the authoring tool. Open `tools/author/index.html` in Chrome, then **Open…** a file, then **I rewrote or approved this column** for each column; that flips it to `hand`.
   - Decide the convention conflicts:
     - one-hamza «أجل» vs attested «أأجل»;
     - the house Arabizi profile vs real writing;
     - «عايزة» vs the more frequent «عايزه»;
     - Arabizi `el visa` or `el fiza`.
   - Re-rate `natural` (the assistant's self-ratings are placeholders).
2. **Pre-registration amendment 1**: a draft is in Brain note `12`. Approve or edit it before any pilot number is reported.
3. **κ labels**: check the 60 labels in Brain note `13`, then re-run `scripts/calibrate_rules.py kappa`. The gate counts once you have reviewed them.
4. **Review D22, D25 and the harmful-text word lists** (`src/afandem/lints/lexicons/harmful.json`, drafted by the build agent).
5. **Banking design questions** from drafting:
   - banking-0003: a model may refuse the over-limit transfer without calling `transfer`. That keeps the state right but fails tool selection. An earlier transfer the same day would force the call.
   - Scorer v1 does not yet check that the reply states the limit on act items.
   - banking-0013 and banking-0014 are borderline refusals.
6. GitHub settings from [ci.md](ci.md):
   - a ruleset requiring `ci-ok`;
   - private vulnerability reporting;
   - Dependabot security updates;
   - labels `data` and `results`.
7. **Ollama Cloud credits (decision):** Gemma has returned a 402 since 13 Nov. The plan says $0 until funded, so paying is your call. For the pilot only clinic-0014 revision 2's six Gemma columns depend on it; every column you rewrite later needs Gemma live. Check the Ollama account page first for whether any free allowance resets.
8. Merge, or not, `fix/scorer-1.2-arabizi-choice` (local, not pushed); pushing it also gives the X post a GitHub page to screenshot.
9. Optional: the Cloudflare token, and a regenerated Fanar key.
10. Outreach (Brain note `10`):
   - OpenReview needs a vouch.
   - The pre-registration is on Zenodo (doi:10.5281/zenodo.23986572, D24).
   - The Hugging Face dataset `AyaNabil111/afandem` is private, with a skeleton card.

**Next for the build:**
- Finish `drafts-pilot-2026-11-13` (above), then merge `fix/scorer-1.2-arabizi-choice` (Aya's call), score and report it as a first look, and read every failure by hand (Phase 1, so the Phase 2 rule against reading failure analyses does not apply; draft faults go to Aya as notes, no wording edits).
- Re-check κ on a **fresh** sample from that run: `scripts/calibrate_rules.py sample … --exclude runs/drafts-clinic-six-2026-11-05/calibration/key.json`, a blind **Opus** labeller that sees replies only, then `kappa`. The two rule bugs are fixed in 1.1 (D26) and `ay wa7ed` in 1.2 (D27; `aw` was already listed).
- Phase 1 exit: about **3 Feb 2027** by the plan's hours (published v0 about 16 Jun 2027; safe date Sep 2027). It needs Aya's draft review, amendment 1 and the κ labels. If hours logged go 30% over a sub-budget, apply the cut list.

**Standing practice:** after every meaningful change, add an Egyptian Arabic X post with Chrome screenshots at the top of Brain note `08 — X Thread (Egyptian Arabic).md` (images in `x-media/`).

**Open notes:**
- **`scripts/probe_providers.py` overwrites tracked files in `tests/fixtures/providers/` every time it runs** (on 13 Nov it replaced Ollama's good 200 fixture with the 402 and added 13 untracked files). The working tree still has those changes, uncommitted. Restore the 8 tracked ones with `git checkout -- tests/fixtures/providers/` (the assistant's attempt was denied); that does not touch the 13 untracked files, which must not be swept in by `git add -A`. Keep all of them out of commits; the probe also calls the paid OpenRouter routes (about $0.0007 per run).
- `tests/fixtures/scenarios/clinic/clinic-0042.json` and `tests/fixtures/smoke/` never go into `data/`.
- Pre-registration §1 says the scenarios are hand-written, and pilot items carry into v0. No pilot number is reported before amendment 1 and Aya's approval of the columns.
