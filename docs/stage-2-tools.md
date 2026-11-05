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
