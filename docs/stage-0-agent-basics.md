# Stage 0: Agent basics

## What we built
`scripts/day1_agent.py`: a minimal agent with 2 tools (`check_reference_code`, `find_similar_codes`) that investigates one Unclassified row and returns a root cause, evidence and confidence.

## Key decisions and why
| Decision | Why |
|---|---|
| Plain Python + Gemini function calling, no framework | Every step is visible and explainable; a framework would hide the loop |
| Max 6 steps | Guardrail: the agent can't loop forever or burn cost |
| "Needs analyst" fallback | For a financial control, an honest "unsure" beats a confident guess |
| Tools return structured dicts | The LLM reads clean facts, not prose |

## Concepts
- **Agent = LLM + tools + loop.** The LLM decides; tools act; the loop lets it react to what it finds.
- **Function calling:** the LLM never runs code. It asks: "call `check_reference_code` with code=8424". Our code runs it and sends the result back.
- **The LLM only sees tool descriptions**, never the code. Clear descriptions mean it picks the right tool.
- **ReAct:** Reason, then Act, then Observe, then repeat.
- **No memory between calls:** we resend the full history (`contents`) every round.

## The 4 lines that are the agent
```python
response = client.models.generate_content(...)   # ask the LLM
if not response.function_calls: ...              # it's done
output = TOOLS[call.name](**call.args)           # our code runs the tool
contents.append(...)                             # add result to history
```

## Likely interview questions
| Question | Short answer |
|---|---|
| What makes it an agent, not a script? | The LLM chooses which tool to call next based on results; the path changes per row. |
| Who executes the tools? | Our code. The LLM only requests a call with arguments. |
| How do you stop runaway loops? | Step limit, then fall back to "Needs analyst". |
| Why no LangChain/LangGraph? | A simple, single-agent loop doesn't need one; plain code is easier to debug and audit. I'd consider LangGraph for complex branching or multi-agent flows. |
| How does it remember earlier steps? | It doesn't; we resend the conversation history each call. |

## Interview one-liner
"The LLM is the decision-maker, the tools are the hands, and the loop is what lets it act on what it finds."
