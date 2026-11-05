# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05 (evening).

**Phase:** 1 (pilot). Sub-budget (a) done; **sub-budget (b) built** (loop, provider, cache, traces, runner, CLI); sub-budget (c) partly built (FakeModel oracle and overrides, trace writer, CLI, scorer v0). Decisions of 5 Nov: pilot domains clinic + banking; free routes only until funded; publish the pilot at the Phase 1 exit.

**What works:** `uv run pytest` (1,084 tests); `uv run afandem data lint <file|dir>`; `uv run afandem run --fake --scenarios tests/fixtures/smoke --runs-dir <dir>` (54/54 oracle successes); `uv run --env-file .env afandem run --target <route> --scenarios data --columns egy,en` (real routes; needs the prompt files below); `afandem show <run_dir>` for hand scoring; `afandem summary <run_dir>`; `scripts/export_cache.py`; `scripts/probe_providers.py [route]`.

**Live routes (probed 5 Nov, [providers.md](providers.md)):** `gemini_free` (Gemini 3.5 Flash-Lite), `groq_qwen` (Qwen3.8-27B), `ollama_cloud` (Gemma 4 31B) work. `fanar_tools`: key valid, model not enabled. `nvidia_deepseek`: endpoint timed out. `cloudflare_qwen`: token invalid. A live end-to-end run through the CLI on Groq (smoke fixtures, scratch prompt stub) wrote traces and a cache.

**Waiting on Aya:**
1. **Write the system prompt and policy blocks** — `config/prompts/system.txt` (with `{policy}`), `policy_clinic.txt`, `policy_banking.txt`; variables in [prompts.md](prompts.md). Real runs refuse until they exist. This is the step that unblocks the week-3 number.
2. **Author the first 10 clinic scenarios** in the authoring tool (`tools/author/`, [authoring.md](authoring.md)), lint them, save to `data/clinic/`.
3. `.env`: rename `OLLAMA_PROBE` to **`OLLAMA_API_KEY`** (the value is an Ollama Cloud key; `OLLAMA_PROBE` is meant for a local install). Replace `CLOUDFLARE_API_TOKEN` with an API token that has the Workers AI permission (optional overflow route).
4. **Fanar:** ask QCRI to enable `Fanar-2.0-Tools` on the key (API answers 422 "Model not authorized") and for the terms of use.
5. Review the tool descriptions in [tools.md](tools.md) (docstrings in `src/afandem/sandbox/clinic.py`, `banking.py`).
6. Employment contract IP clause — Phase 1 commits stay local until checked. Pre-registration deposit (OSF or Zenodo); 2FA; Time Machine.

**Next for the build:**
- **Week-3 number** as soon as 1 and 2 exist: `afandem run --target gemini_free --target groq_qwen --scenarios data --columns egy,en`, then `afandem show` and score by hand into `LOG.md`.
- Sub-budget (c): full normalisers (digits, phones, money, times, Arabic folding), `answer_must_contain` forms, `hallucinated_action` lexicon (an xfail test marks it), validity/tool-selection/argument metrics, reply language, the rule classifier, discovering oracle (solvability), descriptive report, golden traces.
- Open engineering notes: shard export vs `--resume` under the same run id (export only at the end for now; free routes cost nothing); two identical concurrent cache misses are both sent (concurrency 1 by default); `ProviderOutcomeError` could carry `flag`/`retry_after_s` (suggested by the build agent, not done).

**Open notes:** `DOMAIN_TOOLS` in `scenarios/schema.py` is kept in sync with the sandbox registry by a test; `tests/fixtures/scenarios/clinic/clinic-0042.json` is the spec example and `tests/fixtures/smoke/` holds placeholder-text fixtures — neither is ever copied into `data/`. Lints not built yet: calendar, harmful-text, solvability, the 2–5-days-ahead rule.
