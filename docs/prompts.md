# System prompt files

The system prompt and the per-domain policy blocks are **Aya's text**. The harness only loads, fills and hashes them (`src/afandem/agent/prompts.py`); no code, script or assistant writes their wording. Until the files exist, real runs refuse to start, and `afandem run --fake` uses a built-in one-line stub that is visibly marked `[OFFLINE TEST STUB - not the benchmark prompt]`.

## Where the files go

```
config/prompts/
├── system.txt            # the system prompt; must contain {policy}
├── policy_clinic.txt     # the clinic policy block, inserted at {policy}
└── policy_banking.txt    # the banking policy block (telecom later: policy_telecom.txt)
```

UTF-8 plain text. `AFANDEM_PROMPTS_DIR` points the harness at another directory (tests use it).

## How they are rendered

For each scenario: the domain's policy file is rendered first, then `system.txt` with the rendered policy at `{policy}`. Rendering is Python `str.format_map` over the fixed variable set below, so:

- a placeholder is `{name}`; a literal brace is written `{{` or `}}` (JSON examples inside a prompt need doubled braces);
- a name outside the set, a positional `{}`/`{0}`, or attribute/index access (`{date_iso.year}`) stops the run with an error naming it;
- domain variables exist only for their domain (`{daily_limit_egp}` in the clinic policy is an error).

## Variables

All values are strings in machine formats. Examples are for the spec scenario (`now` = Wednesday 4 Nov 2026, 10:00 Cairo).

| Variable | Example | Notes |
|---|---|---|
| `domain` | `clinic` | |
| `date_iso` | `2026-11-04` | Cairo local date |
| `date_dmy` | `04/11/2026` | DD/MM/YYYY |
| `time_hm` | `10:00` | 24-hour |
| `weekday` | `Wednesday` | English weekday name |
| `utc_offset` | `+02:00` | DST-correct (`+03:00` in summer) |
| `tz` | `Africa/Cairo` | |
| `datetime_iso` | `2026-11-04T10:00:00+02:00` | |
| `user_identity_json` | `{"patient_id":"p_17","phone":"+201000000017"}` | the authenticated principal, compact JSON |
| `identity_<key>` | `identity_patient_id` = `p_17`, `identity_phone` = `+201000000017` | one per `user_identity` key (banking: `identity_customer_id`, `identity_phone`) |
| `calendar_json` | `{"closed":["Fri"],"holidays":[...],"hours":[{"close":"22:00","open":"10:00"}],...}` | clinic only; the state's calendar, compact JSON |
| `closed_days` | `Fri` | clinic only; comma-joined |
| `opening_hours` | `10:00-22:00` | clinic only; comma-joined sessions |
| `holidays` | `2026-01-07,2026-01-25,...` | clinic only; comma-joined ISO dates |
| `daily_limit_egp` | `50000` | banking only; from the state's `daily_limit_piastres` |
| `own_accounts_json` | `[{"id":"acc_1","kind":"current"},{"id":"acc_2","kind":"savings"}]` | banking only; the signed-in customer's own accounts, without balances (no tool lists them) |
| `own_cards_json` | `[{"account_id":"acc_1","last4":"4821","status":"active"}]` | banking only; the customer's own cards |
| `policy` | (the rendered policy block) | `system.txt` only |

## Version

`prompt_version` is the first 12 hex digits of SHA-256 over the renderer version and every template file in the directory (`system.txt` and all `policy_*.txt`, names and bytes, sorted by name). Any byte change in any file gives a new version, recorded in `run.json` and every trace line; the response cache keys on the rendered messages, so a prompt edit also invalidates cached calls. The stub's version is `stub`.
