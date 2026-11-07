"""
Stage 5: connect the agent to the MCP server.

MCPTools starts mcp_server/server.py as a separate process, DISCOVERS its tools
(names, descriptions, input schemas), turns them into Gemini tool declarations,
and forwards the agent's tool calls to the server.

MCP is async; our agent loop is plain (sync) Python. So the MCP connection lives
in a background thread with its own event loop, and call() waits for each result.
"""
import asyncio, json, sys, threading
from pathlib import Path
from google.genai import types
from mcp import Client, StdioServerParameters

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
WHY = {"type": "string", "description": "One sentence: why you are calling this tool"}


class MCPTools:
    source = "mcp"

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self._ready = threading.Event()
        self._stop = None
        asyncio.run_coroutine_threadsafe(self._session(), self.loop)
        if not self._ready.wait(timeout=60):
            raise RuntimeError("MCP server did not start")
        if self._error:
            raise self._error
        self.declarations = [self._to_gemini(t) for t in self.tools]

    async def _session(self):
        """Open the connection, discover tools, then stay open until close()."""
        self._error, self._stop = None, asyncio.Event()
        try:
            params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
            async with Client(params) as client:
                self.client = client
                self.tools = (await client.list_tools()).tools      # discovery
                self._ready.set()
                await self._stop.wait()
        except Exception as e:
            self._error = e
            self._ready.set()

    @staticmethod
    def _to_gemini(tool):
        """MCP tool (JSON schema) -> Gemini declaration, plus our required 'why' argument."""
        schema = json.loads(json.dumps(tool.input_schema))         # copy
        schema["properties"]["why"] = WHY
        schema["required"] = schema.get("required", []) + ["why"]
        return types.FunctionDeclaration(name=tool.name, description=tool.description,
                                         parameters_json_schema=schema)

    def call(self, name, args):
        """Send one tool call to the MCP server and return its result as a dict."""
        result = asyncio.run_coroutine_threadsafe(
            self.client.call_tool(name, args), self.loop).result(timeout=60)
        text = result.content[0].text if result.content else "{}"
        if result.is_error:
            return {"error": text}
        return json.loads(text)

    def close(self):
        if self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
