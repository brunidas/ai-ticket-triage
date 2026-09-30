"""Score main.py outputs against tickets/labels.json.

Usage:
    python3 score.py            # all 10 tickets
    python3 score.py 004 010    # only some tickets

Each ticket costs one API call (~$0.00025). No retries: if a call fails,
the ticket is scored as failed and the error is reported.

Every run is saved under runs/<timestamp>/:
    ticket-NNN.json   model response (pretty JSON)
    score.txt         score table + totals + failures
Plus one summary line per run appended to runs/history.txt.
"""

import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LABELS = os.path.join(HERE, "tickets", "labels.json")
MAIN = os.path.join(HERE, "main.py")
RUNS = os.path.join(HERE, "runs")

FIELDS = ["category", "priority", "language", "is_urgent", "escalate"]


def parse_json(text):
    """The model may wrap the object in code fences; take from first { to last }."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in the output")
    return json.loads(text[start:end + 1])


def run_ticket(number):
    return subprocess.run(
        [sys.executable, MAIN, number],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=HERE,
    )


def main():
    with open(LABELS, encoding="utf-8") as f:
        labels = json.load(f)

    if len(sys.argv) > 1:
        tickets = []
        for arg in sys.argv[1:]:
            tickets.append(arg if arg.startswith("ticket-") else "ticket-" + arg)
    else:
        tickets = sorted(labels)

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(RUNS, stamp)
    os.makedirs(run_dir, exist_ok=True)

    rows = []
    failures = []
    field_hits = 0
    perfect_tickets = 0

    for ticket_id in tickets:
        expected = labels[ticket_id]
        number = ticket_id.split("-", 1)[1]

        proc = run_ticket(number)
        if proc.returncode != 0:
            last = (proc.stderr or "").strip().splitlines()
            detail = last[-1] if last else "failed"
            failures.append((ticket_id, "script", detail))
            rows.append((ticket_id, ["ERR"] * len(FIELDS), 0))
            with open(os.path.join(run_dir, ticket_id + ".err.txt"), "w", encoding="utf-8") as f:
                f.write(proc.stderr or "")
            continue

        try:
            data = parse_json(proc.stdout)
            with open(os.path.join(run_dir, ticket_id + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except Exception as exc:
            failures.append((ticket_id, "output", str(exc)))
            rows.append((ticket_id, ["ERR"] * len(FIELDS), 0))
            with open(os.path.join(run_dir, ticket_id + ".raw.txt"), "w", encoding="utf-8") as f:
                f.write(proc.stdout)
            continue

        marks = []
        hits = 0
        for field in FIELDS:
            got = data.get(field)
            want = expected[field]
            if got == want:
                marks.append("OK")
                hits += 1
            else:
                marks.append("--")
                failures.append((ticket_id, field, f"want {want!r} got {got!r}"))

        if data.get("ticket_id") != ticket_id:
            failures.append(
                (ticket_id, "ticket_id", f"want {ticket_id!r} got {data.get('ticket_id')!r}")
            )

        field_hits += hits
        if hits == len(FIELDS):
            perfect_tickets += 1
        rows.append((ticket_id, marks, hits))

    total_fields = len(tickets) * len(FIELDS)

    lines = []
    lines.append(f"{'ticket':12s} " + " ".join(f"{f:>9s}" for f in FIELDS) + "   hits")
    for ticket_id, marks, hits in rows:
        lines.append(f"{ticket_id:12s} " + " ".join(f"{m:>9s}" for m in marks) + f"   {hits}/5")
    lines.append("")
    lines.append(f"campos : {field_hits}/{total_fields}")
    lines.append(f"tickets: {perfect_tickets}/{len(tickets)} perfectos")

    if failures:
        lines.append("")
        lines.append("detalle de fallos:")
        for ticket_id, field, detail in failures:
            lines.append(f"  {ticket_id:12s} {field:12s} {detail}")

    report = "\n".join(lines)
    print()
    print(report)

    with open(os.path.join(run_dir, "score.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")

    history = os.path.join(RUNS, "history.txt")
    with open(history, "a", encoding="utf-8") as f:
        f.write(f"{stamp}  campos {field_hits}/{total_fields}  "
                f"tickets {perfect_tickets}/{len(tickets)}\n")

    print()
    print(f"guardado en {os.path.relpath(run_dir, HERE)}/")
    print(f"historial  {os.path.relpath(history, HERE)}")


if __name__ == "__main__":
    main()
