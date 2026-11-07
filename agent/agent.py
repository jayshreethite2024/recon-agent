"""
Stage 3: the agent loop.

investigate(txn_id) gives the LLM one Unclassified row, lets it call tools
until it submits a finding (or hits the step limit), and returns:
    root cause, evidence, confidence, tool trace, tokens, time.
"""
import json, os, time
import httpx
from google import genai
from google.genai import types, errors
from agent.prompts import PROMPTS
from agent.tools import (get_recon_row, get_outbound_postings, check_reference_code,
                         get_treaty_terms, search_treaty)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")                    # main model (set in .env)
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")  # lighter backup
MAX_STEPS = 6
RETRY_WAITS = [5, 15]   # seconds to wait between retries on each model when Gemini is busy
RETRYABLE = (429, 500, 503, 504)   # rate limit, server error, busy, too slow
THINKING = os.getenv("GEMINI_THINKING", "LOW")   # how much the model thinks before answering

ROOT_CAUSES = ["Company code not mapped", "Timing difference", "Variance just beyond tolerance",
               "Treaty amendment not reflected", "Duplicate posting", "Needs analyst"]

# ------------------------------------------------------------------
# 1. System prompt: chosen by version (see agent/prompts.py)
# ------------------------------------------------------------------
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v2")
SYSTEM_PROMPT = PROMPTS[PROMPT_VERSION]
GUARDRAILS = os.getenv("GUARDRAILS", "on") == "on"

# ------------------------------------------------------------------
# 2. Tool menu: what the LLM reads to decide which tool to call
#    Every tool gets an extra "why" argument so we can see its reasoning.
# ------------------------------------------------------------------
S = types.Schema
WHY = S(type="STRING", description="One sentence: why you are calling this tool")

def declare(name, description, props, required):
    return types.FunctionDeclaration(
        name=name, description=description,
        parameters=S(type="OBJECT", properties={**props, "why": WHY}, required=required + ["why"]))

DECLARATIONS = [
    declare("get_outbound_postings",
            "List every outbound posting for a transaction across ALL cycles (this and later). "
            "Use to detect postings in a later cycle or multiple postings.",
            {"txn_id": S(type="STRING")}, ["txn_id"]),
    declare("check_reference_code",
            "Check whether a company code exists in the valid reference table. "
            "If not, returns valid codes that differ by one digit (likely typos).",
            {"code": S(type="STRING")}, ["code"]),
    declare("get_treaty_terms",
            "Get the treaty setup as held in SRM: share %, contract start/end, ceding company.",
            {"treaty_id": S(type="STRING")}, ["treaty_id"]),
    declare("search_treaty",
            "Search the treaty DOCUMENT text and return the 3 most relevant clauses, "
            "including endorsements. Write a short keyword query, e.g. 'reinsurer share amendment'.",
            {"treaty_id": S(type="STRING"), "query": S(type="STRING")}, ["treaty_id", "query"]),
    declare("submit_finding",
            "Submit your final conclusion. Call exactly once, when you are done investigating.",
            {"root_cause": S(type="STRING", enum=ROOT_CAUSES),
             "evidence": S(type="STRING", description="Specific facts from tool results"),
             "confidence": S(type="STRING", enum=["high", "medium", "low"])},
            ["root_cause", "evidence", "confidence"]),
]

FUNCTIONS = {"get_outbound_postings": get_outbound_postings, "check_reference_code": check_reference_code,
             "get_treaty_terms": get_treaty_terms, "search_treaty": search_treaty}

CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=DECLARATIONS)],
    # mode ANY = the model must call a tool every turn (an investigation tool or submit_finding),
    # so the final answer always arrives in a fixed structure
    tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
    # no temperature: Gemini 3.x models removed sampling parameters
    thinking_config=types.ThinkingConfig(thinking_level=THINKING),   # LOW = faster, cheaper
)

# ------------------------------------------------------------------
# 3a. Gemini client: no hidden library retries, 60s timeout per call,
#     so OUR retry/fallback logic (call_llm) is in control
# ------------------------------------------------------------------
def make_client():
    return genai.Client(http_options=types.HttpOptions(        # reads GEMINI_API_KEY
        timeout=120_000,                                         # milliseconds (2 min)
        retry_options=types.HttpRetryOptions(attempts=1)))       # 1 attempt = no library retries

# ------------------------------------------------------------------
# 3b. Calling Gemini, with retry when the service is busy
# ------------------------------------------------------------------
def call_llm(client, contents, log=print, sleep=time.sleep):
    """Call Gemini. If busy (503) or rate-limited (429): wait and retry,
    then switch to the lighter fallback model. Returns (response, model_used)."""
    for model in [MODEL, FALLBACK_MODEL]:
        for attempt, wait in enumerate(RETRY_WAITS + [None], start=1):
            try:
                return client.models.generate_content(model=model, contents=contents, config=CONFIG), model
            except (errors.APIError, httpx.TimeoutException) as e:
                code = getattr(e, "code", "timeout")
                if code != "timeout" and code not in RETRYABLE:
                    raise                                   # other errors (e.g. bad key): stop
                if wait is None:
                    break                                   # out of retries on this model
                log(f"   {model} busy ({code}), retry {attempt} in {wait}s...")
                sleep(wait)
        if model == MODEL:
            log(f"   switching to fallback model {FALLBACK_MODEL}")
    raise RuntimeError("Both models busy. Try again later.")

# ------------------------------------------------------------------
# 4. Guardrail: a code check on the LLM's answer (doesn't rely on the prompt)
# ------------------------------------------------------------------
def check_finding(root_cause, trace):
    """Return a reason to reject the finding, or None if it passes."""
    if root_cause == "Treaty amendment not reflected":
        sections = [res["section"] for t in trace if t["tool"] == "search_treaty"
                    for res in t["result"].get("results", [])]
        if not any(sec.startswith(("Endorsement", "Amendment")) for sec in sections):
            return "amendment claimed, but no endorsement/amendment clause was retrieved"
    return None

# ------------------------------------------------------------------
# 5. The loop
# ------------------------------------------------------------------
def investigate(txn_id, client=None, verbose=True):
    client = client or make_client()
    row = get_recon_row(txn_id)                   # row data is given upfront, not via a tool
    contents = [types.Content(role="user", parts=[types.Part(
        text=f"Investigate this Unclassified row:\n{json.dumps(row, indent=2)}")])]
    trace, tokens_in, tokens_out, start, models_used = [], 0, 0, time.time(), set()
    log = print if verbose else (lambda *a, **k: None)
    log(f"\n=== txn {txn_id} | treaty {row.get('treaty_id')} | variance {row.get('variance')} ===")

    for step in range(1, MAX_STEPS + 1):
        response, model_used = call_llm(client, contents, log)
        models_used.add(model_used)
        usage = response.usage_metadata
        tokens_in += usage.prompt_token_count or 0
        tokens_out += (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)

        calls = response.function_calls or []
        if not calls:                                       # shouldn't happen with mode=ANY
            return _finish(txn_id, "Needs analyst", "Model gave no tool call", "low",
                           trace, tokens_in, tokens_out, start, log, models_used)

        contents.append(response.candidates[0].content)     # remember what it asked for
        results = []
        for call in calls:
            args = dict(call.args)
            why = args.pop("why", "")

            if call.name == "submit_finding":               # agent is done
                trace.append({"step": step, "tool": "submit_finding", "why": why})
                cause, evidence, conf = args.get("root_cause"), args.get("evidence"), args.get("confidence")
                problem = check_finding(cause, trace) if GUARDRAILS else None
                if problem:                                 # guardrail overrides the LLM
                    log(f"   GUARDRAIL: {problem} -> Needs analyst")
                    evidence = f"[Guardrail: {problem}; agent said '{cause}'] {evidence}"
                    cause, conf = "Needs analyst", "low"
                return _finish(txn_id, cause, evidence, conf, trace, tokens_in, tokens_out,
                               start, log, models_used, guardrail=problem)

            fn = FUNCTIONS.get(call.name)
            output = fn(**args) if fn else {"error": f"unknown tool {call.name}"}
            trace.append({"step": step, "tool": call.name, "args": args, "why": why, "result": output})
            log(f"Step {step}: {call.name}({args})\n   why: {why}\n   got: {json.dumps(output)[:300]}")
            results.append(types.Part.from_function_response(name=call.name, response=output))

        contents.append(types.Content(role="user", parts=results))  # send results back

    return _finish(txn_id, "Needs analyst", f"Step limit ({MAX_STEPS}) reached", "low",
                   trace, tokens_in, tokens_out, start, log, models_used)


def _finish(txn_id, root_cause, evidence, confidence, trace, tokens_in, tokens_out, start, log, models_used,
            guardrail=None):
    result = {"txn_id": str(txn_id), "root_cause": root_cause, "evidence": evidence,
              "confidence": confidence, "steps": len(trace), "tools_used": [t["tool"] for t in trace],
              "models": sorted(models_used), "prompt": PROMPT_VERSION, "guardrail": guardrail,
              "tokens_in": tokens_in, "tokens_out": tokens_out,
              "seconds": round(time.time() - start, 1), "trace": trace}
    log(f"FINDING: {root_cause} ({confidence})\n   evidence: {evidence}\n"
        f"   {result['steps']} steps, {tokens_in}+{tokens_out} tokens, {result['seconds']}s, model: {', '.join(result['models'])}")
    return result
