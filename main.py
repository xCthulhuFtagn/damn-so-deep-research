import streamlit as st
import sqlite3
import pandas as pd
from agents import client, planner_agent, executor_agent
import database
from config import DB_NAME, MAX_TURNS

# --- Init ---
st.set_page_config(page_title="Deep Research Swarm MVP", layout="wide")

if "messages" not in st.session_state:
    st.session_state.messages = []
    # При первом запуске инициализируем/чистим БД
    database.init_db()
    
# Отслеживание прогресса для очистки памяти
if "done_steps_count" not in st.session_state:
    st.session_state.done_steps_count = 0

# --- Sidebar ---
st.sidebar.title("🎛️ Control Center")

# Кнопка полного сброса
if st.sidebar.button("Reset Research"):
    database.clear_db()
    st.session_state.messages = []
    st.session_state.done_steps_count = 0
    st.rerun()

# Отображение плана
st.sidebar.subheader("📋 Research Plan")
try:
    plan_df = database.get_all_plan()
    if not plan_df.empty:
        # Красим статусы
        def color_status(val):
            color = 'grey'
            if val == 'DONE': color = 'green'
            elif val == 'IN_PROGRESS': color = 'orange'
            elif val == 'FAILED': color = 'red'
            return f'color: {color}'
        
        st.sidebar.dataframe(
            plan_df[["step_number", "description", "status"]].style.applymap(color_status, subset=['status'])
        )
    else:
        st.sidebar.info("Plan empty.")
except Exception as e:
    st.sidebar.error(f"DB Error: {e}")

# Одобрение команд терминала
st.sidebar.subheader("🛡️ Security Approvals")
conn = sqlite3.connect(DB_NAME)
approvals = pd.read_sql_query("SELECT * FROM approvals WHERE approved = 0", conn)
conn.close()

if not approvals.empty:
    st.sidebar.warning(f"Pending Approvals: {len(approvals)}")
    for index, row in approvals.iterrows():
        st.sidebar.code(row['command_text'], language="bash")
        c1, c2 = st.sidebar.columns(2)
        if c1.button("✅ Approve", key=f"y_{row['command_hash']}"):
            c = sqlite3.connect(DB_NAME)
            c.execute("UPDATE approvals SET approved=1 WHERE command_hash=?", (row['command_hash'],))
            c.commit()
            c.close()
            st.rerun()
        if c2.button("❌ Deny", key=f"n_{row['command_hash']}"):
            # Можно добавить логику удаления или пометки rejected
            pass
else:
    st.sidebar.success("No pending actions")

# --- Main Chat ---
st.title("🧠 Deep Research Agent Swarm")

# Рендер истории
for msg in st.session_state.messages:
    if msg["role"] != "system": # Скрываем системные напоминалки
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# Обработка ввода
if prompt := st.chat_input("Input research topic..."):
    # Добавляем в UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Swarm Agents are working..."):
        # ОПРЕДЕЛЕНИЕ НАЧАЛЬНОГО АГЕНТА
        # Если план пуст - зовем Planner. Если план есть - Executor.
        plan_df = database.get_all_plan()
        start_agent = planner_agent if plan_df.empty else executor_agent
        
        # ЗАПУСК SWARM
        response = client.run(
            agent=start_agent,
            messages=st.session_state.messages,
            context_variables={},
            max_turns=MAX_TURNS
        )
        
        # Обработка ответа
        last_msg = response.messages[-1]
        st.session_state.messages.extend(response.messages)
        
        with st.chat_message("assistant"):
            st.markdown(last_msg["content"])
            
        # --- ЛОГИКА "STATE OVER HISTORY" (Очистка памяти) ---
        current_done_count = database.get_completed_steps_count()
        
        # Если количество выполненных шагов увеличилось
        if current_done_count > st.session_state.done_steps_count:
            st.session_state.done_steps_count = current_done_count
            
            # Очищаем messages, чтобы не переполнять контекст
            # Агенты восстановят знания через tools.get_completed_research_context
            st.session_state.messages = []
            
            st.toast("✅ Step completed! Memory cleared.", icon="🧹")
            # Добавляем невидимый системный пинок, чтобы агент не потерялся в следующем ходе
            st.session_state.messages.append({
                "role": "system",
                "content": "PREVIOUS STEP DONE. Memory cleared. Use `get_current_plan_step` to continue."
            })
            
    st.rerun()

