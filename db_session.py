import json
import logging
from typing import List, Any, Dict

try:
    from agents.memory import Session
except ImportError:
    from typing import Protocol
    class Session(Protocol):
        async def get_items(self, limit: int | None = None) -> List[dict]: ...
        async def add_items(self, items: List[dict]) -> None: ...
        async def pop_item(self) -> dict | None: ...
        async def clear_session(self) -> None: ...

from database import db_service
from utils.context import current_run_id
from schema import ChatMessage

logger = logging.getLogger(__name__)

def _as_json_str(x: Any) -> str:
    if x is None: return "{}"
    if isinstance(x, str): return x.strip() or "{}"
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return "{}"

def _msg_item(role: str, text: str) -> Dict:
    text = "" if text is None else str(text)
    content_type = "output_text" if role == "assistant" else "input_text"
    return {"type": "message", "role": role, "content": [{"type": content_type, "text": text}]}

class DBSession(Session):
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id

    async def get_items(self, limit: int | None = None) -> List[Dict]:
        run_id = current_run_id.get()
        if not run_id:
            logger.warning("DBSession: No run_id in context for get_items.")
            return [_msg_item("system", "Error: No active run context.")]

        plan_df = db_service.get_all_plan(run_id)
        plan_summary = "\n".join(f"Step {row['step_number']}: {row['status']}" for _, row in plan_df.iterrows())
        items: List[Dict] = [_msg_item("system", f"PROJECT STATUS (Run: {run_id}):\n{plan_summary}")]

        raw_messages: List[ChatMessage] = []
        if self.session_id.startswith("research_"):
            active_task = db_service.get_active_task(run_id)
            if active_task is not None:
                raw_messages.extend(db_service.get_messages_for_task(run_id, active_task))
            else:
                all_msgs = db_service.load_messages(run_id)
                raw_messages.extend(all_msgs[-10:])
        else: # planner, reporter, etc.
             all_msgs = db_service.load_messages(run_id)
             raw_messages.extend(m for m in all_msgs if m.session_id == self.session_id)

        if limit:
            raw_messages = raw_messages[-limit:]

        for m in raw_messages:
            role = str(m.role or "").strip()
            if not role: continue

            content = str(m.content or "")

            if role == "tool":
                call_id = m.tool_call_id
                if call_id:
                    items.append({"type": "function_call_output", "call_id": str(call_id), "output": content})
                continue

            if role in ("system", "user", "assistant"):
                tool_calls = m.tool_calls
                if role == "assistant" and tool_calls:
                    if isinstance(tool_calls, str):
                        try: tool_calls = json.loads(tool_calls)
                        except json.JSONDecodeError: tool_calls = []
                    
                    if content.strip(): items.append(_msg_item("assistant", content))

                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict): continue
                            func = tc.get("function", {})
                            name = func.get("name")
                            if tc.get("id") and name:
                                items.append({
                                    "type": "function_call", "call_id": str(tc["id"]), "name": str(name),
                                    "arguments": _as_json_str(func.get("arguments", "{}")),
                                })
                    continue
                
                if role == "assistant" and not content.strip(): continue
                items.append(_msg_item(role, content))
        
        logger.debug("DBSession(run=%s, session=%s): get_items returning %d items", run_id, self.session_id, len(items))
        return items

    async def add_items(self, items: List[Any]) -> None:
        run_id = current_run_id.get()
        if not run_id:
            logger.error("DBSession: No run_id in context for add_items. Cannot save messages.")
            return
            
        logger.debug("DBSession(run=%s, session=%s): add_items with %d items", run_id, self.session_id, len(items))

        for item in items:
            is_dict = isinstance(item, dict)
            role = item.get("role") if is_dict else getattr(item, "role", None)
            item_type = item.get("type") if is_dict else getattr(item, "type", None)

            if role is None:
                if item_type == "function_call_output": role = "tool"
                elif item_type == "function_call": role = "assistant"
                elif item_type == "function" or item_type == "tool_call_item":
                    # Standalone tool call items are redundant as they are already included 
                    # in the assistant message's tool_calls list.
                    logger.debug("DBSession: Skipping redundant tool call item. Type: %s", item_type)
                    continue
                else: role = "system"

            content_val = item.get("content") if is_dict else getattr(item, "content", None)
            if content_val is None and role == "tool":
                content_val = item.get("output") if is_dict else getattr(item, "output", None)

            content = "".join(b.get("text") for b in content_val if isinstance(b, dict) and b.get("text")) if isinstance(content_val, list) else str(content_val or "")

            tool_calls = item.get("tool_calls") if is_dict else getattr(item, "tool_calls", None)
            if tool_calls is None and item_type == "function_call":
                if item.get("id") and item.get("name"):
                    tool_calls = [{"id": item["id"], "type": "function", "function": {"name": item["name"], "arguments": _as_json_str(item.get("arguments"))}}]
            
            tool_call_id = item.get("tool_call_id") or item.get("call_id") or item.get("id") if is_dict else getattr(item, "tool_call_id", getattr(item, "call_id", getattr(item, "id", None)))
            sender = item.get("sender") or item.get("name") if is_dict else getattr(item, "sender", getattr(item, "name", None))

            # Ensure tool_call_id is a string and not empty if it exists
            final_call_id = None
            if tool_call_id:
                final_call_id = str(tool_call_id).strip()
                if not final_call_id:
                    final_call_id = None

            # Filter out empty system messages which are often side-effects of unhandled item types
            if role == "system" and not content and not tool_calls:
                logger.debug("DBSession: Skipping empty system message. Raw item type: %s", type(item))
                continue

            db_service.save_message(
                run_id=run_id, role=str(role), content=content,
                tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                tool_call_id=final_call_id,
                sender=str(sender) if sender else None, session_id=self.session_id
            )

    async def pop_item(self) -> dict | None:
        logger.warning("pop_item is deprecated in multi-run environment.")
        return None

    async def clear_session(self) -> None:
        run_id = current_run_id.get()
        if not run_id:
            logger.error("DBSession: No run_id, cannot clear session.")
            return
        with db_service.get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE run_id = ? AND session_id = ?", (run_id, self.session_id))
        logger.info("Cleared messages for run %s, session %s", run_id, self.session_id)
