# State — resume here

*Rewrite this page at the end of every session.* Last updated: 2026-11-05.

**Phase:** 0 (setup). Repo skeleton, CI, configs and the pre-registration are done. Phase 0 exits when the items below marked **Aya** are done and the probe results are in.

**What works:** `uv sync`; `uv run afandem --version`; `uv run afandem run --fake`; `uv run pytest`; `uv run python scripts/snapshot_models.py` (no key needed).

**Waiting on Aya (Phase 0 exit):**
1. OpenRouter account: buy $20, training opt-out on, auto top-up off, account spend ceiling; key `afandem-pilot` with `limit: 10`, daily reset → `.env`.
2. Google Cloud project `afandem-free` (no billing) → Gemini key → `.env` as `GEMINI_FREE_API_KEY`; note the AI Studio rate limits in `docs/providers.md`. (`afandem-billed` with $10 prepay comes before Phase 3.)
3. Fanar access request at api.fanar.qa, asking for the terms of use; note the date in `docs/providers.md`. No reply in 3 weeks → e-mail QCRI.
4. Hugging Face: fine-grained write token for the Space and dataset; create the static Space `afandem` and the dataset repo `afandem`, both private.
5. Run `uv run --env-file .env python scripts/probe_providers.py`; commit `tests/fixtures/providers/`; record in `docs/decisions.md` whether Gemini's thought signatures survive OpenRouter.
6. Deposit `docs/preregistration.md` externally (OSF registration, or enable the Zenodo–GitHub integration and publish a release from tag `prereg-v1`).
7. Read the employment contract's IP / outside-work clause before Phase 1 code is pushed.
8. 2FA and recovery codes on GitHub, Hugging Face, OpenRouter and Google.
9. Fix backups: Time Machine is configured but its destination failed to mount on 5 Nov.
10. `pre-commit install` in the clone (once) so the hooks run on every commit.

**Next (Phase 1, sub-budget a, ≤ 35 h):** clinic and telecom sandboxes (calendar, aliases, enums, `list_doctors`) with tests; scenario JSON Schema and loader; data lints; the blind-pane authoring tool. Then the week-3 number: 10 clinic scenarios in EGY + EN through a minimal loop on Haiku, scored by hand.
