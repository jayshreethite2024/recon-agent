# Stage 3: The agent loop

**In one line:** we connected Gemini to our tools. For each Unclassified row, the LLM picks tools, reads the results, and submits a root cause with evidence and confidence.

## How the data flows
```
recon row (get_recon_row) ──► prompt to Gemini (row + system prompt + tool menu)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
         asks for a tool                  calls submit_finding
                    │                             │
       our code runs it (FUNCTIONS)        STOP → root cause, evidence,
                    │                       confidence, steps, tokens, time
      result added to history ──► back to Gemini (max 6 rounds)
```

## Files
| File | What it does |
|---|---|
| `agent/agent.py` | System prompt, tool menu, the loop (`investigate`) |
| `scripts/run_agent.py` | Runs the agent on 1 row or a sample; `--check` compares with the answer key |
| `tests/test_agent_loop.py` | Tests the loop with a scripted fake LLM (no API key) |
| `.env` (you create it, never committed) | `GEMINI_API_KEY=...` |

## Code map: `agent/agent.py`

| What happens | Where | Lines | In plain words |
|---|---|---|---|
| Settings | `MODEL`, `FALLBACK_MODEL`, `MAX_STEPS` | 14–16 | Main model (Flash), lighter backup (Flash-Lite), max 6 rounds. Both model names can be set in `.env` |
| Retry waits | `RETRY_WAITS` | 17 | Wait 5 then 15 seconds between retries on each model |
| Allowed answers | `ROOT_CAUSES` | 19 | The fixed list the agent must choose from |
| **Job description** | `SYSTEM_PROMPT` | 25 | Explains the recon, defines each root cause, sets rules: use evidence, endorsements override, never guess, fill "why" |
| Tool menu builder | `declare` | 54 | Builds one tool description and adds a required `why` argument to every tool |
| **Tool menu** | `DECLARATIONS` | 59 | 4 investigation tools + `submit_finding`. This is all the LLM sees about our tools |
| Name → function | `FUNCTIONS` | 83 | Which Python function runs for each tool name |
| Call settings | `CONFIG` | 86–92 | Prompt + menu; **mode ANY** (line 91) forces a tool call every turn |
| **Call Gemini with retry + fallback** | `call_llm` | 98–116 | Tries Flash. If busy (503) or rate-limited (429): wait 5s, retry, wait 15s, retry. Still busy → switch to Flash-Lite and do the same. Any other error stops the run. Returns the response and which model answered |
| **The loop** | `investigate` | 119 | Everything below happens here |
| Start with the row | line 121 | 121 | Row data goes straight into the first message, not via a tool |
| Ask Gemini | line 129 | 129 | Sends full history + menu |
| Count tokens | line 132 | 132–134 | Adds up input/output tokens for cost |
| Save its request | line 140 | 140 | Adds "I want to call X" to history |
| Take out "why" | line 144 | 144 | Keeps the reasoning for the trace; the Python function doesn't need it |
| **Done?** | line 146 | 146 | If it called `submit_finding`, stop and return the answer |
| **Run the tool** | line 152 | 152 | Our code runs the Python function |
| Send results back | line 157 | 157 | Adds results to history; loop goes round again |
| Safety stop | line 159 | 159 | After 6 rounds: "Needs analyst" |
| Package the result | `_finish` | 163 | Root cause, evidence, confidence, steps, tools used, **models used**, tokens, seconds, full trace |

## Code map: `scripts/run_agent.py`
| What happens | Lines | In plain words |
|---|---|---|
| Load API key | 17–18 | Reads `.env` |
| Pick rows | 29 | One txn, or a random sample of Unclassified rows (seeded, so same sample each time) |
| Load answer key | 31 | Only used with `--check` |
| Run + compare | 34–38 | Investigates each row; prints CORRECT/WRONG with `--check` |

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Row data given upfront, not via a tool | Every investigation needs it; a tool call would always be wasted (same lesson as the removed error/retention tool) | — |
| Final answer is a tool (`submit_finding`) | Forces a fixed structure: root cause must come from the list (`enum`), plus evidence and confidence. No messy text to parse | — |
| Mode ANY (must call a tool every turn) | Every turn is either investigating or submitting; no free-text drift | The agent can't "think out loud" between calls (solved by `why`) |
| Required `why` argument on every tool | Shows *why* it chose each tool: visible reasoning, an audit trail, and easier debugging | A few extra tokens per call |
| Fixed root cause list incl. "Needs analyst" | Measurable against the answer key; gives an honest way out instead of guessing | Can't name a new cause (future: "Other" + notes) |
| Max 6 steps | Stops runaway loops and cost | A hard case could need more |
| No temperature setting | Gemini 3.x models removed sampling parameters (temperature etc.); setting it would error | Answers can vary slightly between runs, so evals should be run more than once |
| Retry with backoff on 503/429 | LLM services get busy; a batch over 50 rows shouldn't crash on a temporary error. Waits grow (5s → 15s) so we don't hammer a busy service | Slower runs when busy |
| Fall back to Flash-Lite | Keeps the batch running when Flash is overloaded | Lite may reason less well; we record which model answered each row so evals compare fairly |
| Model name in `.env`, not code | Models get retired (2.5 Flash was, mid-build); swap without code changes | — |
| Track tokens and time | Cost and latency per row are eval metrics in Stage 4 | — |
| Fake-LLM test | Tests the loop logic and retry without API cost or randomness | Doesn't test the LLM's judgement (that's evals) |

## Likely interview questions
| Question | Answer |
|---|---|
| How does the agent decide which tool to call? | The LLM reads the row, the system prompt and tool descriptions, and picks the next step. Our code has no if/else for tool choice. |
| How do you get structured output? | The final answer is itself a tool (`submit_finding`) with an enum of allowed root causes. |
| How do you see its reasoning? | Every tool call has a required `why` field; the full trace is saved. |
| How do you stop it looping? | Max 6 steps, then "Needs analyst". |
| How do you control cost? | Narrow tools, row given upfront, step limit, token tracking per row. |
| How did you test without the LLM? | A scripted fake LLM checks the loop: history grows correctly, submit stops it, step limit works. |
| What if the LLM service fails? | Busy/rate-limit errors are retried with growing waits, then it falls back to a lighter model. Every result records which model answered. Model names are configurable because models get retired. |
| What does the human do? | Reviews the finding with its evidence and accepts or corrects it. The agent never closes a row. |

---

## My study Q&A

**Do I need to create the API key in AI Studio with a project?**
Yes: name it (e.g. recon-agent), keep "Default Gemini Project", create, copy. Save it in `.env` as `GEMINI_API_KEY=...`. `.env` is in `.gitignore`, so it never goes to GitHub.

**`echo ... > .env` showed no message. Did it work?**
Yes. No output means success. Use `>` to create/overwrite a file, `>>` to add a line to it.

**Is a key in a screenshot a risk if only I use my laptop?**
The laptop isn't the risk; the copy in chat history is. Low risk for a free-tier key (worst case: someone uses the quota). Habit for work: never share keys in screenshots; rotate if you do.

**Error: "404 model gemini-2.5-flash is no longer available".**
Google retired that model for new users. Fix without code changes: `echo "GEMINI_MODEL=gemini-3.8-flash" >> .env`. The 404 also proved the API key works (a bad key gives a different error).

**Error: "503 UNAVAILABLE, high demand".**
Gemini's servers were overloaded; temporary, not our code. Fixed properly by adding retry with backoff (`call_llm`): wait 5s, 15s, then switch to the lighter Flash-Lite model (same approach as MenuMate) and retry there too.

**Why fall back to Flash-Lite instead of just waiting?**
Same approach as MenuMate: when the main model is overloaded, a lighter model usually has capacity. Trade-off: Lite may reason less well, so each result records `models` used, and evals can check whether fallback rows are less accurate.

**Which fallback model, and why remove temperature?**
Google's release notes (Nov 2026): 2.5 Flash is deprecated and routes to `gemini-3.5-flash-lite`, so that's our fallback. The notes also say 3.x models removed sampling parameters, so `temperature=0` was taken out. Consequence: answers may vary a little between runs, so evals should be repeated.

**The run kept waiting and never moved forward. Why?**
Google's library has its own hidden retries. When Gemini was busy, it retried quietly for minutes before our code got control, so our fallback never kicked in. Fix: `make_client()` turns library retries off (`attempts=1`) and sets a 60-second timeout per call, so our `call_llm` decides when to retry and when to switch to Flash-Lite. Lesson: when you add your own retry logic, make sure a library underneath isn't also retrying.

**Error: "504 DEADLINE_EXCEEDED".**
Gemini took longer than our 60s limit to answer: overloaded, plus the model "thinks" before answering. Fixes: (1) 504 and 500 are now retried like 503, and timeouts too; (2) timeout raised to 2 minutes; (3) `thinking_level=LOW` so the model thinks less: faster and cheaper. Our task is simple enough not to need deep thinking; if accuracy suffers in evals we can raise it (set `GEMINI_THINKING=MEDIUM` in `.env`). This is a real trade-off to mention in interviews: latency and cost vs reasoning depth.
