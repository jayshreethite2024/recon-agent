# Stage 4: Evals

**In one line:** we run the agent on all 50 Unclassified rows, compare each answer with the answer key, and measure accuracy, safety, efficiency and cost.

## How the data flows
```
answer_key.csv (50 rows + true cause)
      │ shuffle
      ▼
for each row:  investigate(txn) ──► agent's answer + tools used + tokens + time
      │                                     │
      └──────── compare with true cause ◄───┘
                        │
                        ▼
           results/eval_<time>.csv    (one row per txn, open in Excel)
           results/eval_<time>.md     (summary report)
           results/traces_<time>.jsonl (every tool call, for debugging)
```

## Files
| File | What it does |
|---|---|
| `scripts/run_evals.py` | Runs the evals and writes the reports |
| `results/` | Eval outputs (created on first run). Commit the `.md` reports: they're your evidence |

## Code map: `scripts/run_evals.py`
| What happens | Where | Lines | In plain words |
|---|---|---|---|
| Expected tools per cause | `REQUIRED_TOOLS` | 26 | Which tool must be used to *justify* each cause, e.g. an amendment answer must have searched the treaty. Catches right answers for the wrong reasons |
| Fewest steps needed | `MIN_STEPS` | 34 | Minimum tool calls per cause. More = "extra steps" (over-investigation) |
| **Run all rows** | `evaluate` | 38–57 | Calls the agent on each row, marks correct/wrong, checks tools used, counts extra steps |
| Don't crash on one bad row | line 45 | 45 | If a row errors, it's recorded as ERROR and the run continues |
| Mark the result | line 50 | 50 | Adds: true cause, correct?, number of tool calls, used required tools?, extra steps |
| **Build the report** | `summarise` | 59–110 | Calculates all metrics below |
| Save files | `save` | 113 | Writes the CSV, report and traces into `results/` |
| Mix the order | line 135 | 135 | Shuffles rows (fixed seed) so `--limit 5` gets a mix of causes |
| Pause between rows | `--pause` | 132 | 2 seconds by default, to avoid rate limits |

## What we measure and why
| Section (report) | Metric | Why it matters |
|---|---|---|
| Headline (line 68) | **Accuracy** | The main number: % of rows with the right root cause |
| | Correct AND used the right tools | Right answer for the right reason, not a lucky guess |
| | Avg tool calls, rows with extra steps | Efficiency: over-investigation costs time and tokens |
| | Avg tokens, avg seconds | Cost and speed per row |
| Safety (line 80) | Unclear rows sent to analyst | Does it admit uncertainty instead of guessing? |
| | Clear rows wrongly sent to analyst | Too cautious = less time saved |
| | **Wrong answers marked high confidence** | The worst failure for a financial control |
| Per root cause (line 86) | **Recall** = of real X, how many it found | Which causes it misses |
| | **Precision** = when it says X, how often it's right | Whether analysts can trust each label |
| Confidence (line 98) | Accuracy by high / medium / low | Calibration: "high" should really be more accurate |
| Mistakes (line 108) | True → predicted pairs | What gets confused, which points to the fix |

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Eval on all 50, not a sample | Every cause gets 9 tries; one lucky row doesn't skew it | Slower (~15–40 min) |
| Check tools used, not just the answer | A right answer without evidence isn't trustworthy | Need to define "required tools" per cause |
| Measure extra steps | The 5-row test showed over-investigation | "Minimum steps" is our judgement |
| Separate safety metrics | For a financial control, confidently wrong is worse than "unsure" | — |
| Precision AND recall per cause | Accuracy alone hides which cause fails and how | — |
| Record model used per row | Fallback rows (Flash-Lite) may differ from Flash | — |
| Keep going on errors | One API failure shouldn't waste a 30-minute run | Errors count as wrong |
| Baseline first, change prompt after | You can only prove an improvement against a measured baseline | — |
| Tested with a fake agent | Checks the report logic without API cost | — |

## Results

| Run | Model | Prompt | Accuracy | Unclear → analyst | Confidently wrong | Avg tool calls | Extra steps | Sec/row | Tokens/row |
|---|---|---|---|---|---|---|---|---|---|
| Quick check (5 rows) | 3.5 Flash-Lite | v1 | 5/5 | 1/1 | 0 | 3.0 | 60% | 13.9 | 4,638 + 235 |
| **Baseline (50 rows)** | 3.5 Flash-Lite | v1 | **48/50 = 96%** | 3/5 | **2** | 2.2 | 48% | 9.1 | 3,533 + 252 |
| **v2 + guardrail (50 rows)** | 3.5 Flash-Lite | v2 | **49/50 = 98%** | **5/5** | **0** | 1.8 | 40% | 7.7 | 3,912 + 271 |
| **v2 + guardrail, run 2** | 3.5 Flash-Lite | v2 | **50/50 = 100%** | **5/5** | **0** | 1.7 | 36% | 6.8 | 3,709 + 240 |
| **v2 combined (2 runs)** | | | **99/100 = 99%** | **10/10** | **0** | 1.75 | 38% | 7.3 | ~3,800 + 255 |
| **v2 via MCP (Stage 5)** | 3.5 Flash-Lite | v2 | **50/50 = 100%** | 5/5 | 0 | 1.8 | 36% | 7.5 | 4,190 + 288 |
| **v2 all 3 runs** | | | **149/150 = 99.3%** | **15/15** | **0** | | | | |

### Baseline per root cause
| Root cause | Rows | Recall | Precision | Avg tool calls | Min needed |
|---|---|---|---|---|---|
| Company code not mapped | 9 | 100% | 100% | 2.6 | 1 |
| Timing difference | 9 | 100% | 100% | 1.0 | 1 |
| Variance just beyond tolerance | 9 | 100% | 100% | 2.6 | 0 |
| Treaty amendment not reflected | 9 | 100% | **82%** | 2.2 | 2 |
| Duplicate posting | 9 | 100% | 100% | 1.1 | 1 |
| Needs analyst | 5 | **60%** | 100% | 5.2 | 2 |

Confidence: 48 rows "high" (96% accurate), 2 rows "low" (100% accurate).
Mistakes: Needs analyst → Treaty amendment not reflected (2 rows: **10481, 10479**), both marked **high** confidence.

### What the baseline tells us
| Finding | What it means | Planned fix (v2) |
|---|---|---|
| All 5 clear causes found 100% | Tools + prompt work for clear cases | Keep |
| **2 unclear rows called "amendment", with high confidence** | When it can't explain a variance, it guesses "amendment" instead of admitting uncertainty. Precision for amendment drops to 82%. For a financial control, confidently wrong is the worst failure | Prompt rule: choose "amendment" only if a clause changes the share AND recalculating with the new share matches the actual amount. Otherwise "Needs analyst" |
| Confidence is almost always "high" | Confidence isn't meaningful yet: high was wrong twice | Define confidence in the prompt (high = numbers verified; low = evidence partial) |
| 48% of rows took extra steps | Over-investigation: e.g. small-variance rows used 2.6 tool calls when the variance alone is enough | Prompt rule: stop as soon as evidence is conclusive; a variance under $5 needs no tools |
| 9.1s, ~3,800 tokens per row | Fast and cheap enough for 50 rows per cycle | Fewer steps will cut both |

### Diagnosis: what the 2 wrong rows actually said
| Row | Agent's evidence (summary) | What went wrong |
|---|---|---|
| 10481 (T004) | "SRM and treaty both say 30%… actual implies 44.1%… **there are no treaty amendments or endorsements**" → labelled *amendment* | Evidence contradicts the label |
| 10479 (T004) | "Base terms and text show 30%… actual reflects 40% **without an endorsement**" → labelled *amendment* | Same |

**My hypothesis was wrong.** I expected it to be misled by T002's commission endorsement. Instead, the agent found *no* endorsement, said so, and still chose "amendment". It treated "posted share differs from documented share" as an amendment. It's a **reasoning** failure, not a retrieval failure. Lesson: read the failures before fixing; the fix would otherwise have targeted the wrong thing.

### v2: two layers of defence
| Layer | What | Where | Why |
|---|---|---|---|
| 1. Prompt (v2) | Strict amendment rule: needs an endorsement clause that changes the share **and** gross × new share = actual. "Different share with no endorsement = Needs analyst" | `agent/prompts.py`, `V2` | Fixes the reasoning at the source |
| | Self-check before submitting: does the evidence prove the label? | `V2` | Catches evidence/label contradictions like 10481 |
| | Confidence defined (high = proven + numbers checked) | `V2` | Baseline: "high" was used 48/50 times, including both errors |
| | Stop early when conclusive (e.g. variance under $5 needs no tools) | `V2` | Baseline: 48% extra steps |
| 2. Code guardrail | If the answer is "amendment" but no Endorsement/Amendment clause was ever retrieved → override to "Needs analyst", confidence low | `agent/agent.py`, `check_finding` (line 116), applied at line 158 | Prompts can be ignored; code can't. A deterministic check on the riskiest label |

**Versioning:** v1 and v2 prompts are both kept in `prompts.py`. Choose with `PROMPT_VERSION` in `.env`; switch guardrails off with `GUARDRAILS=off`. Every result records the prompt version and whether the guardrail fired, so runs can be compared fairly.

**Tests:** the fake-LLM test now checks the guardrail both ways: "amendment" without an endorsement is overridden; "amendment" with T003's endorsement is kept.

**Interview story:** "Baseline was 96%, but the two errors were the dangerous kind: unclear rows confidently labelled as amendments. Reading the traces showed the agent's own evidence said no endorsement existed, so it was a reasoning failure. I fixed it in two layers: a stricter prompt with a self-check, and a code guardrail that overrides an amendment label unless an endorsement was actually retrieved. Then I re-ran the same 50 rows to measure the change."

## Likely interview questions
| Question | Answer |
|---|---|
| How did you evaluate the agent? | 50 rows with known root causes; measured accuracy, precision/recall per cause, safety, steps, tokens and time. |
| Why is accuracy not enough? | It hides which causes fail, whether answers were justified by the right evidence, and whether wrong answers were confident. |
| What's the most important metric for a financial control? | Wrong answers with high confidence. "Needs analyst" is safe; confidently wrong is not. |
| Precision vs recall? | Precision: when it says "duplicate", is it right? Recall: of all real duplicates, how many did it find? |
| How do you know an improvement is real? | Same 50 rows, same metrics, before vs after. Run more than once because answers vary slightly. |

---

## My study Q&A

**The quick check was 5/5. Why run all 50?**
5 rows can't show patterns. The full run revealed the 2 confidently-wrong answers and the 48% extra-steps rate that the 5-row check missed or under-sampled.

**Accuracy is 96%. Why isn't that good enough?**
Because of *which* answers were wrong. Both errors were unclear rows labelled "amendment" with high confidence. An analyst trusting a high-confidence label would accept a wrong cause. "Needs analyst" would have been safe.

**Why does the "Needs analyst" row use so many tool calls (5.2 average)?**
To conclude "nothing explains this", the agent has to rule things out: check postings, code, treaty terms, treaty text. More checks are expected here. But check whether a row hit the 6-step limit: then "Needs analyst" came from running out of steps, not judgement (`evidence` would say "Step limit (6) reached").

**What do precision and recall mean in this report?**
Recall: of the 9 real amendments, how many did it find? (100%). Precision: of the 11 times it *said* amendment, how many were right? (9/11 = 82%). Recall says "does it miss things"; precision says "can analysts trust the label".

**What is "confidence vs accuracy" (calibration)?**
Whether "high" really means more likely correct. Here 48/50 were "high", including both mistakes, so the confidence label doesn't help analysts prioritise yet.

**Why not fix the prompt right away?**
You can only prove an improvement against a measured baseline, and you should understand *why* failures happen before changing things. Otherwise you might fix the wrong thing.

**Housekeeping: Git committed `__pycache__`.**
Python's temporary files shouldn't be on GitHub. Fix: add `__pycache__/` to `.gitignore`, then `git rm -r --cached agent/__pycache__ tests/__pycache__` and commit.

**What did the evidence for the 2 wrong rows show?**
Both said there was no endorsement, then labelled the row "amendment" anyway. So it wasn't misled by the T002 commission endorsement (my guess); it misread what "amendment" means. Always read failures before fixing.

**Why fix it in both the prompt and the code?**
The prompt fixes the reasoning, but an LLM can still ignore instructions. The guardrail is a deterministic check on the riskiest label: no retrieved endorsement, no "amendment". Defence in depth, the same idea as controls in finance.

**Could the guardrail hurt real amendments?**
Only if the agent labels an amendment without having searched the treaty, which is also a bad answer. Evals will show it: watch the amendment recall and the "Guardrail overrides" count.

**Why keep v1 in the code?**
To compare v1 and v2 on the same 50 rows and prove the improvement. You can re-run v1 any time with `PROMPT_VERSION=v1`.

---

## v2 results vs baseline

| Metric | Baseline (v1) | v2 + guardrail | Change |
|---|---|---|---|
| Accuracy | 96% (48/50) | **98% (49/50)** | +2 pts |
| Unclear rows sent to analyst | 3/5 | **5/5** | Fixed |
| **Wrong answers with high confidence** | **2** | **0** | **Fixed: the key safety metric** |
| Amendment precision | 82% | **100%** | Fixed |
| Confidence meaningful? | "high" 48×, incl. both errors | "high" 49× all correct; the 1 error was "medium" | Now calibrated |
| Avg tool calls | 2.2 | 1.8 | −18% |
| Rows with extra steps | 48% | 40% | Better, still room |
| Small-variance tool calls | 2.6 | 0.7 | Mostly stops early now |
| Seconds per row | 9.1 | 7.7 | −15% |
| Input tokens per row | 3,533 | 3,912 | +11% (longer prompt) |
| Guardrail overrides | n/a | 0 | Prompt alone fixed it; guardrail is the safety net |

**The one remaining mistake:** row 10436, a "Company code not mapped" case, sent to "Needs analyst" with **medium** confidence. That's a *safe* failure: the analyst checks it, nothing wrong gets accepted. Recall for code-not-mapped is 89%.

**Trade-off made:** v2 traded a slightly longer prompt (+11% input tokens) for zero confidently-wrong answers and fewer steps. For a financial control, that's the right trade.

**What's still open:**
1. Run v2 again: answers vary a little between runs (no temperature setting), so one run isn't proof of stability.
2. 40% of rows still take extra steps, mostly code-not-mapped (2.7 calls vs 1 needed) and amendments (2.6 vs 2).
3. Check row 10436's evidence to see why it held back.

**Updated interview story:** "Baseline was 96%, but both errors were confidently wrong amendment labels. Traces showed the agent's own evidence said no endorsement existed. I added a stricter prompt with a self-check and confidence definitions, plus a code guardrail. On the same 50 rows: 98% accuracy, zero confidently-wrong answers (from 2), all 5 unclear rows correctly escalated, 18% fewer tool calls. The one remaining miss was escalated to an analyst with medium confidence: a safe failure."

**Q: The guardrail never fired. Was it useless?**
No. It's a safety net: the prompt fixed the behaviour this time, but prompts can be ignored on other runs, models or data. Zero overrides is the outcome you want; it proves the prompt worked and the net is there if it doesn't.

**Q: Accuracy only went up 2 points. Why is v2 a big improvement?**
Because the *kind* of error changed. Before: 2 confident wrong labels an analyst might accept. After: 1 cautious "please check" with medium confidence. The risk went from "wrong answer accepted" to "a few extra minutes of analyst time".

**Q: Why did input tokens go up?**
The v2 prompt is longer and is sent on every call. Partly offset by fewer tool calls. A small cost for removing the dangerous errors.

---

## Stability check: v2 run 2

| Metric | v2 run 1 | v2 run 2 | Combined |
|---|---|---|---|
| Accuracy | 98% (49/50) | 100% (50/50) | **99% (99/100)** |
| Unclear rows sent to analyst | 5/5 | 5/5 | **10/10** |
| Confidently wrong | 0 | 0 | **0 in 100** |
| Avg tool calls | 1.8 | 1.7 | 1.75 |
| Small-variance tool calls | 0.7 | 0.2 | |
| Seconds per row | 7.7 | 6.8 | 7.3 |

**Row 10436 flipped:** wrong ("Needs analyst", medium) in run 1, correct in run 2. That's run-to-run variance: the model isn't fully deterministic (no temperature setting on Gemini 3.x). This is exactly why we ran twice: one run can over- or under-state accuracy.

**Honest way to state the result:** "99% across two runs of 50 cases (98% and 100%), zero confidently-wrong answers in 100 investigations, every unclear case escalated." Not "100% accurate".

**Caveats to state before an interviewer does:**
- Synthetic data with 5 seeded causes and a known answer key. Real data is messier: multiple causes per row, causes we didn't list.
- 50 cases is small. 9 per cause means one error moves recall by 11 points.
- The real proof would be running on anonymised real exceptions with analyst labels.

**Small open item:** in run 2 every row, including the 5 "Needs analyst" rows, was marked "high" confidence, although v2 says to use "low" with "Needs analyst". The agent reads "high" as "highly confident this needs an analyst". Not dangerous, but confidence is less informative again. Possible fix later: drop confidence for "Needs analyst", or define it as "confidence in the root cause".

**Q: The second run got 100%. Why not just report 100%?**
Because the two runs differ, and the honest number covers both. Reporting your best run is cherry-picking; interviewers who know evals will ask how many times you ran it.

**Q: Why did row 10436 change between runs?**
LLM outputs vary slightly from run to run. For a borderline case (it took 4 tool calls and in run 1 decided the evidence wasn't strong enough), that variation can flip the answer. That's why we measure over multiple runs, and why the "Needs analyst" safety net matters.

**Q: Is the agent "done"?**
For this dataset, yes: accuracy and safety are where they need to be. Remaining improvements are efficiency (36–40% of rows still take extra steps) and testing on harder, messier data.

---

## Decision: embeddings (planned, then skipped based on evals)
**Plan (Stage 2/4):** keep keyword search as a baseline; add embeddings if evals showed retrieval was weak.
**What evals showed:** amendment recall 100% with keyword search in both v2 runs. The only serious failure (confidently wrong amendments) was **reasoning**, fixed by the v2 prompt and guardrail, not retrieval.
**Decision:** don't add embeddings now. They'd add an API dependency, cost and code with no measurable gain on this data.
**When I'd add them:** real treaties (long, paraphrased wording, many endorsements). I'd use hybrid search (keywords for exact terms and codes, embeddings for meaning) and evaluate retrieval separately: "is the right clause in the top 3?"

**Q: Why didn't you use embeddings? Isn't that standard RAG?**
"I planned it as a measured upgrade. Evals showed keyword retrieval already found 100% of amendment clauses; the failures were in reasoning, so I fixed that instead. I don't add complexity that doesn't move the numbers. On real treaties I'd add hybrid search and evaluate retrieval on its own."
