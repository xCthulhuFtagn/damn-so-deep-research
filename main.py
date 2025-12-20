import streamlit as st
import sqlite3
import pandas as pd
import logging
import re
import json
import openai

from logging_setup import setup_logging
from agents import client, planner_agent, executor_agent
import database
from config import DB_NAME, MAX_TURNS

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

# Кнопка полного сброса
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
            # Можно добавить логику удаления или пометки rejected
            logger.info("Denied terminal command (no-op): hash=%s", row["command_hash"])
            pass
else:
    st.sidebar.success("No pending actions")

# --- Main Chat ---
st.title("🧠 Deep Research Agent Swarm")

# Рендер истории
for msg in st.session_state.messages:
    if msg["role"] == "system": continue # Скрываем системные напоминалки
    if msg["role"] == "tool": continue   # Скрываем результаты инструментов (промежуточные)
    
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"] or "") # Handle None content

# Обработка ввода
if prompt := st.chat_input("Input research topic..."):
    # Добавляем в UI
    logger.info("User prompt received: chars=%s", len(prompt))
    st.session_state.messages.append({"role": "user", "content": prompt})
    database.save_message("user", prompt)
    
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Swarm Agents are working..."):
        try:
            # ОПРЕДЕЛЕНИЕ НАЧАЛЬНОГО АГЕНТА
            # Если план пуст - зовем Planner. Если план есть - Executor.
            plan_df = database.get_all_plan()
            start_agent = planner_agent if plan_df.empty else executor_agent
            logger.info(
                "Starting Swarm run: start_agent=%s messages=%s max_turns=%s",
                getattr(start_agent, "name", str(start_agent)),
                len(st.session_state.messages),
                MAX_TURNS,
            )

            # ЗАПУСК SWARM
            # Мы отключаем debug-режим Swarm (debug=False), чтобы не засорять логи 
            # полным выводом результатов инструментов. 
            # Логирование вызовов и аргументов (INFO) осталось в tools.py.
            response = client.run(
                agent=start_agent,
                messages=st.session_state.messages,
                context_variables={},
                max_turns=MAX_TURNS,
                debug=False,
            )

            # Обработка ответа
            # Сохраняем ТОЛЬКО НОВЫЕ сообщения в БД
            new_messages = response.messages[len(st.session_state.messages):]
            for m in new_messages:
                database.save_message(
                    role=m["role"], 
                    content=m.get("content"), 
                    tool_calls=m.get("tool_calls"), 
                    sender=m.get("sender")
                )
            
            st.session_state.messages.extend(new_messages)
            logger.info("Swarm run finished: new_messages=%s", len(new_messages))
            
            last_msg = response.messages[-1]
            try:
                last_sender = last_msg.get("sender") or last_msg.get("role")
                last_content = last_msg.get("content") or ""
                last_tool_calls = last_msg.get("tool_calls")
                logger.debug(
                    "Swarm last message: sender=%s tool_calls=%s content_preview=%s",
                    last_sender,
                    bool(last_tool_calls),
                    _safe_preview(last_content),
                )
            except Exception:
                logger.debug("Swarm last message: (failed to introspect)")

            with st.chat_message("assistant"):
                if last_msg.get("content"):
                    st.markdown(last_msg["content"])
                else:
                    # Если контента нет (только тулы), можно ничего не выводить или показать спиннер
                    # Но так как это "финальный" ответ цикла, лучше что-то показать, если это не просто тул
                    pass

            # --- Fallback: if Planner didn't emit tool calls, try to parse and persist plan ourselves ---
            if start_agent is planner_agent:
                plan_df_after = database.get_all_plan()
                if plan_df_after.empty:
                    # Если план не создан через тулы, считаем что что-то пошло не так
                    logger.warning("Planner did not create a plan via tools.")
                    st.warning("Planner не создал план. Попробуйте уточнить запрос.")
            
            # Обновляем план в сайдбаре после выполнения (чтобы видеть новые шаги/статусы)
            render_plan()

        except json.JSONDecodeError as e:
            logger.error("Model output malformed JSON (usually in tool calls): %s", e)
            st.error(
                "🛑 **Model Error**: The model generated invalid JSON arguments for a tool call.\n"
                "This happens with smaller models (like gpt-oss-20b). Try restarting the step or clearing history."
            )
            st.stop()
        except openai.APIConnectionError as e:
            logger.error("Connection Error: %s", e)
            st.error(f"🔌 **Connection Error**: Failed to connect to LLM provider.\n\nDetails: {e}")
            st.stop()
        except Exception as e:
            logger.exception("Swarm run failed")
            st.error(f"Swarm run failed: {e}")
            st.stop()
            
        # --- ЛОГИКА "STATE OVER HISTORY" (Очистка памяти) ---
        current_done_count = database.get_completed_steps_count()
        logger.debug(
            "Completed steps count: current=%s previous=%s",
            current_done_count,
            st.session_state.done_steps_count,
        )
        
        # Если количество выполненных шагов увеличилось
        if current_done_count > st.session_state.done_steps_count:
            st.session_state.done_steps_count = current_done_count
            
            # Очищаем messages, чтобы не переполнять контекст
            # Агенты восстановят знания через tools.get_completed_research_context
            # NOTE: Мы также удаляем историю из БД?
            # Если мы очищаем st.session_state.messages, мы теряем контекст для модели.
            # Если мы хотим сохранить "визуальную" историю, но очистить контекст модели:
            # Swarm берет messages из аргумента.
            # Текущая логика: st.session_state.messages = [] -> полная очистка контекста.
            
            # ВАЖНО: При persistence мы должны решить, удалять ли из БД.
            # Логика "Memory cleared" подразумевает, что модель "забывает".
            # Чтобы поддержать это, мы можем удалить старые сообщения из БД или просто пометить их архивированными.
            # Для простоты MVP: удаляем из БД (или просто загружаем пустой список в session_state, но при перезагрузке они вернутся из БД).
            # Правильно: Удалить из messages таблицы (или иметь session_id, но у нас одна сессия).
            # Давайте очистим таблицу messages, но оставим системное сообщение.
            
            logger.info("Step completed -> memory cleared; done_steps_count=%s", current_done_count)
            
            # 1. Clear in-memory
            st.session_state.messages = []
            
            # 2. Clear DB messages (simulating context window reset)
            conn = sqlite3.connect(DB_NAME)
            conn.execute("DELETE FROM messages")
            conn.commit()
            conn.close()
            
            st.toast("✅ Step completed! Memory cleared.", icon="🧹")
            
            # Добавляем невидимый системный пинок
            system_msg = "PREVIOUS STEP DONE. Memory cleared. Use `get_current_plan_step` to continue."
            st.session_state.messages.append({
                "role": "system",
                "content": system_msg
            })
            database.save_message("system", system_msg)
            
    st.rerun()
