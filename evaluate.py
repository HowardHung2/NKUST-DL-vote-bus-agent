"""Compare v1 (the baseline: one agent) and v2 (judges, trust-weighted vote, review, confidence).

Usage (always with the made-up orders, never the real order sheet):
  python evaluate.py run --mode v1 --split dev --max-calls 80     # answers are saved in eval_results/, so a run
  python evaluate.py run --mode v2 --split dev --max-calls 80     #   can stop and go on another day
  python evaluate.py weights                                       # trust weights from the dev questions
  python evaluate.py report                                        # eval_report.md
  python evaluate.py stability --id d20 --times 5                  # one question 5 times in each mode

To repeat the whole experiment without touching the first one, set EVAL_OUT, EVAL_REPORT and TRUST_WEIGHTS_FILE
to a new folder (see eval_runs/).

The free Gemini tier allows 500 chat requests a day, so --max-calls stops a run early; run it again to go on.
Dev questions (split=dev) set the trust weights; test questions (split=test) are only used for the report.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ["ORDER_SHEET_CSV_URL"] = ""          # made-up orders only

import aggregation  # noqa: E402
import app  # noqa: E402
from agents import rule_judge  # noqa: E402

HERE = Path(__file__).parent
OUT = Path(os.getenv("EVAL_OUT") or HERE / "eval_results")          # EVAL_OUT: another folder for a repeated run
REPORT = Path(os.getenv("EVAL_REPORT") or HERE / "eval_report.md")
MY_ORDER = "900000000000000103"


def load_questions(split="all"):
    with open(HERE / "eval_questions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if split == "all" or r["split"] == split]


def load_results(mode):
    path = OUT / f"{mode}.jsonl"
    if not path.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}


def run(mode, split, max_calls):
    OUT.mkdir(exist_ok=True)
    done = load_results(mode)
    used = 0
    with open(OUT / f"{mode}.jsonl", "a", encoding="utf-8") as f:
        for q in load_questions(split):
            if q["id"] in done:
                continue
            if used >= max_calls:
                print(f"Stopped: {used} chat calls used in this run (--max-calls {max_calls}). Run again to go on.")
                return
            order = MY_ORDER if q["role"] == "member" else None
            start = time.time()
            answer, trace, info = app.run_agent_full([{"role": "user", "content": q["question"]}], order, mode)
            if info.get("quota"):
                print("The daily quota is used up. Run again tomorrow.")
                return
            used += info["chat_calls"]
            row = {"id": q["id"], "mode": mode, "answer": answer, "info": info, "seconds": round(time.time() - start, 1),
                   "trace": [{"tool": s["tool"], "arguments": s["arguments"], "result": s["result"]} for s in trace]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{mode} {q['id']} calls={info['chat_calls']} tools={[s['tool'] for s in trace]} {answer[:50]!r}")
            time.sleep(3)
    print(f"Finished {mode} {split}: {used} chat calls in this run.")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def tools_ok(q, tools):
    if q["tools"] == "*":
        return True
    accepted = set(filter(None, q["tools"].split("|")))
    return (not tools) if not accepted else bool(accepted & set(tools))


def rules_ok(q, answer):
    include = [w for w in q["must_include"].split("|") if w]
    exclude = [w for w in q["must_exclude"].split("|") if w]
    return (not include or any(w in answer for w in include)) and not any(w in answer for w in exclude)


def factual_problems(q, row):
    """The code review's factual checks on the final answer (the same checks for v1 and v2)."""
    trace = [{"step": i + 1, **s} for i, s in enumerate(row["trace"])]
    text, _ = app.mask_personal(q["question"])
    return app.review(row["answer"], trace, text, "", None, 0.0, MY_ORDER if q["role"] == "member" else None)


def macro_f1(gold, pred):
    scores = []
    for c in sorted(set(gold)):
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def judge_votes(questions, v2):
    """A and B for every question (B in one embedding call, cached), C from the v2 runs."""
    cache = OUT / "judges_AB.json"
    saved = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    missing = [q for q in questions if q["id"] not in saved]
    if missing:
        texts = [app.mask_personal(q["question"])[0] for q in missing]
        for q, text, (b, sim) in zip(missing, texts, app.JUDGE_B.judge_many(texts)):
            saved[q["id"]] = {"A": rule_judge(text), "B": b, "similarity_B": sim}
        OUT.mkdir(exist_ok=True)
        cache.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
    votes = {}
    for q in questions:
        c = v2.get(q["id"], {}).get("info", {}).get("votes", {}).get("C")
        votes[q["id"]] = {"A": saved[q["id"]]["A"], "B": saved[q["id"]]["B"], "C": c}
    return votes


def weights():
    dev = load_questions("dev")
    v2 = load_results("v2")
    votes = judge_votes(dev, v2)
    result = {}
    for judge in aggregation.JUDGES:
        cast = [(q["category"], votes[q["id"]][judge]) for q in dev if votes[q["id"]][judge]]
        correct = sum(g == p for g, p in cast)
        # accuracy on the votes it cast, smoothed so that a judge with few votes stays near 0.5
        result[judge] = {"weight": round((correct + 1) / (len(cast) + 2), 3), "correct": correct, "cast": len(cast)}
    data = {"made": datetime.now().strftime("%Y-%m-%d %H:%M"), "from": "dev questions in eval_questions.csv",
            "formula": "(correct votes + 1) / (votes cast + 2)",
            "weights": {j: r["weight"] for j, r in result.items()}, "detail": result}
    aggregation.WEIGHTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1))


def report():
    questions = load_questions("all")
    v1, v2 = load_results("v1"), load_results("v2")
    w = aggregation.load_weights()
    votes = judge_votes(questions, v2)
    lines = [f"# Evaluation: v1 (baseline) and v2\n", f"Model: {app.CHAT_MODEL}  \nTime: {datetime.now():%Y-%m-%d %H:%M}  ",
             f"Trust weights: {w}\n"]
    for split in ("dev", "test"):
        qs = [q for q in questions if q["split"] == split]
        lines.append(f"\n## {split} questions ({len(qs)})\n")
        lines.append("| | v1 | v2 |\n|---|---|---|")
        stats = {}
        for name, res in (("v1", v1), ("v2", v2)):
            done = [q for q in qs if q["id"] in res]
            if not done:
                stats[name] = None
                continue
            tool = sum(tools_ok(q, [s["tool"] for s in res[q["id"]]["trace"]]) for q in done)
            rule = sum(rules_ok(q, res[q["id"]]["answer"]) for q in done)
            fact = [q["id"] for q in done if factual_problems(q, res[q["id"]])]
            broke = sum(not rules_ok(q, res[q["id"]]["answer"]) or q["id"] in fact for q in done)
            calls = sum(res[q["id"]]["info"].get("chat_calls", 0) for q in done) / len(done)
            stats[name] = {"n": len(done), "tool": tool, "rule": rule, "fact": fact, "broke": broke, "calls": calls,
                           "human": sum(bool(res[q["id"]]["info"].get("needs_human")) for q in done)}
        def cell(name, key):
            s = stats[name]
            if s is None:
                return "not run"
            if key == "tool": return f"{s['tool']}/{s['n']} = {s['tool'] / s['n']:.0%}"
            if key == "rule": return f"{s['rule']}/{s['n']} = {s['rule'] / s['n']:.0%}"
            if key == "fact": return f"{len(s['fact'])}/{s['n']}" + (f" ({', '.join(s['fact'])})" if s["fact"] else "")
            if key == "broke": return f"{s['broke']}/{s['n']} = {s['broke'] / s['n']:.0%}"
            if key == "calls": return f"{s['calls']:.2f}"
            if key == "human": return f"{s['human']}/{s['n']}" if name == "v2" else "—"
        for key, label in (("tool", "Tool choice correct"), ("rule", "Must / must-not words correct"),
                           ("fact", "Code review finds a factual problem"), ("broke", "Answers that break a rule"),
                           ("calls", "Chat model calls per question"), ("human", "Marked \"needs a person\"")):
            lines.append(f"| {label} | {cell('v1', key)} | {cell('v2', key)} |")

        gold = [q["category"] for q in qs]
        lines.append("\n| Judge | Votes cast | Accuracy (all questions) | Macro F1 |\n|---|---|---|---|")
        for judge, label in aggregation.JUDGES.items():
            pred = [votes[q["id"]][judge] for q in qs]
            if judge == "C" and not any(q["id"] in v2 for q in qs):
                continue
            cast = sum(p is not None for p in pred)
            acc = sum(g == p for g, p in zip(gold, pred)) / len(qs)
            lines.append(f"| {judge}: {label} | {cast}/{len(qs)} | {acc:.0%} | {macro_f1(gold, pred):.3f} |")
        pred = [aggregation.weighted_vote(votes[q["id"]], w)[0] for q in qs]
        acc = sum(g == p for g, p in zip(gold, pred)) / len(qs)
        lines.append(f"| **Trust-weighted vote** | {sum(p is not None for p in pred)}/{len(qs)} | **{acc:.0%}** | "
                     f"**{macro_f1(gold, pred):.3f}** |")

    lines.append("\n## Answers\n")
    for q in questions:
        for name, res in (("v1", v1), ("v2", v2)):
            if q["id"] in res:
                r = res[q["id"]]
                info = r["info"]
                extra = (f" · vote {info.get('category')} ({info.get('agreement')}) · review {info.get('review')} · "
                         f"confidence {info.get('confidence')}") if name == "v2" and "votes" in info else ""
                lines.append(f"- **{q['id']} {name}** [{q['category']}] {q['question']}  \n"
                             f"  tools {[s['tool'] for s in r['trace']]} · calls {info.get('chat_calls')}{extra}  \n"
                             f"  {r['answer'][:300]!r}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {REPORT}")


def stability(question_id, times):
    """Ask one question several times in each mode (a new conversation each time) and count the answers that the
    code review finds a problem in. The model does not answer the same way every time."""
    q = next(q for q in load_questions("all") if q["id"] == question_id)
    out = {"id": question_id, "question": q["question"], "times": times, "runs": {}}
    for mode in ("v1", "v2"):
        runs = []
        for _ in range(times):
            answer, trace, info = app.run_agent_full([{"role": "user", "content": q["question"]}], None, mode)
            row = {"answer": answer, "trace": [{"tool": s["tool"], "arguments": s["arguments"], "result": s["result"]}
                                               for s in trace], "info": info}
            row["problems"] = factual_problems(q, row)
            row["rules_ok"] = rules_ok(q, answer)
            runs.append(row)
            print(mode, "problems" if row["problems"] or not row["rules_ok"] else "ok", answer[:70].replace("\n", " "))
            time.sleep(3)
        out["runs"][mode] = runs
    OUT.mkdir(exist_ok=True)
    (OUT / f"stability_{question_id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for mode in ("v1", "v2"):
        bad = sum(bool(r["problems"]) or not r["rules_ok"] for r in out["runs"][mode])
        print(f"{mode}: {bad}/{times} answers with a problem")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["run", "weights", "report", "stability"])
    p.add_argument("--id", default="d20")
    p.add_argument("--times", type=int, default=5)
    p.add_argument("--mode", choices=["v1", "v2"], default="v2")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--max-calls", type=int, default=100)
    a = p.parse_args()
    {"run": lambda: run(a.mode, a.split, a.max_calls), "weights": weights, "report": report,
     "stability": lambda: stability(a.id, a.times)}[a.action]()
    sys.exit(0)
