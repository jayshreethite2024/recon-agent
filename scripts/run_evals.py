"""
Stage 4: evaluate the agent on all 50 Unclassified rows against the answer key.

Run:
    python3 scripts/run_evals.py --limit 5     # quick check on 5 rows
    python3 scripts/run_evals.py               # all 50 rows (~15-40 min)

Writes to results/:
    eval_<time>.csv      one row per transaction (open in Excel)
    eval_<time>.md       summary report
    traces_<time>.jsonl  every tool call, for debugging
"""
import argparse, csv, json, sys, time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from agent.agent import investigate, ROOT_CAUSES

# Which tool(s) a good investigation MUST use to justify each root cause,
# and the fewest tool calls needed (submit_finding not counted)
REQUIRED_TOOLS = {
    "Company code not mapped":        {"check_reference_code"},
    "Timing difference":              {"get_outbound_postings"},
    "Variance just beyond tolerance": set(),
    "Treaty amendment not reflected": {"search_treaty"},
    "Duplicate posting":              {"get_outbound_postings"},
    "Needs analyst":                  set(),
}
MIN_STEPS = {"Company code not mapped": 1, "Timing difference": 1, "Variance just beyond tolerance": 0,
             "Treaty amendment not reflected": 2, "Duplicate posting": 1, "Needs analyst": 2}


def evaluate(rows, run, pause=0):
    """rows: list of (txn_id, true_cause). run: function txn_id -> agent result."""
    results = []
    for i, (txn, truth) in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] txn {txn} ...", end=" ", flush=True)
        try:
            r = run(txn)
        except Exception as e:                       # one bad row shouldn't kill the run
            r = {"txn_id": txn, "root_cause": "ERROR", "evidence": str(e)[:200], "confidence": "",
                 "steps": 0, "tools_used": [], "models": [], "tokens_in": 0, "tokens_out": 0,
                 "seconds": 0, "trace": []}
        tools = [t for t in r["tools_used"] if t != "submit_finding"]
        r.update(true_cause=truth, correct=r["root_cause"] == truth, tool_calls=len(tools),
                 used_required_tools=REQUIRED_TOOLS[truth] <= set(tools),
                 extra_steps=max(0, len(tools) - MIN_STEPS[truth]))
        print(("CORRECT" if r["correct"] else f"WRONG ({r['root_cause']})") + f" | {len(tools)} tool calls")
        results.append(r)
        time.sleep(pause)
    return results


def summarise(results):
    n = len(results)
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"
    avg = lambda key: sum(r[key] for r in results) / n
    lines = [f"# Eval report ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"Rows: {n} | Models: {', '.join(sorted({m for r in results for m in r['models']})) or '-'}", ""]

    correct = sum(r["correct"] for r in results)
    errors = sum(r["root_cause"] == "ERROR" for r in results)
    lines += ["## Headline", "| Metric | Value |", "|---|---|",
              f"| **Accuracy** | **{correct}/{n} = {pct(correct, n)}** |",
              f"| Correct AND used the right tools | {pct(sum(r['correct'] and r['used_required_tools'] for r in results), n)} |",
              f"| Avg tool calls per row | {avg('tool_calls'):.1f} |",
              f"| Rows with extra (unneeded) steps | {pct(sum(r['extra_steps'] > 0 for r in results), n)} |",
              f"| Avg tokens per row (in + out) | {avg('tokens_in'):.0f} + {avg('tokens_out'):.0f} |",
              f"| Avg seconds per row | {avg('seconds'):.1f} |",
              f"| Run errors | {errors} |", ""]

    # Safety: does it admit uncertainty instead of guessing?
    unclear = [r for r in results if r["true_cause"] == "Needs analyst"]
    said_unsure = [r for r in results if r["root_cause"] == "Needs analyst"]
    lines += ["## Safety (\"Needs analyst\")", "| Metric | Value | Why it matters |", "|---|---|---|",
              f"| Unclear rows correctly sent to analyst | {sum(r['correct'] for r in unclear)}/{len(unclear)} | Guessing on these = confident wrong answers |",
              f"| Clear rows wrongly sent to analyst | {sum(r['true_cause'] != 'Needs analyst' for r in said_unsure)} | Too cautious = less time saved |",
              f"| Wrong answers marked HIGH confidence | {sum((not r['correct']) and r['confidence'] == 'high' for r in results)} | Worst case: confidently wrong |", ""]

    # Per root cause: precision (when it says X, is it right?) and recall (of real X, how many found?)
    lines += ["## Per root cause", "| Root cause | Rows | Recall (found) | Precision (right when it says so) | Avg tool calls |",
              "|---|---|---|---|---|"]
    for c in ROOT_CAUSES:
        real = [r for r in results if r["true_cause"] == c]
        said = [r for r in results if r["root_cause"] == c]
        if not real and not said:
            continue
        tp = sum(r["correct"] for r in real)
        calls = sum(r["tool_calls"] for r in real) / len(real) if real else 0
        lines.append(f"| {c} | {len(real)} | {pct(tp, len(real))} | {pct(tp, len(said))} | {calls:.1f} |")

    # Confidence calibration: is "high" really more accurate than "low"?
    lines += ["", "## Confidence vs accuracy", "| Confidence | Rows | Accuracy |", "|---|---|---|"]
    by_conf = defaultdict(list)
    for r in results:
        by_conf[r["confidence"] or "none"].append(r["correct"])
    for conf in ["high", "medium", "low", "none"]:
        if by_conf[conf]:
            lines.append(f"| {conf} | {len(by_conf[conf])} | {pct(sum(by_conf[conf]), len(by_conf[conf]))} |")

    # Confusion: what gets mixed up
    mistakes = Counter((r["true_cause"], r["root_cause"]) for r in results if not r["correct"])
    lines += ["", "## Mistakes (true → predicted)"]
    lines += [f"- {t} → {p}: {k} row(s)" for (t, p), k in mistakes.most_common()] or ["- None"]
    return "\n".join(lines) + "\n"


def save(results, report):
    out = ROOT / "results"; out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    cols = ["txn_id", "true_cause", "root_cause", "correct", "confidence", "used_required_tools",
            "tool_calls", "extra_steps", "tools_used", "models", "tokens_in", "tokens_out", "seconds", "evidence"]
    with open(out / f"eval_{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in results:
            w.writerow({**r, "tools_used": " > ".join(r["tools_used"]), "models": ",".join(r["models"])})
    with open(out / f"traces_{stamp}.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps({"txn_id": r["txn_id"], "true_cause": r["true_cause"], "trace": r["trace"]}) + "\n")
    (out / f"eval_{stamp}.md").write_text(report)
    return out / f"eval_{stamp}.md"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="only the first N rows (quick check)")
    p.add_argument("--pause", type=float, default=2, help="seconds between rows (avoids rate limits)")
    a = p.parse_args()
    rows = [(r["txn_id"], r["true_root_cause"]) for r in csv.DictReader(open(ROOT / "data" / "answer_key.csv"))]
    import random; random.Random(1).shuffle(rows)        # mix causes, so --limit gets variety
    rows = rows[: a.limit] if a.limit else rows
    results = evaluate(rows, lambda t: investigate(t, verbose=False), pause=a.pause)
    report = summarise(results)
    print("\n" + report)
    print(f"Saved: {save(results, report)}")
