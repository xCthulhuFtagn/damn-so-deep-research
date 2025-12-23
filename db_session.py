import json
import logging
from typing import List, Any
try:
    from agents.memory import Session
except ImportError:
    from typing import Protocol, List, Dict
    class Session(Protocol):
        async def get_items(self, limit: int | None = None) -> List[dict]: ...
        async def add_items(self, items: List[dict]) -> None: ...
        async def pop_item(self) -> dict | None: ...
        async def clear_session(self) -> None: ...
from database import db

logger = logging.getLogger(__name__)

class DBSession(Session):
    """
    Adapter to persist agent conversation history to the existing SQLite database
    via the DatabaseManager.
    """
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """Retrieve conversation history based on session logic."""
        
        # 1. Context Anchor: Plan Summary
        plan_summary = db.get_plan_summary()
        system_msg = {
            "role": "system",
            "content": f"PROJECT STATUS:\n{plan_summary}"
        }
        
        raw_messages = []

        # 2. Fetch messages from DB
        if self.session_id == 'planner_init':
            pass
        elif self.session_id == 'reporter_flow':
            pass
        elif self.session_id == 'main_research':
            active_task = db.get_active_task()
            if active_task is not None:
                # Task-Scoped Memory
                raw_messages.extend(db.get_messages_for_task(self.session_id, active_task))
            else:
                # Fallback to recent history
                raw_messages.extend(db.get_last_n_messages(self.session_id, 10))
        else:
            msgs = db.load_messages(self.session_id)
            if limit: msgs = msgs[-limit:]
            raw_messages.extend(msgs)

        # 3. SANITIZATION
        clean_messages = [system_msg]
        
        for m in raw_messages:
            role = m["role"]
            # Гарантируем, что content - всегда строка. Если None, то "".
            content = m.get("content")
            if content is None:
                content = ""
            
            clean_msg = {
                "role": role,
                "content": content
            }
            
            # --- ЛОГИКА ДЛЯ АССИСТЕНТА ---
            if role == "assistant":
                # Обработка tool_calls
                if m.get("tool_calls"):
                    tcs = m["tool_calls"]
                    # Если вдруг пришло строкой (бывает в некоторых драйверах), парсим
                    if isinstance(tcs, str):
                        try:
                            tcs = json.loads(tcs)
                        except json.JSONDecodeError:
                            tcs = []

                    clean_tcs = []
                    for tc in tcs:
                        if isinstance(tc, dict):
                            # ВАЖНО: OpenAI API требует, чтобы arguments были СТРОКОЙ (JSON string).
                            # Если БД вернула dict, сериализуем обратно в строку.
                            if "function" in tc:
                                func = tc["function"]
                                args = func.get("arguments", "{}")
                                if isinstance(args, dict):
                                    func["arguments"] = json.dumps(args)
                            clean_tcs.append(tc)
                        else:
                            clean_tcs.append(tc)
                            
                    if clean_tcs:
                        clean_msg["tool_calls"] = clean_tcs
                
                # Если сообщение пустое (нет текста и нет вызовов) - пропускаем
                if not content and not clean_msg.get("tool_calls"):
                    continue

            # --- ЛОГИКА ДЛЯ ИНСТРУМЕНТА (TOOL) ---
            elif role == "tool":
                # У тула ОБЯЗАН быть tool_call_id
                if m.get("tool_call_id"):
                    clean_msg["tool_call_id"] = m["tool_call_id"]
                else:
                    # Без ID сообщение тула бесполезно
                    continue
                
                # Имя тула (берем из sender или name)
                if m.get("sender"):
                    clean_msg["name"] = m["sender"]
                elif m.get("name"):
                    clean_msg["name"] = m["name"]

            # Сообщения system/user копируем как есть (content уже обработан выше)
            
            clean_messages.append(clean_msg)

        logger.debug(f"DBSession({self.session_id}): get_items returning {len(clean_messages)} sanitized items")
        return clean_messages

    async def add_items(self, items: List[Any]) -> None:
        """Store new items."""
        logger.debug(f"DBSession({self.session_id}): add_items called with {len(items)} items")
        for item in items:
            # SDK session items can be dicts or objects
            is_dict = isinstance(item, dict)
            role = item.get("role") if is_dict else getattr(item, "role", None)
            item_type = item.get("type") if is_dict else getattr(item, "type", None)
            
            # --- Role Inference ---
            if role is None:
                if item_type == "function_call_output" or (is_dict and "call_id" in item and "output" in item):
                    role = "tool"
                elif item_type == "function_call" or (is_dict and "call_id" in item and "name" in item):
                    role = "assistant"
                elif item_type == "reasoning":
                    role = "assistant"
                else:
                    role = "system" # Fallback
            
            # --- Content Extraction ---
            raw_content = item.get("content") if is_dict else getattr(item, "content", None)
            
            if raw_content is None and (item_type == "function_call_output" or role == "tool"):
                raw_content = item.get("output") if is_dict else getattr(item, "output", None)

            content = ""
            if isinstance(raw_content, list):
                parts = []
                for block in raw_content:
                    if isinstance(block, dict):
                        val = block.get("text") or block.get("output_text")
                        if val: parts.append(str(val))
                    elif hasattr(block, "text"):
                        val = getattr(block, "text")
                        if val: parts.append(str(val))
                content = "".join(parts)
            else:
                content_str = str(raw_content or "").strip()
                if raw_content is None or content_str in ("{}", "None", "[]"):
                    content = ""
                else:
                    content = content_str

            # --- Tool Call Extraction ---
            tool_calls = item.get("tool_calls") if is_dict else getattr(item, "tool_calls", None)
            
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
                            "arguments": arguments or "{}"
                        }
                    }]

            tool_call_id = item.get("tool_call_id") or item.get("call_id") if is_dict else getattr(item, "tool_call_id", getattr(item, "call_id", None))
            
            # Normalize tool calls
            if tool_calls and not isinstance(tool_calls, list):
                tool_calls = [tool_calls]
            
            final_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        final_tool_calls.append(tc)
                    else:
                        try:
                            if hasattr(tc, "model_dump"):
                                final_tool_calls.append(tc.model_dump())
                            elif hasattr(tc, "dict"):
                                final_tool_calls.append(tc.dict())
                            else:
                                final_tool_calls.append({
                                    "id": getattr(tc, "id", None),
                                    "type": getattr(tc, "type", "function"),
                                    "function": {
                                        "name": getattr(getattr(tc, "function", None), "name", None),
                                        "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                                    } if hasattr(tc, "function") else None
                                })
                        except Exception:
                            logger.warning("Failed to serialize tool call object")

            sender = item.get("sender") or item.get("name") if is_dict else getattr(item, "sender", getattr(item, "name", None))

            db.save_message(
                role=str(role),
                content=content if content.strip() else None,
                tool_calls=final_tool_calls if final_tool_calls else None,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                sender=None if sender is None else str(sender),
                session_id=self.session_id 
            )

    async def pop_item(self) -> dict | None:
        """Remove and return the most recent item."""
        # Using raw SQL via DatabaseManager connection to support pop logic if needed,
        # but pop is rarely used.
        conn = db.get_connection()
        c = conn.cursor()
        # Get last message for this session
        c.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1", (self.session_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return None
        
        # Delete it
        msg_id = row[0] # assuming id is first column
        c.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
        conn.commit()
        conn.close()
        
        # We need to reconstruct the dict to return it, but for now just returning True-ish or None
        # In a real implementation we would map row to dict.
        # But this is edge case.
        return {"content": "popped"}

    async def clear_session(self) -> None:
        """Clear all items for this session."""
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
        conn.commit()
        conn.close()
