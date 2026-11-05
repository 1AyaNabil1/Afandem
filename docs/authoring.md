# Authoring scenarios

The authoring tool is one offline page in `tools/author/`. It walks the authoring order of
[the dataset spec](dataset-spec.md) §2, checks the file against the schema as you go, and saves
one scenario JSON. It never writes, suggests or pre-fills any text: every text field starts empty
and the placeholders only name the field.

## Open it

Double-click `tools/author/index.html`, or run `open tools/author/index.html` from the repo. No
server, no network, nothing to install. Chrome or Edge is best: their save dialog writes straight
into `data/<domain>/`. Safari and Firefox download the file instead, and you move it.

First time only: on the review step, click **Load canary.txt…** and pick `tools/author/canary.txt`
(a page opened from disk may not read the files next to it). The tool remembers the canary and
pre-fills it in every new scenario. The file holds the project canary from `src/afandem/canary.py`.

## The steps

| Step | What you enter |
|---|---|
| 1 Meta | domain, id number, behaviour, `now` (Cairo time; the weekday and the DST check are computed), speaker gender, register, `harm_type` (refuse) or `control_of` (act/inform controls), batch, changelog, cultural tags. A panel lists what the chosen behaviour requires. |
| 2 Slot table | key / type / value rows; `intent` is required. Dates show their weekday and distance from `now`. `expected_clarification` (ask items) is picked from the slot keys. |
| 3 State and expectations | tools offered, `user_identity`, `initial_state`, and `expected`: `end_state_patch`, `tool_calls`, `must_not_call`, `read_calls`, `answer_must_contain`, all as JSON with live syntax checks. |
| 4 EGY | the anchor text, plus `follow_up` (ask) or `confirm_yes` (act). |
| 5 Arabizi | from the EGY wording, which is shown for reference; optional `arabizi_variant`. |
| 6 CS | from the EGY wording; the English insertions, each with `tool_cue`. |
| 7 CS-Latin | from the Arabizi wording and the CS insertions (one click copies your CS list). |
| 8 EN | **blind** |
| 9 MSA | **blind** |
| 10 Review and save | the six columns side by side, `natural` 1–5 per column, orthographic tags per column, cultural tags, `phenomenon_realised`, the canary, the checks, save. |

Word counts are live in every column, with the length ratio to EGY (the 0.5–1.8 band) as a hint.

## Why EN and MSA are blind

Every column is an adaptation, never a translation. EN and MSA are written from the slot table, so
their wording does not copy the Egyptian one. On steps 8 and 9 the EGY, Arabizi, CS and CS-Latin
texts are not in the page at all. You see the slot table, the scenario summary (behaviour,
register, speaker, cultural tags) and the expectations. `answer_must_contain` shows its values
only, because its surface forms include the Egyptian wording. The length ratio to EGY is a number;
untick "Show the length ratio" on those steps for stricter blindness. Only the review step shows all
six texts together.

## Drafts

Every change is kept in the browser, so a closed tab loses nothing: reopen the page and the draft
comes back. **Discard draft** clears it. There is one draft at a time, so keep one tab open. A
draft is not a file; save the JSON.

## Saving

Save as `data/<domain>/<id>.json`, e.g. `data/clinic/clinic-0001.json` (Cmd+S works too). The
file is pretty-printed UTF-8 with the keys in schema order, the same text as Python's
`json.dumps(indent=2, ensure_ascii=False)`. `provenance` is always `"hand"`; the tool will not open
a file whose texts say otherwise. If the checks still list problems you can save anyway, as work in
progress.

Then run, in the repo:

```sh
uv run afandem data lint data/
```

The lint is the authority (add `--manual` for the checks done by hand); the page's hints cover only
part of it. To change a saved scenario: **Open…**, edit, **Add revision** with a changelog note,
and save over the file.

## Maintenance

`tests/test_author_tool.py` checks the tool's constants against the schema, the lints and the
sandbox tool registries. With Node installed it also round-trips the fixture scenario through the
page's model and checks that the page rejects what the schema rejects. It fails if any file in
`tools/author/` contains Arabic script or a network reference.
