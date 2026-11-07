# Stage 5: MCP

**In one line:** we moved the 4 investigation tools into an MCP server. The agent now *discovers* the tools from the server and calls them through it, and any other MCP app (e.g. Claude Desktop) can use the same tools.

## What MCP is, simply
**MCP (Model Context Protocol)** is a standard way for AI apps to find and use tools. Like a USB port: any MCP app can plug into any MCP server.

| Without MCP (Stage 3) | With MCP (Stage 5) |
|---|---|
| Tools are functions inside our agent's code | Tools live in a separate **server** process |
| We hand-write each tool's description for Gemini | The agent **asks the server** "what tools do you have?" and gets names, descriptions and inputs |
| Only our agent can use them | Any MCP client can use them: our agent, Claude Desktop, Cursor… |

The tool code itself didn't change: the server imports the same functions from `agent/tools.py`.

## How the data flows
```
agent (investigate)
   │  1. at start: "what tools do you have?"  (list_tools)
   ▼
MCPTools (agent/mcp_tools.py) ──── stdin/stdout ────► MCP server (mcp_server/server.py)
   │  turns each tool into a Gemini declaration          │
   │  (+ adds our "why" field)                            │ runs agent/tools.py functions
   │  2. per step: call_tool(name, args) ───────────────►│ returns result as JSON
   ◄──────────────────────────────────────────────────────┘
Gemini sees the same menu as before; submit_finding stays in the agent
```

## Files
| File | What it does |
|---|---|
| `mcp_server/server.py` | The MCP server: 4 tools, each wrapping a function from `agent/tools.py` |
| `agent/mcp_tools.py` | The MCP client: starts the server, discovers tools, forwards calls |
| `agent/agent.py` | Now works with either tool source: local functions or MCP |
| `tests/test_mcp.py` | 20 checks: discovery, same results as local, agent loop through MCP |
| `tests/fakes.py` | Fake Gemini, shared by the tests |

## Code map: `mcp_server/server.py`
| What happens | Lines | In plain words |
|---|---|---|
| Create the server | 18 | Named "recon-tools", with a one-line description for clients |
| Register a tool | 21–22 (and 28, 35, 41) | `@server.tool()` turns a Python function into an MCP tool. The **function name** becomes the tool name, the **type hints** (`txn_id: str`) become the input schema, the **docstring** becomes the description clients see |
| Start | 49 | `server.run()` listens on stdin/stdout ("stdio"): the client starts this as a child process and talks to it through pipes |

## Code map: `agent/mcp_tools.py`
| What happens | Lines | In plain words |
|---|---|---|
| Where the server is | 16 | Path to `server.py` |
| Start everything | 23–33 | Starts a background thread with its own event loop, opens the connection, waits until tools are discovered |
| **Discovery** | 42 | `list_tools()`: asks the server what it offers |
| Stay connected | 35–47 | Keeps the connection open for the whole run (starting a server per call would be slow) |
| **MCP → Gemini** | 50–56 | Converts each tool's JSON schema into a Gemini declaration and adds our required `why` field |
| **Call a tool** | 58–65 | Sends `call_tool(name, args)` to the server, waits for the answer, turns the JSON text back into a dict |
| Close | 67 | Ends the connection |

**Why a background thread?** The MCP library is *async* (built to handle many things at once); our agent loop is plain step-by-step Python. The thread runs the async side; `call()` waits for each result, so the agent loop didn't need rewriting.

## Code map: `agent/agent.py` (changes)
| What happens | Lines | In plain words |
|---|---|---|
| Local tool menu | 45 | Hand-written declarations (used when `TOOL_SOURCE=local`) |
| Final answer tool | 64 | `submit_finding` is separate: it's the agent's output, not a data tool, so it never goes on the server |
| **Choose the source** | 78 | `TOOL_SOURCE` in `.env`: `local` (default) or `mcp` |
| Local toolbox | 80 | Same shape as MCPTools: a menu (`declarations`) and `call()` |
| Create once | 88 | Starts the toolbox once per run and reuses it |
| Build the Gemini config | 99, 110 | Menu = tools + `submit_finding` |
| Pick toolbox and menu | 161–162 | In `investigate`: local menu, or the discovered MCP menu |
| **Run a tool** | 199 | `toolbox.call(...)`: the loop doesn't care whether it's local or MCP |

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Server wraps existing functions | One source of truth for tool logic; Stage 2 tests still apply | — |
| Docstrings = descriptions | Clients see exactly what the code says | Descriptions must be written well in the server |
| Agent discovers tools at runtime | Add a tool on the server and the agent sees it without code changes | Less control over each description |
| `why` added by the client, not the server | `why` is for our agent's audit trail; other MCP apps shouldn't need it | — |
| `submit_finding` stays in the agent | It's the agent's answer format, not a data capability | — |
| stdio transport (local pipes) | Simplest; no network, no auth | Server must run on the same machine. Remote would use HTTP transport |
| Toggle with `TOOL_SOURCE` | Compare local vs MCP on the same evals; fall back if MCP breaks | — |
| One connection per run | Starting the server takes ~1s; per call it would be slow | — |
| Tested equivalence | 16 checks prove MCP returns exactly what the local functions return | — |

## Optional demo: use the tools from Claude Desktop
Add to Claude Desktop's MCP config (Settings → Developer → Edit Config), with your real paths:
```json
{
  "mcpServers": {
    "recon-tools": {
      "command": "/full/path/to/python3",
      "args": ["/full/path/to/recon-agent/mcp_server/server.py"]
    }
  }
}
```
Restart Claude Desktop, then ask: *"Using recon-tools, check whether company code 7311 is valid."* Same tools, different AI app. That's the point of MCP.

## Likely interview questions
| Question | Answer |
|---|---|
| What is MCP? | A standard protocol for AI apps to discover and call tools. Server exposes tools; any client can use them. |
| Why use it here? | Tools become reusable: our agent, Claude Desktop or another team's agent can use the same recon tools without custom integration. |
| What changed in the agent? | It discovers tools from the server instead of hard-coding them, and sends calls to the server. The loop is unchanged. |
| How did you know MCP didn't break anything? | Equivalence tests (MCP results = local results) and the same 50-row eval with `TOOL_SOURCE=mcp`. |
| Why is `submit_finding` not on the server? | It's the agent's output format, not a data tool. Other clients don't need it. |
| stdio vs HTTP? | stdio = server runs locally as a child process; simplest. HTTP = remote/shared server, needs auth. Production would likely be HTTP. |
| What are the risks of MCP in a bank? | A server is a new access point to data: needs auth, access control, logging and read-only tools. Ours are read-only lookups by design. |

---

## Results
| Check | Result |
|---|---|
| `tests/test_mcp.py` | 20/20 passed: discovery, same results as local tools, agent loop through MCP |
| 50-row eval with `TOOL_SOURCE=mcp` | **50/50 = 100%**, 5/5 unclear escalated, 0 confidently wrong, 1.8 tool calls/row, 7.5 s/row |
| Tokens per row | ~4,190 in vs ~3,800 with local tools |

**Why more tokens through MCP?** The tool menu Gemini sees is built from the server's schemas, which carry a little extra (e.g. "title" fields and longer docstrings) compared with the hand-written local menu. It's sent on every call, so it adds up. A possible tidy-up: strip unneeded schema fields in `_to_gemini`.

**Combined v2 total (local ×2 + MCP ×1):** 149/150 = 99.3%, 15/15 unclear rows escalated, 0 confidently wrong in 150 investigations.

**Q: How do you prove MCP didn't change behaviour?**
Two levels: unit-level equivalence (16 checks that MCP returns exactly what the local functions return) and system-level: the same 50-row eval gave the same accuracy and safety.
