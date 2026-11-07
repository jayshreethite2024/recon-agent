"""
Stage 5: MCP server exposing the recon investigation tools.

Any MCP client (our agent, Claude Desktop, Cursor...) can connect, discover
these tools and call them. The tool code itself is unchanged: it's imported
from agent/tools.py. The docstrings below are the tool descriptions clients see.

Run on its own (clients usually start it for you):
    python3 mcp_server/server.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp.server.mcpserver import MCPServer
from agent import tools

server = MCPServer("recon-tools", instructions="Tools to investigate Unclassified reinsurance recon rows.")


@server.tool()
def get_outbound_postings(txn_id: str) -> dict:
    """List every outbound posting for a transaction across ALL cycles (this and later).
    Use to detect postings in a later cycle or multiple postings."""
    return tools.get_outbound_postings(txn_id)


@server.tool()
def check_reference_code(code: str) -> dict:
    """Check whether a company code exists in the valid reference table.
    If not, returns valid codes that differ by one digit (likely typos)."""
    return tools.check_reference_code(code)


@server.tool()
def get_treaty_terms(treaty_id: str) -> dict:
    """Get the treaty setup as held in SRM: share %, contract start/end, ceding company."""
    return tools.get_treaty_terms(treaty_id)


@server.tool()
def search_treaty(treaty_id: str, query: str) -> dict:
    """Search the treaty DOCUMENT text and return the 3 most relevant clauses, including
    endorsements. Write a short keyword query, e.g. 'reinsurer share amendment'."""
    return tools.search_treaty(treaty_id, query)


if __name__ == "__main__":
    server.run()   # stdio: the client talks to this process through stdin/stdout
