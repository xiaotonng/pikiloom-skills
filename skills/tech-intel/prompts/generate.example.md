{{FOCUS_DIRECTIVE}}You are given {{TOP_N}} candidate items below. Select the best and
draft content for each selected item.

## How many to produce
- Aim for about {{TARGET_TOTAL}} items total.
- At minimum: {{MIN_POST}} posts and {{MIN_QUOTE}} quotes.
- If fewer than {{HARD_MIN_TOTAL}} items clear your quality bar, produce fewer —
  never pad with weak or unrelated items.

## How to draft each item
- `post`: a standalone summary of one item. First line = who/what + what happened;
  following lines = one concrete fact each (a number, capability, limit). Put the
  main link on its own final line.
- `quote`: a one-or-two-line take that adds a single specific point on top of the
  source (the source link is implicit).
- Every fact you write MUST be traceable to the candidate's `text` / `context_text`
  / `reference_content`. Do not introduce numbers or @handles that are not there.

## Candidates
{{ITEMS_BLOCK}}

## Output
Return ONE raw JSON object as specified in the system prompt — keys `post`, `quote`,
`reply`, each a list of `{ "source_id", "text" }`. Nothing else.
