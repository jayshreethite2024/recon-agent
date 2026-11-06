"""
Stage 3: run the agent on Unclassified rows and watch it investigate.

Setup once:   create a file called .env in the project folder containing
              GEMINI_API_KEY=your-key-here

Run:
    python3 scripts/run_agent.py --txn 10436        # one row
    python3 scripts/run_agent.py --sample 5         # 5 random Unclassified rows
    python3 scripts/run_agent.py --sample 5 --check # also compare with the answer key
"""
import argparse, csv, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")                      # puts GEMINI_API_KEY into the environment
from agent.agent import investigate

parser = argparse.ArgumentParser()
parser.add_argument("--txn", help="one transaction id")
parser.add_argument("--sample", type=int, help="number of random Unclassified rows")
parser.add_argument("--check", action="store_true", help="compare with answer_key.csv")
args = parser.parse_args()

unclassified = [r["txn_id"] for r in csv.DictReader(open(ROOT / "data" / "recon_result.csv"))
                if r["comment"] == "Unclassified"]
txns = [args.txn] if args.txn else random.Random(7).sample(unclassified, args.sample or 3)

truth = {r["txn_id"]: r["true_root_cause"] for r in csv.DictReader(open(ROOT / "data" / "answer_key.csv"))}
correct = 0
for t in txns:
    result = investigate(t)
    if args.check:
        ok = result["root_cause"] == truth.get(t)
        correct += ok
        print(f"   {'CORRECT' if ok else 'WRONG'} (true: {truth.get(t)})")

if args.check:
    print(f"\n{correct}/{len(txns)} correct")
