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
| v2 | | v2 | | | | | | | |

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

**Next step (before fixing):** read the `evidence` for rows 10481 and 10479 in `results/eval_….csv` to confirm *why* it said "amendment". Hypothesis: it found an endorsement (possibly T002's commission change, which doesn't affect ceded amounts) and didn't check the numbers. Rule: look at failures before changing anything.

**Interview story:** "Baseline was 96%, but the two errors were the dangerous kind: unclear rows confidently labelled as amendments. I traced the failures, tightened the prompt to require numeric verification, and re-ran the same 50 rows to measure the change."

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
