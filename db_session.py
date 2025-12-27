import json
import logging
from typing import List, Any

try:
    from agents.memory import Session
except ImportError:
    from typing import Protocol

    class Session(Protocol):
        async def get_items(self, limit: int | None = None) -> List[dict]: ...
        async def add_items(self, items: List[dict]) -> None: ...
        async def pop_item(self) -> dict | None: ...
        async def clear_session(self) -> None: ...


from database import DatabaseManager

logger = logging.getLogger(__name__)


def _as_json_str(x: Any) -> str:
    """Ensure arguments are JSON string (Responses/Agents style)."""
    if x is None:
        return "{}"
    if isinstance(x, str):
        s = x.strip()
        return s if s else "{}"
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return "{}"


def _msg_item(role: str, text: str) -> dict:
    """
    Responses-style message item with content blocks.
    This is required because Agents SDK chat-completions converter expects content as a list of dict blocks.
    """
    text = "" if text is None else str(text)
    if role == "assistant":
        content = [{"type": "output_text", "text": text}]
    else:
        content = [{"type": "input_text", "text": text}]
    return {
        "type": "message",
        "role": role,
        "content": content,
    }


class DBSession(Session):
    """
    Adapter to persist agent conversation history to SQLite (DatabaseManager).
    """
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """
        Return session items as Responses input items:
          - {"type":"message","role":"user|assistant|system","content":[{"type":"input_text|output_text","text":"..."}]}
          - {"type":"function_call","call_id":"...","name":"...","arguments":"{...}"}
          - {"type":"function_call_output","call_id":"...","output":"..."}
        """
        # 1) Context Anchor: Plan Summary (system message)
        plan_summary = DatabaseManager.get_instance().get_plan_summary()
        system_text = f"PROJECT STATUS:\n{plan_summary}"
        items: List[dict] = [_msg_item("system", system_text)]

        raw_messages: List[dict] = []

        # 2) Fetch messages from DB
        if self.session_id == "planner_init":
            pass
        elif self.session_id == "reporter_flow":
            pass
        elif self.session_id == "main_research":
            active_task = DatabaseManager.get_instance().get_active_task()
            if active_task is not None:
                raw_messages.extend(DatabaseManager.get_instance().get_messages_for_task(self.session_id, active_task))
            else:
                raw_messages.extend(DatabaseManager.get_instance().get_last_n_messages(self.session_id, 10))
        else:
            msgs = DatabaseManager.get_instance().load_messages(self.session_id)
            if limit:
                msgs = msgs[-limit:]
            raw_messages.extend(msgs)

        # 3) Convert DB messages -> Responses items
        for m in raw_messages:
            role = str(m.get("role") or "").strip()
            if not role:
                continue

            content = m.get("content")
            if content is None:
                content = ""
            content = str(content)

            # --- TOOL OUTPUT MESSAGES ---
            if role == "tool":
                call_id = m.get("tool_call_id") or m.get("call_id")
                if not call_id:
                    continue
                items.append({
                    "type": "function_call_output",
                    "call_id": str(call_id),
                    "output": content,
                })
                continue

            # --- SYSTEM / USER / ASSISTANT ---
            if role in ("system", "user", "assistant"):
                tool_calls = m.get("tool_calls")

                # If assistant has tool_calls -> convert to function_call items
                if role == "assistant" and tool_calls:
                    if isinstance(tool_calls, str):
                        try:
                            tool_calls = json.loads(tool_calls)
                        except json.JSONDecodeError:
                            tool_calls = []

                    # Keep assistant text if exists
                    if content.strip():
                        items.append(_msg_item("assistant", content))

                    # Convert tool_calls -> function_call items
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue

                            call_id = tc.get("id") or tc.get("call_id")
                            func = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                            name = func.get("name") or tc.get("name")
                            args = func.get("arguments", "{}") if func else tc.get("arguments", "{}")

                            if not call_id or not name:
                                continue

                            items.append({
                                "type": "function_call",
                                "call_id": str(call_id),
                                "name": str(name),
                                "arguments": _as_json_str(args),
                            })
                    continue

                # Drop empty assistant text to reduce noise
                if role == "assistant" and not content.strip():
                    continue

                items.append(_msg_item(role, content))
                continue

            # Unknown roles: ignore
            continue

        logger.debug("DBSession(%s): get_items returning %d items", self.session_id, len(items))
        return items

    async def add_items(self, items: List[Any]) -> None:
        """
        Store new items coming from the SDK into DatabaseManager.get_instance().
        We keep the DB schema: role/content + optional tool_calls/tool_call_id.
        """
        logger.debug("DBSession(%s): add_items called with %d items", self.session_id, len(items))

        for item in items:
            is_dict = isinstance(item, dict)
            role = item.get("role") if is_dict else getattr(item, "role", None)
            item_type = item.get("type") if is_dict else getattr(item, "type", None)

            # --- Role inference ---
            if role is None:
                if item_type == "function_call_output" or (is_dict and "call_id" in item and "output" in item):
                    role = "tool"
                elif item_type == "function_call" or (is_dict and "call_id" in item and "name" in item):
                    role = "assistant"
                elif item_type == "reasoning":
                    role = "assistant"
                else:
                    role = "system"

            # --- Content extraction ---
            raw_content = item.get("content") if is_dict else getattr(item, "content", None)

            if raw_content is None and (item_type == "function_call_output" or role == "tool"):
                raw_content = item.get("output") if is_dict else getattr(item, "output", None)

            content = ""
            if isinstance(raw_content, list):
                parts = []
                for block in raw_content:
                    if isinstance(block, dict):
                        # Responses-style content blocks use "text"
                        val = block.get("text") or block.get("output_text")
                        if val:
                            parts.append(str(val))
                    elif hasattr(block, "text"):
                        val = getattr(block, "text")
                        if val:
                            parts.append(str(val))
                content = "".join(parts)
            else:
                content_str = str(raw_content or "").strip()
                if raw_content is None or content_str in ("{}", "None", "[]"):
                    content = ""
                else:
                    content = content_str

            # --- Tool call extraction (store in DB as tool_calls list) ---
            tool_calls = item.get("tool_calls") if is_dict else getattr(item, "tool_calls", None)

            # If SDK gives function_call item, normalize into tool_calls shape for DB storage
            if tool_calls is None and item_type == "function_call":
                call_id = item.get("call_id") if is_dict else getattr(item, "call_id", None)
                name = item.get("name") if is_dict else getattr(item, "name", None)
                arguments = item.get("arguments") if is_dict else getattr(item, "arguments", None)
                if call_id and name:
                    tool_calls = [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": _as_json_str(arguments),
                        }
                    }]

            tool_call_id = (
                (item.get("tool_call_id") or item.get("call_id")) if is_dict
                else getattr(item, "tool_call_id", getattr(item, "call_id", None))
            )

            # Normalize tool_calls
            if tool_calls and not isinstance(tool_calls, list):
                tool_calls = [tool_calls]

            final_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        func = tc.get("function")
                        if isinstance(func, dict):
                            func["arguments"] = _as_json_str(func.get("arguments"))
                        final_tool_calls.append(tc)
                    else:
                        try:
                            if hasattr(tc, "model_dump"):
                                dumped = tc.model_dump()
                                func = dumped.get("function")
                                if isinstance(func, dict):
                                    func["arguments"] = _as_json_str(func.get("arguments"))
                                final_tool_calls.append(dumped)
                            elif hasattr(tc, "dict"):
                                dumped = tc.dict()
                                func = dumped.get("function")
                                if isinstance(func, dict):
                                    func["arguments"] = _as_json_str(func.get("arguments"))
                                final_tool_calls.append(dumped)
                        except Exception:
                            logger.warning("Failed to serialize tool call object")

            sender = (
                (item.get("sender") or item.get("name")) if is_dict
                else getattr(item, "sender", getattr(item, "name", None))
            )

            DatabaseManager.get_instance().save_message(
                role=str(role),
                content=content if content.strip() else None,
                tool_calls=final_tool_calls if final_tool_calls else None,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                sender=None if sender is None else str(sender),
                session_id=self.session_id
            )

    async def pop_item(self) -> dict | None:
        conn = DatabaseManager.get_instance().get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1", (self.session_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None

        msg_id = row[0]
        c.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
        conn.commit()
        conn.close()
        return {"content": "popped"}

    async def clear_session(self) -> None:
        conn = DatabaseManager.get_instance().get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
        conn.commit()
        conn.close()
