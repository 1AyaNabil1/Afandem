# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05 (night).

**Phase:** 1 (pilot). Sub-budgets (a), (b) and (c) are built, and so are all the lints in the spec's table. All 30 pilot scenarios exist as **assistant drafts** (15 clinic, 15 banking), lint-clean and solvable, waiting for Aya's review. The rule-classifier κ check is met on blind assistant labels and is provisional until she reviews them (D26). Free routes only until funded; the pilot is published at the Phase 1 exit. The repo is public; commits follow Conventional Commits.

**What works:**
- `uv run pytest` (1,792 tests).
- `afandem data lint <path> [--allow-drafts]`, now with calendar (including the 2–5-days-ahead rule), harmful-text and solvability lints (D25).
- `afandem run --fake | --target <route>`, `score`, `report`, `show`, `summary`.
- Scripts:
  - `scripts/probe_providers.py` and `scripts/export_cache.py`;
  - `scripts/calibrate_rules.py sample|kappa`: the blind κ check;
  - `scripts/review_sheet.py`: a Markdown review sheet of every scenario.
- CI: 11 jobs behind `ci-ok`, CodeQL, the release workflow (strict lint refuses drafts) and Dependabot. See [ci.md](ci.md).
- Versions: prompt `fe89ad7e0f42` (D23: the banking policy block now lists the customer's own accounts and cards), scorer 1.1, normaliser 2 (adds «امبارح»/yesterday as -1 day).

**Live routes ([providers.md](providers.md)):**
- Working: `gemini_free` (Gemini 3.5 Flash-Lite), `ollama_cloud` (Gemma 4 31B), `groq_gptoss` (gpt-oss-120b) and `groq_qwen` (Qwen3.8-27B). The two Groq routes run out of their **daily token quota** after about 60 items each; the harness stops them cleanly (exit code 4, outcome `quota`).
- `fanar_tools`: waiting for QCRI to enable `Fanar-2.0-Tools`.
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
- **On 6 Nov, run everything as one fresh run** (cached calls replay free, so only the new items cost quota): `uv run --env-file .env afandem run --target gemini_free --target ollama_cloud --target groq_gptoss --target groq_qwen --scenarios data --run-id drafts-pilot-2026-11-06`. If a quota stops it, re-run the same command with `--retry-errors`. Then `afandem score` and `afandem report`.
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
7. Optional: the Cloudflare token, and a regenerated Fanar key.
8. Outreach (Brain note `10`):
   - OpenReview needs a vouch.
   - The pre-registration is on Zenodo (doi:10.5281/zenodo.23986572, D24).
   - The Hugging Face dataset `AyaNabil111/afandem` is private, with a skeleton card.

**Next for the build:**
- Run `drafts-pilot-2026-11-06` (above); score and report it as a first look, and read every failure by hand.
- Re-check κ on a **fresh** sample from that run: `scripts/calibrate_rules.py sample … --exclude runs/drafts-clinic-six-2026-11-05/calibration/key.json`, a blind labeller, then `kappa`. The two rule bugs are fixed in scorer 1.1 (D26). Arabizi choice words (`ay wa7ed`, `aw`) are still missing from the alternative markers.

**Standing practice:** after every meaningful change, add an Egyptian Arabic X post with Chrome screenshots at the top of Brain note `08 — X Thread (Egyptian Arabic).md` (images in `x-media/`).

**Open notes:**
- `tests/fixtures/scenarios/clinic/clinic-0042.json` and `tests/fixtures/smoke/` never go into `data/`.
- Pre-registration §1 says the scenarios are hand-written, and pilot items carry into v0. No pilot number is reported before amendment 1 and Aya's approval of the columns.
