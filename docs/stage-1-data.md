# Stage 1: Synthetic data

## What we built
`scripts/generate_data.py` creates a fully synthetic reinsurance recon dataset (no client data): 492 transactions for cycle 2026-Q3-C1, 4 treaties with text documents, and a rule-based recon that leaves **50 Unclassified rows** with known root causes.

## Files (in `data/`)
| File | Holds |
|---|---|
| `inbound.csv` | Source transactions: treaty, company code, policy date, gross amount |
| `outbound.csv` | What SRM ceded, per cycle (includes next cycle C2) |
| `treaty_report.csv` | SRM's treaty setup: share %, contract period (T003 is stale on purpose) |
| `error.csv`, `retention.csv` | Rows SRM rejected or retained |
| `reference_codes.csv` | Valid company codes |
| `recon_result.csv` | Recon output: expected, actual, variance, rule-based comment |
| `treaties/T00X.txt` | Treaty documents with articles and endorsements |
| `answer_key.csv` | True root cause per Unclassified row. **Hidden from the agent; evals only.** |

## Recon logic (same as the real V1)
Expected = gross × participation %. Actual = outbound for this cycle. Match within $0.90. Rules: Present in Error → Retention → 0 $ → outside contract period → Exact Match → else **Unclassified**.

## Recon result
| Comment | Rows |
|---|---|
| Exact Match | 380 |
| Present in Error | 20 |
| Present in Retention | 15 |
| 0 $ transaction | 10 |
| Policy date outside contract period | 8 |
| **Unclassified** | **50** |

## Seeded root causes (what the agent must find)
| Root cause | Rows | Evidence the agent needs |
|---|---|---|
| Company code not mapped | 9 | Code not in reference table; one digit off a valid code |
| Timing difference | 9 | No outbound this cycle; present in next cycle |
| Variance just beyond tolerance | 9 | Variance $1 to $4.50 |
| Treaty amendment not reflected | 9 | T003 Endorsement 1 cut share 20% → 15% from 1 Jul; treaty report still says 20% (needs treaty search) |
| Duplicate posting | 9 | Two outbound rows for one transaction |
| Needs analyst | 5 | Unexplained variance, no supporting signal. Agent should NOT guess |

## Key decisions and why
| Decision | Why |
|---|---|
| Fully synthetic, invented names and codes | No client data or IP; safe to publish |
| Seeded causes with an answer key | Makes accuracy measurable: evals compare agent vs truth |
| Each cause needs different tools | Tests that the agent picks the right investigation path |
| "Needs analyst" cases included | Tests that the agent admits uncertainty instead of guessing |
| Distractor endorsement on T002 (commission change) | Tests that treaty search finds the *relevant* amendment, not any amendment |
| Fixed random seed | Same data every run, so eval results are comparable |

## Likely interview questions
| Question | Short answer |
|---|---|
| Why synthetic data? | Client data can't leave the environment. Synthetic data mirrors the real structure and failure patterns I see in recon. |
| How do you know it's realistic? | The five causes are patterns I've seen analysts resolve manually; structure mirrors inbound/outbound/error/retention/treaty report. |
| How will you measure the agent? | Each Unclassified row has a known root cause; evals score the agent's answer against it. |
| Why include unsolvable rows? | A good agent must say "needs analyst" rather than guess. That's a key safety metric for a financial control. |
| Limitation? | Real data is messier: multiple causes per row, unseen causes. Next step would be multi-label output and testing on anonymised real patterns. |
