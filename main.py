import streamlit as st
import logging
import json
import time

from logging_setup import setup_logging
from research_agents import planner_agent, executor_agent
from database import db_service
from runner import runner
from config import MAX_TURNS

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Deep Research Swarm", layout="wide")

# --- Authentication ---
if 'user_id' not in st.session_state:
    st.title("Login / Register")
    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                user_id = db_service.authenticate_user(username, password)
                if user_id:
                    st.session_state.user_id = user_id
                    st.session_state.username = username
                    st.rerun()
                else:
                    st.error("Invalid username or password")

    with register_tab:
        with st.form("register_form"):
            username = st.text_input("Username", key="reg_user")
            password = st.text_input("Password", type="password", key="reg_pass")
            submitted = st.form_submit_button("Register")
            if submitted:
                user_id = db_service.register_user(username, password)
                if user_id:
                    st.success("Registration successful! Please login.")
                else:
                    st.error("Username already exists.")
else:
    # --- Main Application ---
    st.sidebar.title(f"Welcome, {st.session_state.username}")
    st.sidebar.markdown("---")

    # --- Run Management in Sidebar ---
    st.sidebar.subheader("Research Runs")
    user_runs = db_service.get_user_runs(st.session_state.user_id)
    
    if st.sidebar.button("➕ New Research Run"):
        # Simple title for now, could be a form
        new_run_title = f"New Run {len(user_runs) + 1}"
        new_run_id = db_service.create_run(st.session_state.user_id, new_run_title)
        st.session_state.active_run_id = new_run_id
        st.rerun()

    if not user_runs:
        st.sidebar.info("No research runs yet. Create one to begin.")
    else:
        for run in user_runs:
            if st.sidebar.button(f"📄 {run['title']}", key=run['id']):
                st.session_state.active_run_id = run['id']
                st.rerun()

    st.sidebar.markdown("---")

    # --- Active Run View ---
    if 'active_run_id' in st.session_state:
        run_id = st.session_state.active_run_id
        run_title = db_service.get_run_title(run_id) or "Research"
        st.title(f"🧠 {run_title}")

        # --- Plan and Approvals in Sidebar ---
        st.sidebar.subheader("📋 Research Plan")
        plan_df = db_service.get_all_plan(run_id)
        if not plan_df.empty:
            st.sidebar.dataframe(plan_df[["step_number", "description", "status"]])
        else:
            st.sidebar.info("Plan is empty for this run.")

        st.sidebar.subheader("🛡️ Security Approvals")
        approvals_df = db_service.get_pending_approvals(run_id)
        if not approvals_df.empty:
            for _, row in approvals_df.iterrows():
                st.sidebar.code(row['command_text'], language="bash")
                c1, c2 = st.sidebar.columns(2)
                if c1.button("✅ Approve", key=f"approve_{row['command_hash']}"):
                    db_service.update_approval_status(run_id, row['command_hash'], 1)
                    st.rerun()
                if c2.button("❌ Deny", key=f"deny_{row['command_hash']}"):
                    db_service.update_approval_status(run_id, row['command_hash'], -1)
                    st.rerun()
        else:
            st.sidebar.success("No pending actions for this run.")

        # --- Main Chat Area ---
        messages = db_service.load_messages(run_id)
        for msg in messages:
            if msg.role == "system": continue
            with st.chat_message(msg.role):
                st.markdown(f"**{msg.sender or ''}**")
                if msg.content:
                    st.markdown(msg.content)
                if msg.tool_calls:
                    st.json(msg.tool_calls)
        
        # --- Swarm Execution Logic ---
        if db_service.is_swarm_running(run_id):
            with st.status("🚀 Swarm is active...", expanded=True):
                while db_service.is_swarm_running(run_id):
                    time.sleep(2)
                    st.rerun()
            st.success("Swarm has finished its run.")
            time.sleep(1)
            st.rerun()

        if prompt := st.chat_input("Input research topic...", disabled=db_service.is_swarm_running(run_id)):
            plan_df = db_service.get_all_plan(run_id)
            start_agent = planner_agent if plan_df.empty else executor_agent
            
            # Save user message
            db_service.save_message(run_id, "user", prompt)
            
            # Start the swarm
            runner.run_in_background(
                run_id=run_id,
                user_id=st.session_state.user_id,
                start_agent=start_agent,
                input_text=prompt,
                max_turns=MAX_TURNS
            )
            st.rerun()
    else:
        st.info("Select a research run from the sidebar or create a new one.")