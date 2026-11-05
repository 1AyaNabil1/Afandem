# Afandem (أفندم)

**Does an LLM agent still do the right thing when you talk to it the way Egyptians actually type?**

Afandem is an open benchmark for *tool-using* LLM agents in Arabic. It takes the same request — book a clinic appointment, change a phone bundle, block a card — and writes it six ways: English, Modern Standard Arabic, Egyptian Arabic, Arabizi (Arabic in Latin letters and digits: `3ayez a7gez`), and code-switched Egyptian+English in both of its real forms (Arabic script with English words, and Arabizi with English words). Every version has the same checkable outcome, so a difference in what the agent *does* — which tool it calls, with which arguments, whether it asks when it should ask and refuses when it should refuse — can be attributed to the language variety.

The name is what an Egyptian service agent says to take your request — and what you say when you did not understand.

## What it measures

- **RQ1 — the gap.** How much do task success, tool choice, argument accuracy and call validity change from MSA (and English) to Egyptian, Arabizi and code-switched Egyptian?
- **RQ2 — where it breaks.** Understanding, cultural grounding (dates like «بعد بكرة», numbers like «ألف وربع», names, money, phones), or action (wrong tool, invented arguments, acting instead of asking)?
- **RQ3 — safety parity.** Are harmful requests refused equally in every variety, and are harmless-but-alarming requests over-refused in dialect?

## How it works (planned)

- Small, deterministic tool sandboxes (clinic, telecom, banking) with a fixed clock and a stated policy, so the correct end state is known.
- Every scenario authored by hand by a native Egyptian speaker; nothing machine-translated; provenance recorded per item.
- Scoring is programmatic (end state, tool calls, arguments); an LLM judge is used only for a few text labels and never for task success.
- Paired design, pre-registered hypotheses, confidence intervals everywhere, and a run-to-run noise floor next to every consistency number.
- Full traces and a response cache are published, so every reported number can be reproduced offline.

## Status

**Phase 0 — setup (November 2026).** The design is in [`docs/plan.md`](docs/plan.md), with the [dataset](docs/dataset-spec.md), [harness](docs/harness-spec.md) and [methodology](docs/methodology.md) specifications. The hypotheses, analysis and sample-size rule are fixed in advance in [`docs/preregistration.md`](docs/preregistration.md) (tag `prereg-v1`). The code is a skeleton: no scenarios and no results yet. Next: a 30-scenario pilot on two domains.

```bash
uv sync
uv run afandem run --fake      # offline check, no keys needed
uv run pytest
```

## Licence

Code: MIT (see `LICENSE`). Human-authored data: CC BY 4.0 (see `data/LICENSE`). Model outputs (traces, cached responses) will be published separately under a model-output notice.

## Author

Aya Nabil — [GitHub](https://github.com/1AyaNabil1) · [Hugging Face](https://huggingface.co/AyaNabil111)
