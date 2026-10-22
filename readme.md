# AI Ticket Triage

A CLI that triages support tickets with an LLM. It reads a ticket (JSON), builds a
prompt (system + user), sends it to [OpenRouter](https://openrouter.ai), and prints
a JSON analysis: category, priority, language, urgency, escalation, summary,
first-response draft, and confidence.

Built to learn how prompt design, provider selection, and output validation fit
together in a real LLM application.

## How it works

```
tickets/ticket-NNN.json ──▶ build_messages() ──▶ OpenRouter ──▶ JSON on stdout
                              system + user       deepseek-v4-flash
```

1. Read `subject`, `description`, `id` and (optionally) `logs` from the ticket file.
2. Build two messages: a `system` message with the full triage rules, and a
   `user` message with the ticket content.
3. Call the model via the OpenRouter SDK with `temperature=0` and an explicit
   provider order.
4. Print the raw JSON response.

The model never sees `tickets/labels.json` — that file is the ground truth used
only by the scorer.

## Installation

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
OPENROUTER_API_KEY=sk-or-...
```

Get a key at <https://openrouter.ai/settings/keys>. The `.env` file is gitignored —
never commit it, never hardcode the key.

## Usage

```bash
python3 main.py 002        # classify ticket-002
python3 main.py            # asks for the ticket id
```

Example output:

```json
{
  "ticket_id": "ticket-002",
  "category": "billing",
  "priority": "P2",
  "language": "en",
  "is_urgent": false,
  "summary": "The customer was charged twice for the same September subscription.",
  "first_response_draft": "Thanks for reporting this. We see two charges ...",
  "escalate": false,
  "escalation_reason": "",
  "confidence": 0.95
}
```

### Scoring against ground truth

```bash
python3 score.py              # score all 10 tickets
python3 score.py 004 010      # score specific tickets
```

The scorer compares each response field against `tickets/labels.json`, prints a
pass/fail table, and saves every run under `runs/<timestamp>/` with a line appended
to `runs/history.txt`.

## Why it is configured this way

Every non-obvious setting in `main.py` was chosen for a measurable reason.

### Model: `deepseek/deepseek-v4-flash`

Selected from OpenRouter's public price table (~2,600 input / 500 output tokens
per ticket → about **$0.00025 per ticket**). The first choice was
`mistralai/mistral-small-24b`, which was serving from a single provider and started
returning 429s (provider-side rate limit). Moving to a model with many providers
fixed it. Batch endpoints (`:batch`) were discarded early: 50–75% cheaper, but
asynchronous — useless for an interactive CLI.

### `temperature=0`

Without it, the same ticket scores differently between runs. With it, most of the
variance between runs disappears. This is what makes the scoring history below
meaningful.

### `provider` order — why not `sort: "price"`

OpenRouter's `sort: "price"` sorts providers by **input** price. This workload is
~1,400 input tokens but ~500 output tokens, and output is where the cost is. Real
prices for `deepseek/deepseek-v4-flash` (verified against
`https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints`):

| provider | in $/M | out $/M | real cost per run |
|---|---|---|---|
| OpenInference | **0.012** (cheapest input) | 1.25 | $0.000642 |
| Relace | 0.03 (2nd cheapest input) | 1.28 | $0.000682 (most expensive) |
| StreamLake | 0.0749 | 0.1498 | **$0.000180** (cheapest) |
| Baidu | 0.0763 | 0.1526 | $0.000183 |
| DeepInfra | 0.09 | 0.18 | $0.000216 |
| Azure | 0.21 | 0.56 | $0.000574 |

**Relace is the 2nd cheapest in input and the most expensive per run** — output
price dominates. So `sort: "price"` would likely pick the worst provider for this
workload. Instead, `main.py` passes an explicit `order` with 15 providers, ordered
by **real cost per run**, grouped by quantization: fp8 first, then fp4, then
unknown.

An experiment (`test-client-sdk-or.py`) verified both halves. With
`sort: "price"`, 5 runs always selected OpenInference — the cheapest **input**,
fourth most expensive **per run** — confirming the sort keys on input price.
With our explicit `order`, 10 runs (`strategy: direct`) selected StreamLake
(position 1 of 15, fp8) every time, 7 of 15 providers available per call.

### `max_price`

A ceiling (`{"prompt": "0.25", "completion": "1.30"}`) so a mispriced or
newly-added endpoint can never be selected at an unexpected price. If nothing
qualifies, the call errors instead of charging.

### `x_open_router_metadata="enabled"`

Returns which provider actually served the request, so routing claims can be
checked instead of assumed.

## From 46/50 to 50/50 — the prompt purification

Tuning happened in two eras.

### Era 1 — manual scoring (before `score.py`)

The system prompt was already on its third rewrite by then (a generic first
draft, then a product-specific rewrite with concrete categories, P1 and
escalation rules), tested per-ticket by hand — those runs were never scored.
The first **full pass over all 10 tickets**, scored by hand against
`labels.json`, set the baseline:

- First full pass: **46/50** — `004` and `010` came back P2 + escalate (labels say
  P3 + false): the escalation rules were too broad.
- Rewrite escalation (define it by *work required*; a reproducible crash in one
  feature is not an outage) → affected tickets re-run → escalate fixed on both.
- Redraw the P2/P3 boundary (core flow vs single feature) → priorities fixed on
  `004`/`010`, broke `003` (re-run covered only the affected tickets, so the
  totals from this era are partial re-counts, not full passes).

In total the prompt went through **about ten revisions** across both eras — this
section lists only the milestones that moved the score.

This era uncovered the real problem: **the same prompt gave different answers
between runs**. Root cause: `temperature` was never set (the plan called for
0–0.3), so every call sampled differently. Fix: `temperature=0`.

### Era 2 — the scorer (`score.py`)

Automated: all 10 tickets, field by field against `labels.json`, every run saved
under `runs/`. The scored sequence:

```
47 → 49 → 50 → 48 → 49 → 49 → 50 → 50 → 50   (last three consecutive)
```

Even at `temperature=0`, reruns of the *identical* prompt scored 47, 47 and 49
with **different tickets failing each time** — residual variance. Suspected
cause: provider routing (each run can land on a different quantization, fp8 vs
fp4); never proven. So mid-sequence swings of ±1–2 fields may be noise rather
than the change made just before them.

What each change fixed (failures taken from the saved `runs/*/score.txt`):

| pass | change | result |
|---|---|---|
| 49→50 | *"even if the error is intermittent"* in P2 | `001` stopped falling to P3 |
| 50→48 | no rule change — pure flapping: two overlapping P2/P3 rules resolved differently | instability isolated to `002` and `003` |
| 48→49 | **guard on P3**: P3 only applies if no core flow (login, API, webhooks, money) is blocked *or malfunctioning* — kills P3 escapes structurally instead of adding examples | `003` fixed |
| 49→49 | guard too broad: *"wrong amount"* also swallowed wrong-plan invoices | `002` fixed, `009` broke |
| 49→50 | narrowed to **duplicate charge only** — a wrong plan on an invoice is an invoice correction, not a money malfunction | `002` and `009` both correct |

The lesson: when two rules claim the same ticket, **narrow one of them to match
the distinction that already exists in the labels** — do not keep piling examples
on top of both sides (each new clause can flip a different ticket).

## Example tickets

The repo ships 10 synthetic tickets (`tickets/ticket-001..010.json`) so anyone
cloning it can run `python3 score.py` immediately — no data collection needed.

Distribution:

- **Categories:** api ×2, billing ×2, integration ×1, bug ×2, account ×1,
  how_to ×1, other ×1.
- **Languages:** 8 English, 2 Spanish (`ticket-009`, `ticket-010`).
- **Urgent + escalated:** `ticket-007` is the only P1 / `escalate: true` — used to
  prove the model does *not* escalate when the customer merely asks.
- **With logs:** `ticket-001`, `ticket-003`, `ticket-007`, `ticket-010` (the rest
  omit the field; `main.py` uses `.get("logs")` so nothing breaks).
- **Ground truth:** `labels.json` has the expected classification per ticket. The
  model never sees it — the scorer compares against it.
- **Reference output:** `example-output.json` shows the structure the CLI produces.

All fixtures are 100% synthetic — never real customer or employer tickets.

## Project structure

- `main.py` — CLI + `build_messages()` (the system prompt lives here) + SDK call.
- `score.py` — runs tickets, compares against `labels.json`, saves each run.
- `tickets/ticket-001..010.json` — inputs (`logs` optional).
- `tickets/labels.json` — ground truth. The model never sees it.
- `tickets/example-output.json` — reference output structure.
- `runs/` — saved runs + `history.txt` (gitignored).
- `test-client-sdk-or.py` — provider routing experiment (not part of the app).

## Project conventions

- Code and prompts in English.
- Commit messages in English, no dates (Git adds those).
- Secrets in `.env` only — gitignored, never hardcoded.
- One prompt change per iteration, validated against `labels.json` before the next.
