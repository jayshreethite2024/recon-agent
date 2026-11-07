"""
Stage 5 test: the MCP server gives the same answers as the local tools,
and the agent loop works through MCP. No API key needed.

Run:  python3 tests/test_mcp.py
"""
import csv, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent import tools
from agent.agent import LocalTools, make_config, investigate
from agent.mcp_tools import MCPTools
from tests.fakes import FakeClient, resp

mcp = MCPTools()                                              # starts mcp_server/server.py
passed = 0
def check(name, cond):
    global passed
    print(("PASS " if cond else "FAIL ") + name); passed += cond

# 1. Discovery: the agent finds the tools by asking the server
names = sorted(d.name for d in mcp.declarations)
check("discovers 4 tools", names == sorted(d.name for d in LocalTools.declarations))
check("adds 'why' to every tool", all("why" in d.parameters_json_schema["properties"] for d in mcp.declarations))
make_config(mcp.declarations)                                 # Gemini accepts the discovered menu
check("Gemini config builds from discovered tools", True)

# 2. Same results through MCP as calling the functions directly
key = list(csv.DictReader(open(ROOT / "data" / "answer_key.csv")))
for cause in ["Company code not mapped", "Timing difference", "Duplicate posting", "Treaty amendment not reflected"]:
    txn = next(r["txn_id"] for r in key if r["true_root_cause"] == cause)
    row = tools.get_recon_row(txn)
    for name, args in [("get_outbound_postings", {"txn_id": txn}),
                       ("check_reference_code", {"code": row["company_code"]}),
                       ("get_treaty_terms", {"treaty_id": row["treaty_id"]}),
                       ("search_treaty", {"treaty_id": row["treaty_id"], "query": "reinsurer share amendment"})]:
        local = getattr(tools, name)(**args)
        check(f"{cause}: {name} same via MCP", mcp.call(name, args) == local)

# 3. Full agent loop through MCP (scripted fake LLM)
c = FakeClient([
    resp("check_reference_code", {"code": "7311", "why": "outbound missing; code may be invalid"}),
    resp("submit_finding", {"root_cause": "Company code not mapped", "evidence": "7311 invalid; 7310 valid",
                            "confidence": "high", "why": "done"})])
r = investigate("10436", client=c, verbose=False, toolbox=mcp)
check("agent loop works through MCP", r["root_cause"] == "Company code not mapped"
      and r["trace"][0]["result"]["similar_valid_codes"] == ["7310"])

mcp.close()
print(f"\n{passed} checks passed")
