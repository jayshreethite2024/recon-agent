# Stage 2: Tools

**In one line:** we wrote 5 Python functions ("tools") that look up facts about an Unclassified row. The agent will call them in Stage 3. No AI yet.

## How the data flows
```
CSV files ──► DuckDB (SQL tables) ──► tools 1–4 ──┐
                                                    ├──► TOOLS dict ──► agent (Stage 3)
treaty .txt files ──► tool 5 (split → score → top 3) ┘
```

## Files
| File | What it does |
|---|---|
| `agent/tools.py` | The 5 tools + the TOOLS dict |
| `tests/test_tools.py` | Checks each tool returns the right evidence |
| `requirements.txt` | Libraries to install: `duckdb`, `google-genai` |

## Code map: what happens where (`agent/tools.py`)

**Tool vs helper:** a *tool* is a function the agent can call (it's in the `TOOLS` dict). A *helper* (name starts with `_`) is used inside tools; the agent never sees it. `_rows` and `_chunk_treaty` are helpers.

| What happens | Function | Lines | In plain words |
|---|---|---|---|
| Load CSVs as SQL tables | (top of file) | 13–17 | DuckDB opens every CSV as a table you can query with SQL. `all_varchar=true` reads everything as text, so codes like 7310 stay labels. |
| Run SQL, return rows | `_rows` | 21–25 | Helper: sends a SQL string to DuckDB and turns the result into a list of dicts. Every SQL tool uses it. |
| Tool 1: the row | `get_recon_row` | 31–41 | SQL **JOIN** of `recon_result` and `inbound` on txn_id. Returns variance, code, treaty, policy date, gross. |
| Tool 2: postings | `get_outbound_postings` | 45–50 | SQL on `outbound` for **all cycles**. Shows next-cycle postings (timing) and double postings (duplicate). |
| Tool 3: code check | `check_reference_code` | 55–63 | SQL reads valid codes. **Python** (line 59) finds valid codes that differ by exactly 1 digit, i.e. likely typos. |
| Tool 4: SRM treaty setup | `get_treaty_terms` | 68–72 | SQL on `treaty_report`. Returns share %, contract dates. |
| Tool 5, step 1: **split treaty into clauses** | `_chunk_treaty` (helper) | 77–84 | Reads the .txt file. **Line 82** cuts the text at each line starting `Article N:` or `Endorsement No.`. Each piece becomes `{section, text}`. |
| Tool 5, step 2: **keyword search** | `search_treaty` | 94–99 | Line 95 breaks text into words and drops filler words (`STOPWORDS`, line 86). Line 94 shortens words to 5 letters, so "amended" and "amendment" match. **Line 99** scores each clause = number of matching words. |
| Tool 5, step 3: **ranking + top 3** | `search_treaty` | 102–103 | Line 102 sorts clauses by score, highest first. Line 103 keeps the top 3. |
| Tool lookup | `TOOLS` | 107–108 | A dict: tool name → function. The agent says a name; we find and run the function. |

## Code map: `tests/test_tools.py`
| What happens | Lines | In plain words |
|---|---|---|
| Read the answer key | 15 | Loads true root causes |
| Pick a sample row | 16 | `first("Duplicate posting")` returns the first txn with that cause |
| Check + print | 19–22 | Prints PASS/FAIL and counts passes |
| One block per root cause | rest | Call tools on that row, check the evidence is there |

## Which tool finds which root cause
| Root cause | Tools | Evidence |
|---|---|---|
| Company code not mapped | 1 → 3 | Code invalid, 1 digit off a valid code |
| Timing difference | 1 → 2 | Posted only in next cycle |
| Variance beyond tolerance | 1 | Variance $1–$4.50 |
| Treaty amendment | 1 → 4 → 5 | SRM 20%, endorsement says 15% |
| Duplicate posting | 1 → 2 | 2 postings |
| Needs analyst | all | Nothing explains it |

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| 5 narrow tools, not one "run any SQL" tool | Safe, reliable, auditable, easy to evaluate | Less flexible: new needs mean new tools |
| Removed the error/retention tool on review | The recon already checks error and retention before a row can be Unclassified, so the tool always returned "not found": a wasted call | Would need it back if error files arrive after recon |
| Tools return small dicts | Less for the LLM to read: cheaper, fewer mistakes | — |
| DuckDB on CSVs | Real SQL, zero setup; swaps for Databricks later | — |
| Codes read as text | Codes are labels; numbers would drop leading zeros | — |
| Near-match inside code check | One call gives "invalid" + "likely typo of X" | — |
| Split treaties by heading | Clauses stay whole | Needs consistent headings |
| Top 3, not top 1 | Ranking is imperfect; the LLM reads all 3 | More text sent to the LLM |
| Keyword search first | Works without an API key; gives a baseline | Matches words, not meaning |

## What testing caught
1. **Chunking bug (line 82):** the old rule split at *any* line starting "Article 4", including the endorsement sentence "Article 4 is amended…". This cut the endorsement's heading off its content. **Fix:** split only on `Article N:` (with the colon).
2. **Ranking limitation (line 99):** for "reinsurer share amendment", the original 20% clause scores 4 and the 15% endorsement scores 3, because the original uses "share" and "reinsurer" twice. Keyword search counts words; it doesn't know an endorsement overrides. **Mitigation:** top 3 + a prompt rule "endorsements override base terms" (Stage 3). **Future fix:** embeddings.

## Likely interview questions
| Question | Answer |
|---|---|
| Why not give the LLM a SQL tool? | Narrow tools are safer, cheaper and easier to evaluate and audit. |
| How did you test before adding the LLM? | Unit tests per root cause, so later failures point to reasoning, not data. |
| How does retrieval work? | Split treaty by clause headings → score clauses by matching words → return top 3. |
| Why top 3? | Testing showed the base clause outranks the endorsement; top 3 keeps the right one in view. |
| Did you remove anything? | Yes: an error/retention tool. It duplicated a check the recon already does, so it never added evidence. Every tool should add new information. |
| Why not embeddings? | Planned upgrade. Keyword search gave a baseline and needed no API key. |

---

## My study Q&A

**Where is SQL used if this is Python code?**
SQL runs *inside* Python via DuckDB. Lines 13–17 turn each CSV into a SQL table. Each tool writes a SQL string and `_rows` (line 21) sends it to DuckDB. Python wraps it as a function and returns a dict. Same idea as `spark.sql("SELECT ...")` in PySpark. Every tool uses SQL except `search_treaty`, which reads text files in Python.

**What is a dict?**
Python's label → value pairs, like one table row with column names: `{"txn_id": "10436", "company_code": "7311"}`. Read a value with `row["company_code"]`. Looks almost like JSON, which is why LLMs read it easily. A list of dicts = a table. Every tool returns a dict; `TOOLS` is a dict of name → function.

**What does `test_tools.py` do?**
Picks one row per root cause from the answer key, calls the tools on it, and checks the **evidence** appears (e.g. duplicate → `posting_count == 2`). It does **not** check the root cause label, because tools return facts, not conclusions.

| | Tests (Stage 2) | Evals (Stage 4) |
|---|---|---|
| Checks | Tools give the right facts | Agent reaches the right conclusion |
| Rows | 1 per root cause | All 50 |
| Compared with | Expected evidence | Answer key label |

Why test tools separately: if the agent is wrong later, we know it's reasoning, not bad data.

**Why was the error/retention tool removed?**
The recon already checks error and retention *before* a row can be Unclassified, so for every Unclassified row the tool returned "not found". It added no new evidence and wasted a step. Rule: every tool must add new information.

**How many tools: 5 or 6? Is splitting the treaty a tool?**
5 tools. A **tool** is something the agent can call (it's in `TOOLS`). A **helper** (name starts with `_`) is used inside a tool; the agent never sees it. Splitting, scoring and ranking all happen *inside* tool 5 (`search_treaty`); `_chunk_treaty` is its helper.

**Is splitting by clauses "chunking"?**
Yes. A chunk is a piece of a document about one thing. We chunk by clause heading (line 82), so each Article or Endorsement is one chunk.

**Which keyword from the recon report is used to search the treaty?**
None. The row gives only the `treaty_id` (which treaty to search). The **query text is written by the agent** based on what it suspects, e.g. variance ≈ 5% of gross and SRM says 20% → searches `"reinsurer share amendment"`. In tests we typed the query by hand.

**How does scoring and ranking work?** (query `"reinsurer share amendment"` on T003)
1. Break the query into words, shorten each to 5 letters: {reins, share, amend}
2. For each chunk, count words whose stem matches:

| Chunk | Matches | Score |
|---|---|---|
| Article 4: Reinsurer's Share (20%) | Reinsurer, Share, Reinsurers, share | 4 |
| Endorsement No. 1 (15%) | amended, Reinsurers, share | 3 |
| Article 1: Parties | Reinsurers | 1 |
| Articles 2, 3, 5 | none | 0, dropped |

3. Sort by score, keep the top 3 (lines 102–103).

Stemming matters: without it "amendment" wouldn't match "amended". Weakness: Article 4 wins only by repeating words; keyword search doesn't understand that an endorsement overrides.

**Will keyword search be replaced by embeddings?**
Not yet. Stage 3 keeps keyword search to get a **baseline**. In Stage 4: add embeddings, run the same evals, compare (does the endorsement rank #1? does amendment accuracy rise?). Likely end state is **hybrid**: embeddings match meaning ("share reduced" ≈ "participation changed"); keywords match exact terms (codes, "Article 4"). Interview story: "baseline → measured → improved from X% to Y%."

**How does the agent decide which tool to run?**
No if/else in our code. The LLM reads three things: the row, the tool menu (names + descriptions), and the system prompt. It picks the most sensible next step, like an analyst, then decides again after each result:
```
Sees outbound missing        → check_reference_code(7311)
Sees invalid, similar 7310   → final answer: Company code not mapped
```
We steer it through clear tool descriptions, the system prompt (e.g. "endorsements override base terms"), and fixing what evals show it gets wrong. Stage 3 will print each decision so it's visible.
