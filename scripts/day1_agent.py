"""
Day 1: your first agent (about 70 lines).

Setup (run once in your terminal):
    pip install google-genai
    export GEMINI_API_KEY="your-key"     # free key: https://aistudio.google.com/apikey

Run:
    python day1_agent.py
"""
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"   # if this name errors, use the latest Flash model listed in AI Studio
MAX_STEPS = 6                # guardrail: the agent can't loop forever

# ---------------------------------------------------------------
# 1. TOOLS: plain Python functions (fake data for now)
# ---------------------------------------------------------------
VALID_CODES = {"8421": "Company A", "2290": "Company B", "5530": "Company C"}

def check_reference_code(code: str) -> dict:
    """Is this company code valid in the reference table?"""
    return {"code": code, "exists": code in VALID_CODES}

def find_similar_codes(code: str) -> dict:
    """Valid codes that differ from this one by a single digit (possible typos)."""
    similar = [c for c in VALID_CODES
               if len(c) == len(code) and sum(a != b for a, b in zip(c, code)) == 1]
    return {"code": code, "similar_valid_codes": similar}

TOOLS = {"check_reference_code": check_reference_code,
         "find_similar_codes": find_similar_codes}

# ---------------------------------------------------------------
# 2. TOOL DESCRIPTIONS: what the LLM reads to decide which tool to call
# ---------------------------------------------------------------
code_param = types.Schema(type="OBJECT",
                          properties={"code": types.Schema(type="STRING", description="4-digit company code")},
                          required=["code"])
declarations = [
    types.FunctionDeclaration(name="check_reference_code",
                              description="Check whether a company code exists in the valid reference table.",
                              parameters=code_param),
    types.FunctionDeclaration(name="find_similar_codes",
                              description="Find valid codes one digit away from a given code, to spot typos.",
                              parameters=code_param),
]
config = types.GenerateContentConfig(
    tools=[types.Tool(function_declarations=declarations)],
    system_instruction=("You investigate Unclassified reconciliation rows. Use the tools to gather evidence. "
                        "Finish with: root cause, evidence, confidence (high/medium/low). "
                        "If evidence is insufficient, say 'Needs analyst'."),
)

# ---------------------------------------------------------------
# 3. THE AGENT LOOP (ReAct): reason -> act (tool) -> observe -> repeat
# ---------------------------------------------------------------
client = genai.Client()   # reads GEMINI_API_KEY from the environment
question = "Row 10045 is Unclassified. Its company code is 8424. Why might it be unclassified?"
contents = [types.Content(role="user", parts=[types.Part(text=question)])]

for step in range(1, MAX_STEPS + 1):
    response = client.models.generate_content(model=MODEL, contents=contents, config=config)

    if not response.function_calls:                 # no tool requested -> final answer
        print(f"\nFINAL ANSWER (after {step - 1} tool rounds):\n{response.text}")
        break

    contents.append(response.candidates[0].content)  # keep the LLM's tool request in history
    results = []
    for call in response.function_calls:            # YOUR code runs the tool, not the LLM
        output = TOOLS[call.name](**call.args)
        print(f"Step {step}: {call.name}({dict(call.args)}) -> {output}")
        results.append(types.Part.from_function_response(name=call.name, response=output))
    contents.append(types.Content(role="user", parts=results))  # send results back
else:
    print("Stopped: step limit reached -> Needs analyst")
