"""Stage 3 test: checks the agent loop with a scripted fake LLM (no API key needed).
Run:  python3 tests/test_agent_loop.py"""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from google.genai import types
from agent.agent import investigate

def resp(name, args):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=40))

class FakeModels:
    def __init__(self, script): self.script, self.calls = script, []
    def generate_content(self, model, contents, config):
        self.calls.append(len(contents)); return self.script.pop(0)
class FakeClient:
    def __init__(self, script): self.models = FakeModels(script)

# scripted "LLM": check code, then submit
c = FakeClient([
    resp("check_reference_code", {"code": "7311", "why": "outbound missing; code may be invalid"}),
    resp("submit_finding", {"root_cause": "Company code not mapped", "evidence": "7311 invalid; 7310 valid",
                            "confidence": "high", "why": "enough evidence"})])
r = investigate("10436", client=c)
assert r["root_cause"] == "Company code not mapped" and r["steps"] == 2, r
assert c.models.calls == [1, 3], c.models.calls   # history grows: question, +request, +result
# step limit
c = FakeClient([resp("get_outbound_postings", {"txn_id": "10436", "why": "loop"}) for _ in range(6)])
r = investigate("10436", client=c, verbose=False)
assert r["root_cause"] == "Needs analyst" and "Step limit" in r["evidence"], r
# retry + fallback: main model busy 3 times (out of retries) -> switches to lighter model
from google.genai import errors
import agent.agent as A
busy = errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
class FlakyModels(FakeModels):
    def generate_content(self, model, contents, config):
        self.models_tried = getattr(self, "models_tried", []) + [model]
        if model == A.MODEL: raise busy
        return super().generate_content(model, contents, config)
fm = FlakyModels([resp("submit_finding", {"root_cause": "Duplicate posting", "evidence": "2 postings",
                                          "confidence": "high", "why": "done"})])
waits = []
out, used = A.call_llm(type("C", (), {"models": fm})(), [], log=lambda *a: None, sleep=waits.append)
assert waits == [5, 15] and used == A.FALLBACK_MODEL, (waits, used)
assert fm.models_tried == [A.MODEL] * 3 + [A.FALLBACK_MODEL], fm.models_tried
# 504 (too slow) is also retried
slow = errors.ServerError(504, {"error": {"code": 504, "message": "deadline", "status": "DEADLINE_EXCEEDED"}})
class SlowOnce(FakeModels):
    def generate_content(self, model, contents, config):
        if not getattr(self, "failed", False): self.failed = True; raise slow
        return super().generate_content(model, contents, config)
sm = SlowOnce([resp("submit_finding", {"root_cause": "Duplicate posting", "evidence": "x",
                                       "confidence": "high", "why": "done"})])
waits = []
out, used = A.call_llm(type("C", (), {"models": sm})(), [], log=lambda *a: None, sleep=waits.append)
assert waits == [5] and used == A.MODEL, (waits, used)
print("MOCK TESTS PASSED")
