"""
Stage 2 tests: for one row of each seeded root cause, check the tools
surface the evidence an analyst (or the agent) would need.

Run:  python tests/test_tools.py
"""
import csv, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.tools import (get_recon_row, get_outbound_postings, check_reference_code,
                         get_treaty_terms, search_treaty)

key = list(csv.DictReader(open(ROOT / "data" / "answer_key.csv")))
first = lambda cause: next(r["txn_id"] for r in key if r["true_root_cause"] == cause)
passed = 0

def check(name, condition):
    global passed
    print(("PASS " if condition else "FAIL ") + name)
    passed += condition

# A. Company code not mapped -> code invalid, one similar valid code
t = first("Company code not mapped")
row = get_recon_row(t)
ref = check_reference_code(row["company_code"])
check("code not mapped: code invalid", not ref["exists"])
check("code not mapped: near-match found", len(ref["similar_valid_codes"]) == 1)

# B. Timing difference -> no posting this cycle, one in next cycle
t = first("Timing difference")
post = get_outbound_postings(t)
check("timing: posted only in next cycle", [p["cycle"] for p in post["postings"]] == ["2026-Q3-C2"])

# C. Small variance -> variance between $0.90 and $5
t = first("Variance just beyond tolerance")
check("small variance: 0.90 < |variance| < 5", 0.90 < abs(float(get_recon_row(t)["variance"])) < 5)

# D. Treaty amendment -> SRM says 20%, treaty endorsement says 15%
t = first("Treaty amendment not reflected")
row = get_recon_row(t)
terms = get_treaty_terms(row["treaty_id"])
hits = search_treaty(row["treaty_id"], "reinsurer share amendment")
check("amendment: SRM share is 20%", float(terms["participation_pct"]) == 20.0)
endorsement = [h for h in hits["results"] if h["section"].startswith("Endorsement")]
check("amendment: Endorsement in top 3 results", len(endorsement) == 1)
check("amendment: endorsement mentions 15%", bool(endorsement) and "15%" in endorsement[0]["text"])

# E. Duplicate -> two postings in this cycle
t = first("Duplicate posting")
check("duplicate: two postings", get_outbound_postings(t)["posting_count"] == 2)

# Distractor: T002 commission endorsement should NOT top a share query
hits = search_treaty("T002", "reinsurer share")
check("distractor: T002 share query returns Article 4", hits["results"][0]["section"].startswith("Article 4"))

print(f"\n{passed} checks passed")
