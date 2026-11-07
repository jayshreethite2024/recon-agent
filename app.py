"""
Stage 6: Streamlit UI for the Recon Exception Investigator.

Run locally:   streamlit run app.py
Deployed on Streamlit Community Cloud: the API key comes from the app's Secrets.
"""
import csv, os, glob, random
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent

# --- settings: Streamlit secrets (cloud) or .env (local) -------------------------
try:
    for k, v in st.secrets.items():                 # cloud: copy secrets into the environment
        os.environ.setdefault(k, str(v))
except Exception:
    pass                                            # no secrets file locally: that's fine
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from agent.agent import investigate, ROOT_CAUSES, MODEL, PROMPT_VERSION, TOOL_SOURCE
from agent.tools import get_recon_row

MAX_RUNS = int(os.getenv("MAX_RUNS_PER_SESSION", "15"))   # protects the API key on a public demo

st.set_page_config(page_title="Recon Exception Investigator", page_icon="🔎", layout="wide")


# --- data ------------------------------------------------------------------
@st.cache_data
def load_rows():
    recon = [r for r in csv.DictReader(open(ROOT / "data" / "recon_result.csv")) if r["comment"] == "Unclassified"]
    random.Random(3).shuffle(recon)                 # mix causes so the demo list has no pattern
    truth = {r["txn_id"]: r["true_root_cause"] for r in csv.DictReader(open(ROOT / "data" / "answer_key.csv"))}
    return recon, truth

rows, truth = load_rows()
state = st.session_state
state.setdefault("findings", {})     # txn -> agent result
state.setdefault("reviews", {})      # txn -> analyst decision
state.setdefault("runs", 0)


# --- sidebar ---------------------------------------------------------------
with st.sidebar:
    st.title("🔎 Recon Investigator")
    st.caption("An AI agent that investigates Unclassified reinsurance reconciliation exceptions "
               "and suggests a root cause with evidence. An analyst approves or corrects it.")
    st.markdown("**Synthetic data only.** No client data.")
    st.divider()
    st.markdown(f"**Model:** `{MODEL}`  \n**Prompt:** `{PROMPT_VERSION}`  \n**Tools:** `{TOOL_SOURCE}`")
    st.markdown(f"**Investigations this session:** {state.runs}/{MAX_RUNS}")
    show_truth = st.toggle("Demo mode: show true root cause", value=False,
                           help="Reveals the answer key, to check the agent's answer.")

tab_inv, tab_eval, tab_how = st.tabs(["Investigate", "Eval results", "How it works"])


# --- tab 1: investigate ----------------------------------------------------
with tab_inv:
    st.subheader("Unclassified rows from this recon cycle")
    reviewed = len(state.reviews)
    c1, c2, c3 = st.columns(3)
    c1.metric("Unclassified rows", len(rows))
    c2.metric("Investigated", len(state.findings))
    c3.metric("Reviewed by analyst", reviewed)

    table = [{"txn_id": r["txn_id"], "treaty": r["treaty_id"], "company code": r["company_code"],
              "expected": float(r["expected_amount"]), "actual": float(r["actual_amount"]),
              "variance": float(r["variance"]),
              "agent finding": state.findings.get(r["txn_id"], {}).get("root_cause", ""),
              "analyst": state.reviews.get(r["txn_id"], {}).get("decision", "")}
             for r in rows]
    st.dataframe(table, hide_index=True, width="stretch", height=260)

    txn = st.selectbox("Pick a row to investigate", [r["txn_id"] for r in rows],
                       format_func=lambda t: f"{t}  (variance {get_recon_row(t)['variance']})")

    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Row data**")
        st.json(get_recon_row(txn), expanded=True)
        run = st.button("🔎 Investigate", type="primary", disabled=state.runs >= MAX_RUNS)
        if state.runs >= MAX_RUNS:
            st.info("Session limit reached (protects the demo's API quota). Refresh to start a new session.")

    if run:
        with st.spinner("Agent is investigating…"):
            try:
                state.findings[txn] = investigate(txn, verbose=False)
                state.runs += 1
            except Exception as e:
                st.error(f"Investigation failed: {e}. The model may be busy; try again in a minute.")

    result = state.findings.get(txn)
    with right:
        if result:
            conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(result["confidence"], "⚪")
            st.markdown(f"### {result['root_cause']}")
            st.markdown(f"{conf_icon} Confidence: **{result['confidence']}**")
            st.markdown(f"**Evidence:** {result['evidence']}")
            if result.get("guardrail"):
                st.warning(f"Guardrail applied: {result['guardrail']}")
            st.caption(f"{len([t for t in result['tools_used'] if t != 'submit_finding'])} tool calls · "
                       f"{result['tokens_in'] + result['tokens_out']:,} tokens · {result['seconds']}s · "
                       f"{', '.join(result['models'])}")
            if show_truth:
                ok = result["root_cause"] == truth.get(txn)
                (st.success if ok else st.error)(f"True root cause: {truth.get(txn)}")
        else:
            st.info("Pick a row and click **Investigate** to see the agent work.")

    if result:
        st.markdown("#### Investigation steps")
        for t in result["trace"]:
            if t["tool"] == "submit_finding":
                st.markdown(f"**Step {t['step']}: submit finding** — _{t['why']}_")
                continue
            with st.expander(f"Step {t['step']}: {t['tool']}({', '.join(f'{k}={v}' for k, v in t['args'].items())})"):
                st.markdown(f"_Why:_ {t['why']}")
                st.json(t["result"])

        st.markdown("#### Analyst review")
        st.caption("The agent never closes a row. The analyst's decision is final and becomes a label.")
        a, b = st.columns([1, 2])
        if a.button("✅ Accept finding"):
            state.reviews[txn] = {"decision": "Accepted", "root_cause": result["root_cause"]}
        corrected = b.selectbox("Or correct it to", ROOT_CAUSES, index=ROOT_CAUSES.index(result["root_cause"])
                                if result["root_cause"] in ROOT_CAUSES else 0, key=f"fix_{txn}")
        if b.button("✏️ Save correction"):
            state.reviews[txn] = {"decision": f"Corrected → {corrected}", "root_cause": corrected}
        if txn in state.reviews:
            st.success(f"Saved: {state.reviews[txn]['decision']}")


# --- tab 2: eval results ---------------------------------------------------
with tab_eval:
    st.subheader("How well does it work?")
    st.markdown("Tested on all 50 Unclassified rows against a known answer key.")
    st.table([
        {"Version": "v1 baseline", "Accuracy": "96%", "Unclear rows → analyst": "3/5",
         "Confidently wrong": "2", "Tool calls/row": "2.2", "Sec/row": "9.1"},
        {"Version": "v2 + guardrail (3 runs)", "Accuracy": "99.3% (149/150)", "Unclear rows → analyst": "15/15",
         "Confidently wrong": "0", "Tool calls/row": "1.8", "Sec/row": "7.3"},
    ])
    st.markdown("**What changed in v2:** the baseline's two errors were unclear rows confidently labelled "
                "*amendment*, even though the agent's own evidence said no endorsement existed. "
                "v2 adds a stricter prompt with a self-check and defined confidence, plus a code guardrail "
                "that rejects an *amendment* label unless an endorsement was actually retrieved.")
    reports = sorted(glob.glob(str(ROOT / "results" / "eval_*.md")))
    if reports:
        with st.expander(f"Latest full eval report ({Path(reports[-1]).name})"):
            st.markdown(Path(reports[-1]).read_text())


# --- tab 3: how it works ---------------------------------------------------
with tab_how:
    st.subheader("How it works")
    st.markdown("""
1. **Recon** leaves rows *Unclassified* when no rule explains a variance.
2. The **agent** (Gemini) gets the row, a job description and a menu of tools.
3. It **investigates**: checks postings across cycles, validates the company code,
   compares SRM's treaty setup with the treaty document.
4. It **submits** a root cause from a fixed list, with evidence and confidence,
   or *Needs analyst* when the evidence isn't conclusive.
5. A **guardrail** in code checks the riskiest label before it's shown.
6. An **analyst** accepts or corrects it. The agent never closes a row.

Tools are also served over **MCP**, so other AI apps can use the same tools.
""")
    img = ROOT / "docs" / "architecture.png"
    if img.exists():
        st.image(str(img), caption="Architecture", width="stretch")
