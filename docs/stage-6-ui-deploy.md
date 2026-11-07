# Stage 6: UI, README and deployment

**In one line:** a Streamlit app where you pick an Unclassified row, watch the agent investigate step by step, and accept or correct its finding; plus a README and a public deployment.

## What the app shows
| Tab | What's there |
|---|---|
| **Investigate** | The 50 Unclassified rows → pick one → **Investigate** → root cause, confidence, evidence, every tool call with its "why" → **Accept** or **Correct** |
| **Eval results** | v1 vs v2 table and the latest full eval report |
| **How it works** | 6-step explanation + architecture diagram |
| Sidebar | What it is, model / prompt / tool source, runs used this session, **demo mode** toggle |

## Files
| File | What it does |
|---|---|
| `app.py` | The Streamlit app |
| `README.md` | Project front page on GitHub: problem, results, decisions, how to run |
| `.streamlit/secrets.toml.example` | Which secrets to set on Streamlit Cloud (the real file is never committed) |
| `requirements.txt` | Now includes `streamlit` (Streamlit Cloud installs from this) |

## Code map: `app.py`
| What happens | Lines | In plain words |
|---|---|---|
| Load settings | 14–20 | On the cloud: copies Streamlit **Secrets** into the environment. Locally: reads `.env`. The agent code reads both the same way |
| Session limit | 25 | Max 15 investigations per visitor session: protects your API key and free quota on a public link |
| Load the rows | 32–37 | Reads the 50 Unclassified rows and the answer key; shuffles the order (line 34) so the planted causes aren't in blocks |
| Remember things | 40–42 | `session_state` keeps findings, analyst reviews and the run count while you click around |
| Sidebar | 46–55 | Description, settings, run count, demo-mode toggle |
| Tabs | 57 | Investigate / Eval results / How it works |
| Row table | 75 | All rows with the agent's finding and analyst decision once available |
| Pick a row | 77 | Dropdown of rows |
| **Run the agent** | 88–95 | Calls the same `investigate()` as the scripts; shows an error message (not a crash) if Gemini is busy |
| **Finding card** | 97–113 | Root cause, coloured confidence, evidence, guardrail warning if it fired, tokens/time/model, true cause in demo mode |
| **Steps** | 115–122 | Each tool call in an expander: arguments, why, result |
| **Analyst review** | 124–135 | Accept, or pick the correct cause and save. The analyst's decision is final |
| Eval tab | 138 | Results table + latest report from `results/` |
| How-it-works tab | 158 | Steps + diagram |

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Streamlit | All Python; you used it before; free hosting | Less design control than a web framework |
| Show every step with its "why" | Trust: analysts and interviewers can see *how* it reached the answer | More screen space |
| Accept / Correct buttons | Human-in-the-loop is the product: the agent suggests, the analyst decides | Reviews are kept for the session only (no database in the demo) |
| Demo mode (show true cause) | Lets a viewer check the agent against the answer key | Off by default, so the default view is realistic |
| 15 runs per session | A public link with your key could burn your quota | A visitor who wants more must refresh |
| Friendly error on API failure | Gemini can be busy; the app shouldn't crash in a demo | — |
| Local tools in the app (not MCP) | Fewer moving parts on the cloud host; MCP is proven by its eval | Set `TOOL_SOURCE=mcp` in Secrets to use MCP |
| Secrets in Streamlit Cloud, not the repo | The key never touches GitHub | — |

## Deploy on Streamlit Community Cloud (free)
1. Push everything to GitHub (repo must be public, or connect your private repo).
2. Go to **share.streamlit.io** → sign in with GitHub → **Create app** → **Deploy a public app from GitHub**.
3. Repository: `jayshreethite2024/recon-agent` · Branch: `main` · Main file: `app.py`.
4. **Advanced settings** → Python version **3.12** → **Secrets**: paste
   ```
   GEMINI_API_KEY = "your-key"
   GEMINI_MODEL = "gemini-3.5-flash-lite"
   ```
5. **Deploy**. You get a public link like `recon-agent-xxxx.streamlit.app`. Put it in the README and on your resume.

## Likely interview questions
| Question | Answer |
|---|---|
| Who is the user? | A recon analyst who clears Unclassified rows each cycle. The app gives them a pre-investigated suggestion with evidence instead of a blank row. |
| Why show the steps? | Trust and auditability. For a financial control, "why" matters as much as "what". |
| What happens to Accept/Correct? | In the demo, kept for the session. In production: saved to a table, used as labels (to monitor accept rate, retrain, train a cheaper ML model). |
| How do you protect the API key on a public demo? | Key in platform secrets, never in code; a per-session run limit. |
| What would you measure in production? | Accept rate, correction rate per cause, time per row before vs after, % escalated to "Needs analyst", cost per row. |
