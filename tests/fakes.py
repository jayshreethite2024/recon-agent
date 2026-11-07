"""Fake Gemini responses and client, shared by the tests (no API key needed)."""
from google.genai import types

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

