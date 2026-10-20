"""Insightly web console (Streamlit). Talks to the API over HTTP; holds no secrets.

Run:  uv run --extra ui streamlit run ui/streamlit_app.py
Env:  INSIGHTLY_API_URL (default http://localhost:8000), INSIGHTLY_API_TOKEN (Cognito JWT)
"""

from __future__ import annotations

import json
import os

import httpx
import plotly.graph_objects as go
import streamlit as st

API = os.environ.get("INSIGHTLY_API_URL", "http://localhost:8000")
TOKEN = os.environ.get("INSIGHTLY_API_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

st.set_page_config(page_title="Insightly", page_icon=":bar_chart:", layout="wide")
st.title("Insightly")
st.caption("Ask a business question. Every answer shows the SQL and the metric definition used.")

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.thread_id = None
    st.session_state.pending = None

with st.sidebar:
    st.subheader("Session")
    if st.button("New conversation"):
        st.session_state.messages, st.session_state.thread_id = [], None
        st.session_state.pending = None
    try:
        spend = httpx.get(f"{API}/v1/cost/today", headers=HEADERS, timeout=5).json()
        st.metric(
            "Spent today", f"${spend['spent_usd']:.4f}", help=f"Daily budget ${spend['daily_budget_usd']:.2f}"
        )
    except Exception:
        st.warning(f"API not reachable at {API}")
    st.markdown(
        "**Try:**\n- Net revenue by category group in 2023\n- Plot monthly orders for "
        "2022\n- Return rate by distribution center\n- How are we doing?"
    )


def render(msg: dict) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        res = msg.get("result")
        if not res:
            return
        for h in res.get("highlights") or []:
            st.markdown(f"- {h}")
        if res.get("chart"):
            st.plotly_chart(go.Figure(res["chart"]), use_container_width=True)
        if res.get("rows"):
            st.dataframe(
                [dict(zip(res["columns"], r, strict=False)) for r in res["rows"][:200]],
                use_container_width=True,
            )
        if res.get("sql"):
            with st.expander("SQL and run details"):
                st.code(res["sql"], language="sql")
                cost = res.get("cost") or {}
                st.caption(
                    f"status={res.get('status')} attempts={res.get('attempts')} "
                    f"cost=${cost.get('total_usd', 0):.5f} cached={res.get('cached')} "
                    f"path={' > '.join(res.get('trace') or [])}"
                )
                c1, c2 = st.columns(2)
                if c1.button("👍 Correct", key=f"up-{msg['id']}"):
                    _feedback(res, "up")
                if c2.button("👎 Wrong", key=f"down-{msg['id']}"):
                    _feedback(res, "down")


def _feedback(res: dict, rating: str) -> None:
    httpx.post(
        f"{API}/v1/feedback",
        headers=HEADERS,
        timeout=10,
        json={
            "thread_id": res["thread_id"],
            "rating": rating,
            "question": res.get("question", ""),
            "sql": res.get("sql"),
        },
    )
    st.toast("Feedback saved")


def call(payload: dict) -> dict:
    progress = st.status("Working…", expanded=False)
    result: dict = {}
    with httpx.stream("POST", f"{API}/v1/ask/stream", json=payload, headers=HEADERS, timeout=120) as r:
        event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
                if event == "progress":
                    progress.update(label=f"Running: {data['node'].replace('_', ' ')}")
                elif event == "result":
                    result = data
    progress.update(label="Done", state="complete")
    return result


for m in st.session_state.messages:
    render(m)

pending = st.session_state.pending
if pending:
    st.info(pending["question"])
    cols = st.columns(len(pending["options"]) or 1)
    for i, opt in enumerate(pending["options"]):
        if cols[i].button(opt):
            st.session_state.pending = None
            res = call({"thread_id": st.session_state.thread_id, "resume": opt})
            st.session_state.messages.append(
                {
                    "id": len(st.session_state.messages),
                    "role": "assistant",
                    "content": res.get("answer") or "",
                    "result": res,
                }
            )
            st.rerun()

if prompt := st.chat_input("Ask about sales, returns, inventory, delivery or web conversion"):
    st.session_state.messages.append(
        {"id": len(st.session_state.messages), "role": "user", "content": prompt}
    )
    res = call({"question": prompt, "thread_id": st.session_state.thread_id})
    res["question"] = prompt
    st.session_state.thread_id = res.get("thread_id")
    if res.get("status") == "clarify":
        st.session_state.pending = res["clarification"]
    st.session_state.messages.append(
        {
            "id": len(st.session_state.messages),
            "role": "assistant",
            "content": res.get("answer") or "",
            "result": res,
        }
    )
    st.rerun()
