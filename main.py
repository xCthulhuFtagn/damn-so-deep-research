import streamlit as st
import sqlite3
import pandas as pd
import logging
import re
import json

from logging_setup import setup_logging
from research_agents import planner_agent, executor_agent
import database
from runner import runner
from config import DB_NAME, MAX_TURNS, DB_PATH
import time

# Configure logging as early as possible (Streamlit reruns safe)
setup_logging()
logger = logging.getLogger(__name__)

_STEP_RE = re.compile(r"^\s*(\d+)[\.\)]\s+(.*\S)\s*$")


def _extract_numbered_steps(text: str) -> list[tuple[int, str]]:
    """
    Fallback parser when the model doesn't emit tool calls.
    Accepts lines like:
      1. Do X
      2) Do Y
    """
    if not text:
        return []
    steps: list[tuple[int, str]] = []
    for line in text.splitlines():
        m = _STEP_RE.match(line)
        if not m:
            continue
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        desc = m.group(2).strip()
        if desc:
            steps.append((num, desc))
    # keep stable order (and ignore duplicates by number)
    seen: set[int] = set()
    out: list[tuple[int, str]] = []
    for num, desc in steps:
        if num in seen:
            continue
        seen.add(num)
        out.append((num, desc))
    return out


def _safe_preview(text: str, max_len: int = 240) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...(truncated)"

# --- Init ---
st.set_page_config(page_title="Deep Research Swarm MVP", layout="wide")

if "messages" not in st.session_state:
    # При первом запуске инициализируем/чистим БД
    logger.info("First run: initializing DB and session state")
    database.init_db()
    # Load history from DB
    st.session_state.messages = database.load_messages()
    
# Отслеживание прогресса для очистки памяти
if "done_steps_count" not in st.session_state:
    # Initialize from DB to avoid false "memory cleared" on reload
    st.session_state.done_steps_count = database.get_completed_steps_count()
    logger.debug("Session state initialized: done_steps_count=%s", st.session_state.done_steps_count)

# --- Sidebar ---
st.sidebar.title("🎛️ Control Center")

# Кнопка полной остановки (только если рой запущен)
if database.is_swarm_running():
    if st.sidebar.button("🛑 Stop Research", type="primary"):
        logger.info("User requested stop")
        database.set_stop_signal(True)
        st.toast("Stopping swarm...", icon="🛑")
else:
    # Кнопка полного сброса (только если рой НЕ запущен)
    if st.sidebar.button("Reset Research"):
        logger.info("User requested reset: clearing DB and UI state")
        database.clear_db()
        st.session_state.messages = []
        st.session_state.done_steps_count = 0
        st.rerun()

# Отображение плана
st.sidebar.subheader("📋 Research Plan")

plan_container = st.sidebar.empty()

def render_plan():
    with plan_container.container():
        try:
            plan_df = database.get_all_plan()
            logger.debug("Loaded plan for sidebar: rows=%s", 0 if plan_df is None else len(plan_df))
            if not plan_df.empty:
                # Красим статусы
                def color_status(val):
                    color = 'grey'
                    if val == 'DONE': color = 'green'
                    elif val == 'IN_PROGRESS': color = 'orange'
                    elif val == 'FAILED': color = 'red'
                    return f'color: {color}'
                
                st.dataframe(
                    plan_df[["step_number", "description", "status"]].style.map(color_status, subset=['status'])
                )
            else:
                st.info("Plan empty.")
        except Exception as e:
            logger.exception("DB error while rendering plan sidebar")
            st.error(f"DB Error: {e}")

render_plan()

# Одобрение команд терминала
st.sidebar.subheader("🛡️ Security Approvals")
try:
    conn = sqlite3.connect(DB_NAME)
    approvals = pd.read_sql_query("SELECT * FROM approvals WHERE approved = 0", conn)
    conn.close()
    logger.debug("Loaded pending approvals: count=%s", len(approvals))
except Exception:
    logger.exception("Failed to load approvals from DB")
    approvals = pd.DataFrame()

if not approvals.empty:
    st.sidebar.warning(f"Pending Approvals: {len(approvals)}")
    for index, row in approvals.iterrows():
        st.sidebar.code(row['command_text'], language="bash")
        c1, c2 = st.sidebar.columns(2)
        if c1.button("✅ Approve", key=f"y_{row['command_hash']}"):
            logger.info("Approved terminal command: hash=%s", row["command_hash"])
            c = sqlite3.connect(DB_NAME)
            c.execute("UPDATE approvals SET approved=1 WHERE command_hash=?", (row['command_hash'],))
            c.commit()
            c.close()
            st.rerun()
        if c2.button("❌ Deny", key=f"n_{row['command_hash']}"):
            logger.info("Denied terminal command: hash=%s", row["command_hash"])
            c = sqlite3.connect(DB_NAME)
            # Use -1 as a sentinel for denied (SQLite doesn't enforce BOOLEAN strictly)
            c.execute("UPDATE approvals SET approved=-1 WHERE command_hash=?", (row['command_hash'],))
            c.commit()
            c.close()
            st.rerun()
else:
    st.sidebar.success("No pending actions")

# --- Main Chat ---
st.title("🧠 Deep Research Agent Swarm")

# Рендер истории
# Always load fresh messages from DB to stay in sync with background runner
st.session_state.messages = database.load_messages()

for msg in st.session_state.messages:
    # Defensive: ignore malformed rows (older runs could have role=None).
    if msg.get("role") is None:
        continue
    if msg["role"] == "system":
        if msg["content"] and ("Error" in msg["content"] or "failed" in msg.get("content", "").lower()):
            with st.chat_message("assistant", avatar="🚨"):
                st.error(msg["content"])
        continue 
    if msg["role"] == "tool": continue   # Скрываем результаты инструментов (промежуточные)
    
    # Пропускаем только пустые или чисто технические сообщения ассистента без вызовов инструментов
    content = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls")
    
    if msg["role"] == "assistant" and not tool_calls and (not content or content in ("{}", "None", "[]")):
        continue
    
    # Streamlit chat_message signature treats the first positional arg as "name".
    # We keep styling by using only "user"/"assistant" as the chat name, and
    # display custom senders (Planner/Executor/...) inside the message body.
    role = msg["role"] if msg["role"] in ("user", "assistant") else "assistant"
    sender = (msg.get("sender") or "").strip() if role == "assistant" else ""
    content = msg.get("content") or ""

    with st.chat_message(role):
        if sender:
            st.markdown(f"**{sender}**")
        st.markdown(content)

# --- Logic for Running Swarm ---
def start_swarm(prompt: str, start_agent_name="Planner"):
    # ОПРЕДЕЛЕНИЕ НАЧАЛЬНОГО АГЕНТА
    plan_df = database.get_all_plan()
    
    if start_agent_name == "Planner":
         start_agent = planner_agent
    elif start_agent_name == "Executor":
         start_agent = executor_agent
    else:
         start_agent = planner_agent if plan_df.empty else executor_agent

    logger.info("Starting swarm via runner: agent=%s", start_agent.name)
    # Передаем MAX_TURNS из конфига в раннер
    runner.run_in_background(start_agent, input_text=prompt, max_turns=MAX_TURNS)
    st.rerun()

# --- Observer Loop (if swarm is running) ---
if database.is_swarm_running():
    with st.status("🚀 Swarm is active...", expanded=True) as status:
        st.write("Agents are performing research steps...")
        # Polling loop
        last_msg_count = len(st.session_state.messages)
        while database.is_swarm_running():
            time.sleep(2)
            # Check for new messages to trigger UI refresh
            current_messages = database.load_messages()
            if len(current_messages) > last_msg_count:
                st.rerun()
            
        # Проверяем на ошибки перед финальным рендером
        final_messages = database.load_messages()
        has_error = any("Error" in (m.get("content") or "") for m in final_messages if m["role"] == "system")
        
        if has_error:
            status.update(label="Swarm execution failed", state="error", expanded=True)
        else:
            status.update(label="Swarm finished!", state="complete", expanded=False)
        
        time.sleep(1)
        st.rerun()

# Обработка ввода
if prompt := st.chat_input("Input research topic...", disabled=database.is_swarm_running()):
    logger.info("User prompt received: chars=%s", len(prompt))
    # We do NOT save to DB here; Runner will save it via session.add_items
    
    # Determine start agent
    plan_df = database.get_all_plan()
    start_agent_name = "Planner" if plan_df.empty else "Executor"
    start_swarm(prompt=prompt, start_agent_name=start_agent_name)
