# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05.

**Phase:** 1 (pilot), sub-budget (a) — sandboxes, schema, lints, authoring tool. Decisions of 5 Nov: pilot domains clinic + banking; **free routes only** until funded ([free-pilot-models.md](free-pilot-models.md)); publish the pilot at the Phase 1 exit.

**What works:** `uv run pytest` (670 tests); `uv run afandem data lint <file|dir>` (schema + 16 lints incl. the sandbox state check); clinic (7 tools) and banking (5 tools) sandboxes; `uv run python scripts/dump_tools.py` → [tools.md](tools.md); `uv run python scripts/snapshot_models.py`; `uv run --env-file .env python scripts/probe_providers.py [route]` (free routes + OpenRouter).

**Waiting on Aya:**
1. **Free accounts and keys → `.env`** (see `.env.example`): Google AI Studio key from a project *without* billing; Groq (no card); NVIDIA build (no card); optional Cloudflare. Then run the probes and commit `tests/fixtures/providers/`.
2. **Fanar:** request access at api.fanar.qa asking explicitly for `Fanar-2.0-Tools` and for the terms of use; note the date in [providers.md](providers.md).
3. **Review the tool descriptions** in [tools.md](tools.md) (edit the docstrings in `src/afandem/sandbox/clinic.py` and `banking.py`; they are what models read), and the 16 specialty values.
4. **Employment contract IP clause** — Phase 1 code is committed locally and is **not pushed** until this is checked.
5. Deposit `docs/preregistration.md` externally (OSF, or Zenodo–GitHub release of tag `prereg-v1`).
6. 2FA on GitHub, Google, Groq, NVIDIA, Hugging Face; fix Time Machine (destination failed to mount on 5 Nov).
7. Hugging Face token + private Space and dataset `afandem` (needed by the Phase 1 exit, not before).
8. Start authoring with the authoring tool (`tools/author/`, see [authoring.md](authoring.md)): the first 10 clinic scenarios, then lint them.

**Next for the build (sub-budget b, ≤ 40 h):** agent loop with the follow-up rule, one OpenAI-compatible provider (raw passthrough of assistant turns), SQLite cache, traces, `--resume`, `--budget`, per-route rate limiting; then the week-3 number: 10 clinic scenarios × EGY + EN through the loop on Gemini (free tier), scored by hand.

**Open notes:** `DOMAIN_TOOLS` in `scenarios/schema.py` is kept in sync with the sandbox registry by `tests/test_integration_tools.py`; the example scenario `tests/fixtures/scenarios/clinic/clinic-0042.json` is a test fixture copied from the spec and must never be copied into `data/`. Lints not built yet: calendar (expected dates on closed days), harmful-text, solvability (needs the agent loop), the 2–5-days-ahead rule.
