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

An experiment (`test-client-sdk-or.py`) verified the routing: 10 runs, `strategy:
direct`, StreamLake (position 1 of 15, fp8) selected every time, 7 of 15 providers
available per call, cost $3µ per run.

### `max_price`

A ceiling (`{"prompt": "0.25", "completion": "1.30"}`) so a mispriced or
newly-added endpoint can never be selected at an unexpected price. If nothing
qualifies, the call errors instead of charging.

### `x_open_router_metadata="enabled"`

Returns which provider actually served the request, so routing claims can be
checked instead of assumed.

## From 47/50 to 50/50 — the prompt purification

The scorer made prompt work measurable. Each change touched **one rule at a
time**, then re-ran all 10 tickets and compared against `labels.json`:

```
47 → 49 → 50 → 48 → 49 → 50 → 50 → 50   (last three consecutive)
```

What each pass fixed:

| pass | change | result |
|---|---|---|
| 47→49 | *"even if the error is intermittent"* in P2 | `001` stopped falling to P3 |
| escalations | define escalation by **work required**, and explicitly list signals that do **not** count (customer frustration, "please escalate") | only `007` escalates; stable ever since |
| 48→49 | **guard on P3**: P3 only applies if no core flow (login, API, webhooks, money) is blocked *or malfunctioning* — kills P3 escapes structurally instead of adding examples | `003` fixed |
| 49→50 | guard was too broad (*"wrong amount"* swallowed `009`); narrowed to **duplicate charge only** — a wrong plan on an invoice is an invoice correction, not a money malfunction | `002` and `009` both correct |

The lesson: when two rules claim the same ticket, **narrow one of them to match
the distinction that already exists in the labels** — do not keep piling examples
on top of both sides (each new clause can flip a different ticket).

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
