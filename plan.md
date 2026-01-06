# Detailed Refactoring Plan: Multi-User Architecture

## Phase 1: Modularization (Structural Hygiene)
*Goal: Decouple the monolithic files into logical modules. No logic changes, just movement.*

1.  **Create Directory Structure**
    ```bash
    mkdir -p utils tools
    touch utils/__init__.py tools/__init__.py
    ```

2.  **Move Web Scraping Logic**
    *   **Source:** `tools.py` (`fetch_and_process_url`)
    *   **Destination:** `utils/web_scraper.py`
    *   **Action:**
        *   Move `fetch_and_process_url` function.
        *   Move imports: `requests`, `trafilatura`, `concurrent.futures`, `urlparse`, `hashlib`.
        *   Ensure `text_splitter` and merging logic are either moved here or to `text_processing.py`.

3.  **Move Text Processing Logic**
    *   **Source:** `tools.py` (Global vars `text_splitter`, `bi_encoder`, `cross_encoder`)
    *   **Destination:** `utils/text_processing.py`
    *   **Action:**
        *   Initialize `SentenceTransformer` and `CrossEncoder` here.
        *   Initialize `RecursiveCharacterTextSplitter`.
        *   Export these objects for use in `tools/search.py`.

4.  **Split `tools.py`**
    *   **`tools/search.py`**:
        *   Move `intelligent_web_search`.
        *   Import `bi_encoder`, `cross_encoder`, `text_splitter` from `utils.text_processing`.
        *   Import `fetch_and_process_url` from `utils.web_scraper`.
    *   **`tools/planning.py`**:
        *   Move `add_steps_to_plan`, `get_current_plan_step`, `insert_corrective_steps`.
    *   **`tools/execution.py`**:
        *   Move `execute_terminal_command`, `read_file`, `answer_from_knowledge`.
    *   **`tools/reporting.py`**:
        *   Move `get_research_summary`, `submit_step_result`, `mark_step_failed`, `get_recovery_context`.
    *   **`tools/legacy.py`**:
        *   Move `web_search_summary`.

5.  **Update Imports**
    *   Scan `main.py`, `research_agents.py`, `runner.py`.
    *   Replace `import tools` with explicit imports: `from tools.search import intelligent_web_search`, etc.

---

## Phase 2: Database Schema & Multi-Tenancy
*Goal: Enable multiple users and isolated runs.*

6.  **Database Migration (Schema Changes)**
    *   **File:** `database.py` (init_db method)
    *   **New Table: `users`**
        ```sql
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,  -- UUID
            username TEXT UNIQUE,
            password_hash TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        ```
    *   **New Table: `runs`**
        ```sql
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,  -- UUID
            user_id TEXT,
            title TEXT,
            status TEXT DEFAULT 'active', -- active, archived
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        ```
    *   **Modify Existing Tables:**
        *   `plan`: Add `run_id TEXT`. PK should likely become `(run_id, step_number)` or keep generic ID and index `run_id`.
        *   `messages`: Add `run_id TEXT`. Index `idx_messages_run_id`.
        *   `approvals`: Add `run_id TEXT`.
        *   `global_state` -> `run_state`: Key should be `(run_id, key)`.

7.  **Refactor `DatabaseManager` to `DatabaseService`**
    *   **File:** `database.py`
    *   **Remove Singleton:** Delete `_instance` and `__new__`. Make it a standard class `DatabaseService`.
    *   **Constructor:** `def __init__(self, db_path: str): ...`
    *   **Auth Methods:**
        *   `register_user(username, password) -> user_id` (Use `bcrypt` for hashing).
        *   `authenticate_user(username, password) -> user_id | None`.
    *   **Run Management:**
        *   `create_run(user_id, initial_prompt) -> run_id`.
        *   `get_user_runs(user_id) -> List[Dict]`.
    *   **Refactor ALL Methods to Accept `run_id`:**
        *   `add_plan_step(description, step_number)` -> `add_plan_step(run_id, description, step_number)`
        *   `get_next_step()` -> `get_next_step(run_id)`
        *   `save_message(...)` -> `save_message(run_id, ...)`
    *   *Note:* Update all SQL queries to `WHERE run_id = ?`.

---

## Phase 3: Context & Runner Concurrency
*Goal: Thread-safe execution using ContextVars.*

8.  **Implement ContextVars**
    *   **File:** `utils/context.py` (New File)
    *   **Content:**
        ```python
        import contextvars
        
        # Context Vars
        current_run_id = contextvars.ContextVar("current_run_id", default=None)
        current_user_id = contextvars.ContextVar("current_user_id", default=None)
        
        # Helper to get DB instance (optional, if we want to DI)
        ```
    
9.  **Inject Context in Tools**
    *   **File:** `tools/*.py`
    *   **Action:** In every tool function, retrieve the ID:
        ```python
        from utils.context import current_run_id
        
        @function_tool
        def get_current_plan_step():
            run_id = current_run_id.get()
            if not run_id: return "Error: No active run."
            # Call DB with run_id
            return db_service.get_next_step(run_id)
        ```

10. **Update `SwarmRunner`**
    *   **File:** `runner.py`
    *   **Method:** `run_in_background(self, run_id, user_id, start_agent, input_text)`
    *   **Action:**
        *   Inside the thread target wrapper, **SET** the context vars immediately:
            ```python
            token_run = current_run_id.set(run_id)
            token_user = current_user_id.set(user_id)
            try:
                # ... execute agents ...
            finally:
                current_run_id.reset(token_run)
                # ...
            ```
        *   Maintain a `self.active_runs = {}` dict to track threads by `run_id`.

---

## Phase 4: Data Structures & Optimization
*Goal: Type safety and better code.*

11. **Typed Message Objects**
    *   **File:** `database.py` (or `schema.py`)
    *   **Class:**
        ```python
        from pydantic import BaseModel, Field
        from typing import Optional, List, Dict, Any
        
        class ChatMessage(BaseModel):
            id: Optional[int]
            role: str
            content: Optional[str] = ""
            tool_calls: Optional[List[Dict[str, Any]]] = None # Flexible payload
            run_id: str
            sender: Optional[str]
            timestamp: Optional[str]
        ```
    *   **Action:** Update `load_messages(run_id)` to return `List[ChatMessage]`.

---

## Phase 5: UI Updates (Streamlit)
*Goal: Multi-user interface.*

12. **Login Screen**
    *   **File:** `main.py`
    *   Check `if "user_id" not in st.session_state`:
        *   Show Login/Register tabs.
        *   On success, set `st.session_state["user_id"]`.

13. **Dashboard Layout**
    *   **Sidebar:**
        *   "Create New Research Run" (+ Button).
        *   "History": List runs (`db.get_user_runs(user_id)`).
        *   On click, set `st.session_state["active_run_id"]`.
    *   **Main Area:**
        *   If `active_run_id` is set:
            *   Show Chat Interface (filtered by `run_id`).
            *   Show Plan (filtered by `run_id`).
        *   Else:
            *   Show "Select a run or create new".

14. **Terminal Approvals**
    *   Update approval UI to filter by `run_id` (so User A doesn't approve User B's command).
