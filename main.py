import streamlit as st
import sqlite3
import pandas as pd
import logging
import re
import json

from logging_setup import setup_logging
from research_agents import planner_agent, executor_agent
from database import DatabaseManager
from runner import runner
from config import DB_PATH, MAX_TURNS
import time

# Configure logging as early as possible (Streamlit reruns safe)
setup_logging()
logger = logging.getLogger(__name__)

# --- MONKEY PATCH START (V4 - Aggressive Early Interception) ---
from agents import _run_impl
import re

# Сохраняем оригинальный метод (если еще не сохранен)
if not hasattr(_run_impl.RunImpl, "_original_process_model_response"):
    _run_impl.RunImpl._original_process_model_response = _run_impl.RunImpl.process_model_response

# Regex pattern to detect and clean tool name artifacts
TOOL_NAME_ARTIFACT_PATTERN = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)<\|.*$')

def _clean_tool_name(name: str) -> str:
    """
    Aggressively clean tool name from artifacts like <|channel|>commentary, <|think|>, etc.
    Returns the base tool name only.
    """
    if not name or not isinstance(name, str):
        return name
    
    # Check for artifact pattern
    match = TOOL_NAME_ARTIFACT_PATTERN.match(name)
    if match:
        clean = match.group(1)
        logger.warning(f"🔧 Cleaned tool name: '{name}' → '{clean}'")
        return clean
    
    # Fallback: split on <| if present
    if "<|" in name:
        clean = name.split("<|")[0]
        logger.warning(f"🔧 Cleaned tool name (fallback): '{name}' → '{clean}'")
        return clean
    
    return name

def _sanitize_tool_calls(tool_calls):
    """
    Helper function to iterate and clean tool calls list, 
    handling both object attributes and dictionary keys.
    """
    if not tool_calls:
        return

    for tc in tool_calls:
        # Вариант 1: tc - это объект (Pydantic model)
        if hasattr(tc, 'function') and hasattr(tc.function, 'name'):
            original_name = tc.function.name
            clean_name = _clean_tool_name(original_name)
            if clean_name != original_name:
                tc.function.name = clean_name
        
        # Вариант 2: tc - это словарь (dict)
        elif isinstance(tc, dict) and 'function' in tc:
            func = tc['function']
            # func может быть словарем или объектом
            if isinstance(func, dict) and 'name' in func:
                original_name = func['name']
                clean_name = _clean_tool_name(original_name)
                if clean_name != original_name:
                    func['name'] = clean_name
            elif hasattr(func, 'name'):
                original_name = func.name
                clean_name = _clean_tool_name(original_name)
                if clean_name != original_name:
                    func.name = clean_name

def _patched_process_model_response(*args, **kwargs):
    """
    Патч для очистки имен инструментов от мусора.
    Перехватывает response перед обработкой и чистит его на любой глубине.
    """
    response = kwargs.get('response')
    agent = kwargs.get('agent')
    agent_name = agent.name if agent else 'Unknown'
    
    if response:
        try:
            # Log all tool calls BEFORE sanitization for debugging
            tool_names_found = []
            
            # 1. Проверяем tool_calls прямо в корне (если response это Message)
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tc in response.tool_calls:
                    if hasattr(tc, 'function') and hasattr(tc.function, 'name'):
                        tool_names_found.append(tc.function.name)
                _sanitize_tool_calls(response.tool_calls)
            
            # 2. Проверяем стандартную структуру OpenAI: response.choices[0].message.tool_calls
            if hasattr(response, 'choices') and isinstance(response.choices, list):
                for choice in response.choices:
                    if hasattr(choice, 'message'):
                         if hasattr(choice.message, 'tool_calls') and choice.message.tool_calls:
                             for tc in choice.message.tool_calls:
                                 if hasattr(tc, 'function') and hasattr(tc.function, 'name'):
                                     tool_names_found.append(tc.function.name)
                             _sanitize_tool_calls(choice.message.tool_calls)

            # 3. Проверяем структуру agents.items.ModelResponse.output
            if hasattr(response, 'output') and isinstance(response.output, list):
                for item in response.output:
                    # Проверяем прямой атрибут 'name' (ResponseFunctionToolCall)
                    if hasattr(item, 'name') and item.name:
                         original_name = item.name
                         tool_names_found.append(original_name)
                         clean_name = _clean_tool_name(original_name)
                         if clean_name != original_name:
                             item.name = clean_name
            
            # Log discovered tool calls
            if tool_names_found:
                logger.info(f"🔧 Agent '{agent_name}' called tools: {tool_names_found}")
                
            # DEBUG: Check handoff matching
            if kwargs.get('handoffs'):
                handoff_names = []
                for h in kwargs['handoffs']:
                    if hasattr(h, 'tool_name'):
                        handoff_names.append(h.tool_name)
                    elif hasattr(h, 'name'):
                        handoff_names.append(h.name)
                    else:
                        handoff_names.append(str(h))

                logger.info(f"🔍 Agent '{agent_name}' valid handoffs: {handoff_names}")
                
                for tc in tool_names_found:
                    # Check if clean name matches any handoff
                    clean = _clean_tool_name(tc)
                    if clean in handoff_names:
                        logger.info(f"✅ MATCH: Tool '{clean}' matches handoff!")
                    else:
                        if "transfer" in clean:
                             logger.warning(f"⚠️ MISMATCH: Tool '{clean}' looks like handoff but not in list {handoff_names}")
            
        except Exception as e:
            logger.error(f"🔧 MonkeyPatch Error during traversal: {e}", exc_info=True)
            
    # Вызываем оригинал
    return _run_impl.RunImpl._original_process_model_response(*args, **kwargs)


# Применяем патч
_run_impl.RunImpl.process_model_response = _patched_process_model_response
logger.info("✅ Applied MonkeyPatch (v4) - Aggressive tool name sanitization")
# --- MONKEY PATCH END ---



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
    DatabaseManager.get_instance().init_db()
    # Load history from DB
    st.session_state.messages = DatabaseManager.get_instance().load_messages()
    
# Отслеживание прогресса для очистки памяти
if "done_steps_count" not in st.session_state:
    # Initialize from DB to avoid false "memory cleared" on reload
    st.session_state.done_steps_count = DatabaseManager.get_instance().get_completed_steps_count()
    logger.debug("Session state initialized: done_steps_count=%s", st.session_state.done_steps_count)

# --- Sidebar ---
st.sidebar.title("🎛️ Control Center")

# Кнопка полной остановки (только если рой запущен)
if DatabaseManager.get_instance().is_swarm_running():
    drop_research_text = "🛑 Drop running research"
else:
    drop_research_text = "🛑 Drop research"
if st.sidebar.button("🛑 Drop research", type="primary"):
    logger.info("User requested stop")
    DatabaseManager.get_instance().set_stop_signal(True)
    st.toast("Stopping swarm...", icon="🛑")
    # Кнопка полного сброса (только если рой НЕ запущен)
    logger.info("User requested reset: clearing DB and UI state")
    st.toast("Clearing DB...", icon="🛑")
    DatabaseManager.get_instance().clear_db()
    st.session_state.clear()
    st.rerun()

# Отображение плана
st.sidebar.subheader("📋 Research Plan")

plan_container = st.sidebar.empty()

def render_plan():
    with plan_container.container():
        try:
            plan_df = DatabaseManager.get_instance().get_all_plan()
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
    approvals = DatabaseManager.get_instance().get_pending_approvals()
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
            DatabaseManager.get_instance().update_approval_status(row['command_hash'], 1)
            st.rerun()
        if c2.button("❌ Deny", key=f"n_{row['command_hash']}"):
            logger.info("Denied terminal command: hash=%s", row["command_hash"])
            DatabaseManager.get_instance().update_approval_status(row['command_hash'], 1)
            st.rerun()
else:
    st.sidebar.success("No pending actions")

# --- Main Chat ---
st.title("🧠 Deep Research Agent Swarm")

# Рендер истории
# Always load fresh messages from DB to stay in sync with background runner
st.session_state.messages = DatabaseManager.get_instance().load_messages()

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
    
    # Extract session and task context if available
    session_id = msg.get("session_id")
    task_num = msg.get("task_number")

    with st.chat_message(role):
        header = ""

        if tool_calls:
            tool_call = tool_calls[0]
            func_name = tool_call.get("function", {}).get("name")
            func_args_str = tool_call.get("function", {}).get("arguments", "{}")
            
            try:
                func_args = json.loads(func_args_str)
            except json.JSONDecodeError:
                func_args = {} # Fallback to empty dict
            match func_name:
                case "intelligent_web_search":
                    header += f"**{sender}({func_args.get("query", "N/A")})** "
                case "execute_terminal_command":
                    header += f"**{sender}({func_args.get("command", "N/A")})** "
                case "mark_step_failed":
                    header += f"**{sender}({func_args.get("error_msg", "N/A")})** "
                case _:
                    header += f"**{sender}()** "
        else:
            if sender:
                header += f"**{sender}** "
        
        # Add visual context indicators
        meta = []
        if session_id and session_id != 'default':
            meta.append(f"`[{session_id}]`")
        if task_num:
            meta.append(f"`(Task {task_num})`")
            
        if meta:
            header += " ".join(meta)
            
        if header:
            st.markdown(header)
        if not tool_calls:
            st.markdown(content)

# --- Logic for Running Swarm ---
def start_swarm(prompt: str, start_agent_name="Planner"):
    # ОПРЕДЕЛЕНИЕ НАЧАЛЬНОГО АГЕНТА
    plan_df = DatabaseManager.get_instance().get_all_plan()

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
if DatabaseManager.get_instance().is_swarm_running():
    with st.status("🚀 Swarm is active...", expanded=True) as status:
        st.write("Agents are performing research steps...")
        # Polling loop
        last_msg_count = len(st.session_state.messages)
        last_pending_approvals_count = DatabaseManager.get_instance().get_pending_approvals_count()
        while DatabaseManager.get_instance().is_swarm_running():
            time.sleep(2)
            # Check for new messages to trigger UI refresh
            current_messages = DatabaseManager.get_instance().load_messages()
            current_msg_count = len(current_messages)
            current_pending_approvals_count = DatabaseManager.get_instance().get_pending_approvals_count()
            if (current_msg_count != last_msg_count) or (current_pending_approvals_count != last_pending_approvals_count):
                st.rerun()
            
        # Проверяем на ошибки перед финальным рендером
        final_messages = DatabaseManager.get_instance().load_messages()
        has_error = any("Error" in (m.get("content") or "") for m in final_messages if m["role"] == "system")
        
        if has_error:
            status.update(label="Swarm execution failed", state="error", expanded=True)
        else:
            status.update(label="Swarm finished!", state="complete", expanded=False)
        
        time.sleep(1)
        st.rerun()

# Обработка ввода
if prompt := st.chat_input("Input research topic...", disabled=DatabaseManager.get_instance().is_swarm_running()):
    logger.info("User prompt received: chars=%s", len(prompt))
    # We do NOT save to DB here; Runner will save it via session.add_items
    
    # Determine start agent
    plan_df = DatabaseManager.get_instance().get_all_plan()
    start_agent_name = "Planner" if plan_df.empty else "Executor"
    start_swarm(prompt=prompt, start_agent_name=start_agent_name)
