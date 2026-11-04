"""
Stage 1: generate synthetic reinsurance recon data.
Everything is invented: no client names, codes or data.

Run:  python scripts/generate_data.py      (writes into data/)
"""
import csv, random, json
from datetime import date, timedelta
from pathlib import Path

random.seed(42)                     # same data every run
DATA = Path(__file__).resolve().parent.parent / "data"
CYCLE, NEXT_CYCLE = "2026-Q3-C1", "2026-Q3-C2"
TOLERANCE = 0.90

# ---------------- reference data ----------------
REFERENCE_CODES = {"7310": "Northwind Mutual", "4475": "Bluefield Insurance",
                   "6120": "Harbor Point Assurance", "5583": "Crestline General"}

TREATIES = [  # treaty report as SRM holds it (T003's share is STALE: endorsement changed it)
    {"treaty_id": "T001", "contract_name": "Northwind Property QS 2026", "ceding_company_code": "7310",
     "participation_pct": 20.0, "start_date": "2026-01-01", "end_date": "2026-12-31"},
    {"treaty_id": "T002", "contract_name": "Bluefield Casualty QS 2026", "ceding_company_code": "4475",
     "participation_pct": 25.0, "start_date": "2026-01-01", "end_date": "2026-12-31"},
    {"treaty_id": "T003", "contract_name": "Harbor Point Marine QS 2026", "ceding_company_code": "6120",
     "participation_pct": 20.0, "start_date": "2026-01-01", "end_date": "2026-12-31"},
    {"treaty_id": "T004", "contract_name": "Crestline Motor QS 2026", "ceding_company_code": "5583",
     "participation_pct": 30.0, "start_date": "2026-04-01", "end_date": "2027-03-31"},
]
TREATY = {t["treaty_id"]: t for t in TREATIES}

# ---------------- build transactions ----------------
inbound, outbound, error, retention, answer_key = [], [], [], [], []
txn = 10000

def rand_date(start="2026-07-01", end="2026-09-30"):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return (s + timedelta(days=random.randint(0, (e - s).days))).isoformat()

def new_txn(treaty_id, amount=None, policy_date=None, company_code=None):
    global txn
    txn += 1
    t = TREATY[treaty_id]
    row = {"txn_id": txn, "cycle": CYCLE, "treaty_id": treaty_id,
           "company_code": company_code or t["ceding_company_code"],
           "policy_effective_date": policy_date or rand_date(),
           "gross_amount": round(amount if amount is not None else random.uniform(5_000, 250_000), 2),
           "financial_type": random.choice(["300", "301", "340"])}
    inbound.append(row)
    return row

def expected(row):
    return round(row["gross_amount"] * TREATY[row["treaty_id"]]["participation_pct"] / 100, 2)

def post(row, amount, cycle=CYCLE):
    outbound.append({"txn_id": row["txn_id"], "cycle": cycle, "treaty_id": row["treaty_id"],
                     "ceded_amount": round(amount, 2)})

normal_treaties = ["T001", "T002", "T004"]   # T003 rows after Jul are all affected by the endorsement

# 1. Clean rows -> Exact Match
for _ in range(380):
    r = new_txn(random.choice(normal_treaties))
    post(r, expected(r) + random.uniform(-0.5, 0.5))

# 2. Rows caught by existing recon rules
for _ in range(20):                                  # Present in Error
    r = new_txn(random.choice(normal_treaties))
    error.append({"txn_id": r["txn_id"], "error_reason": random.choice(
        ["Missing LOB mapping", "Invalid currency", "Contract not active in SRM"])})
for _ in range(15):                                  # Present in Retention
    r = new_txn(random.choice(normal_treaties))
    retention.append({"txn_id": r["txn_id"], "retained_amount": r["gross_amount"]})
for _ in range(10):                                  # 0 $ transaction
    r = new_txn(random.choice(normal_treaties), amount=0)
for _ in range(8):                                   # Policy date outside contract (T004 starts Apr)
    r = new_txn("T004", policy_date=rand_date("2026-01-01", "2026-03-20"))
    post(r, expected(r))

# 3. Seeded Unclassified root causes (the answer key) - 9 each + 5 ambiguous = 50
def seed(cause, row, note):
    answer_key.append({"txn_id": row["txn_id"], "true_root_cause": cause, "note": note})

for _ in range(9):   # A. Company code not mapped: typo of a valid code -> SRM can't route, no outbound
    good = random.choice(["7310", "4475", "5583"])
    tid = {"7310": "T001", "4475": "T002", "5583": "T004"}[good]
    bad = good[:-1] + str((int(good[-1]) + random.choice([1, 2, 3])) % 10)
    r = new_txn(tid, company_code=bad)
    seed("Company code not mapped", r, f"{bad} is a typo of valid code {good}")

for _ in range(9):   # B. Timing difference: posted in the next cycle
    r = new_txn(random.choice(normal_treaties), policy_date=rand_date("2026-09-24", "2026-09-30"))
    post(r, expected(r), cycle=NEXT_CYCLE)
    seed("Timing difference", r, "outbound present in next cycle")

for _ in range(9):   # C. Variance just beyond tolerance (rounding)
    r = new_txn(random.choice(normal_treaties))
    post(r, expected(r) + random.choice([1, -1]) * random.uniform(1.0, 4.5))
    seed("Variance just beyond tolerance", r, "small rounding variance > $0.90")

for _ in range(9):   # D. Share changed by treaty endorsement (T003: 20% -> 15% from 1 Jul 2026)
    r = new_txn("T003", policy_date=rand_date("2026-07-01", "2026-09-20"))
    post(r, r["gross_amount"] * 0.15)
    seed("Treaty amendment not reflected", r, "Endorsement 1 changed share to 15%; treaty report still 20%")

for _ in range(9):   # E. Duplicate posting
    r = new_txn(random.choice(normal_treaties))
    post(r, expected(r)); post(r, expected(r))
    seed("Duplicate posting", r, "two outbound rows for one txn")

for _ in range(5):   # F. No clear evidence -> agent should say Needs analyst
    r = new_txn(random.choice(normal_treaties))
    post(r, expected(r) * random.uniform(1.2, 1.6))
    seed("Needs analyst", r, "unexplained variance, no supporting signal")

# ---------------- run the rule-based recon (what V1 does today) ----------------
err_ids, ret_ids = {e["txn_id"] for e in error}, {r["txn_id"] for r in retention}
recon = []
for r in inbound:
    t = TREATY[r["treaty_id"]]
    exp = expected(r)
    act = round(sum(o["ceded_amount"] for o in outbound
                    if o["txn_id"] == r["txn_id"] and o["cycle"] == CYCLE), 2)
    var = round(act - exp, 2)
    if r["txn_id"] in err_ids:          comment = "Present in Error"
    elif r["txn_id"] in ret_ids:        comment = "Present in Retention"
    elif r["gross_amount"] == 0:        comment = "0 $ transaction"
    elif not (t["start_date"] <= r["policy_effective_date"] <= t["end_date"]):
        comment = "Policy effective date outside contract period"
    elif abs(var) <= TOLERANCE:         comment = "Exact Match"
    else:                               comment = "Unclassified"
    recon.append({"txn_id": r["txn_id"], "cycle": CYCLE, "treaty_id": r["treaty_id"],
                  "company_code": r["company_code"], "expected_amount": exp,
                  "actual_amount": act, "variance": var,
                  "outbound_missing": act == 0 and exp != 0, "comment": comment})

# ---------------- write files ----------------
def write(name, rows):
    with open(DATA / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)

random.shuffle(inbound)
write("inbound.csv", inbound)
write("outbound.csv", outbound)
write("error.csv", error)
write("retention.csv", retention)
write("treaty_report.csv", TREATIES)
write("reference_codes.csv", [{"company_code": k, "company_name": v} for k, v in REFERENCE_CODES.items()])
write("recon_result.csv", recon)
write("answer_key.csv", answer_key)   # HIDDEN from the agent: used only by evals

summary = {}
for r in recon: summary[r["comment"]] = summary.get(r["comment"], 0) + 1
print(json.dumps(summary, indent=2))
