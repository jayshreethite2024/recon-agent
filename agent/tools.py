"""
Stage 2: the agent's tools.

Each tool is a plain Python function: input in, a small dict out.
The agent (Stage 3) decides WHICH tool to call; these functions do the work.
No AI in this file.
"""
import re
from pathlib import Path
import duckdb

DATA = Path(__file__).resolve().parent.parent / "data"
db = duckdb.connect()   # in-memory database; reads the CSVs directly

for table in ["inbound", "outbound", "treaty_report",
              "reference_codes", "recon_result"]:
    db.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv_auto('{DATA / table}.csv', all_varchar=true)")
# all_varchar=true keeps codes like '7310' as text, not numbers


def _rows(sql, params=()):
    """Run SQL and return a list of dicts."""
    cur = db.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ------------------------------------------------------------------
# Tool 1: the row itself
# ------------------------------------------------------------------
def get_recon_row(txn_id: str) -> dict:
    """Recon result for one transaction, plus its inbound details."""
    rows = _rows("""
        SELECT r.txn_id, r.cycle, r.treaty_id, r.company_code, r.expected_amount,
               r.actual_amount, r.variance, r.outbound_missing, r.comment,
               i.policy_effective_date, i.gross_amount, i.financial_type
        FROM recon_result r JOIN inbound i USING (txn_id)
        WHERE r.txn_id = ?""", [str(txn_id)])
    return rows[0] if rows else {"error": f"txn {txn_id} not found"}


# ------------------------------------------------------------------
# Tool 2: outbound postings across ALL cycles (timing, duplicates)
# ------------------------------------------------------------------
def get_outbound_postings(txn_id: str) -> dict:
    """Every outbound posting for a transaction, in any cycle."""
    postings = _rows("SELECT cycle, treaty_id, ceded_amount FROM outbound WHERE txn_id = ? ORDER BY cycle",
                     [str(txn_id)])
    return {"txn_id": str(txn_id), "posting_count": len(postings), "postings": postings}


# ------------------------------------------------------------------
# Tool 3: company code validity (+ near matches for typos)
# ------------------------------------------------------------------
def check_reference_code(code: str) -> dict:
    """Is the company code valid? If not, list valid codes one digit away."""
    code = str(code)
    valid = {r["company_code"]: r["company_name"] for r in _rows("SELECT * FROM reference_codes")}
    similar = [c for c in valid
               if len(c) == len(code) and sum(a != b for a, b in zip(c, code)) == 1]
    return {"code": code, "exists": code in valid, "company_name": valid.get(code),
            "similar_valid_codes": [] if code in valid else similar}


# ------------------------------------------------------------------
# Tool 4: treaty setup as SRM holds it
# ------------------------------------------------------------------
def get_treaty_terms(treaty_id: str) -> dict:
    """Treaty report terms in SRM: share %, contract period, ceding company."""
    rows = _rows("SELECT * FROM treaty_report WHERE treaty_id = ?", [str(treaty_id)])
    return rows[0] if rows else {"error": f"treaty {treaty_id} not found"}


# ------------------------------------------------------------------
# Tool 5: search treaty documents (simple RAG: chunk + retrieve)
# ------------------------------------------------------------------
def _chunk_treaty(treaty_id: str) -> list[dict]:
    """Split a treaty into clause-level chunks on 'Article' / 'Endorsement' headings."""
    text = (DATA / "treaties" / f"{treaty_id}.txt").read_text()
    # split only on real headings ("Article 4: ...", "Endorsement No. 1"), not on
    # sentences that mention an article ("Article 4 is amended...")
    parts = re.split(r"\n(?=Article \d+:|Endorsement No\.)", text)
    return [{"section": p.strip().splitlines()[0], "text": " ".join(p.strip().splitlines()[1:]).strip()}
            for p in parts[1:]]   # parts[0] is the title block

STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "is", "for", "on", "by", "any", "all"}

def search_treaty(treaty_id: str, query: str, top_k: int = 3) -> dict:
    """Return the treaty clauses most relevant to the query (keyword match).
    Stage 3 upgrade: swap keyword scoring for embeddings."""
    path = DATA / "treaties" / f"{treaty_id}.txt"
    if not path.exists():
        return {"error": f"no document for treaty {treaty_id}"}
    stem = lambda w: w[:5]   # crude stemming: "amended"/"amendment" -> "amend"
    tokens = lambda s: [w for w in re.findall(r"[a-z0-9%]+", s.lower()) if w not in STOPWORDS]
    query_stems = {stem(w) for w in tokens(query)}
    scored = []
    for ch in _chunk_treaty(treaty_id):
        score = sum(stem(w) in query_stems for w in tokens(ch["section"] + " " + ch["text"]))
        if score:
            scored.append({**ch, "score": score})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return {"treaty_id": treaty_id, "query": query, "results": scored[:top_k]}


# Name -> function lookup, used by the agent loop
TOOLS = {f.__name__: f for f in [get_recon_row, get_outbound_postings, check_reference_code,
                                 get_treaty_terms, search_treaty]}
