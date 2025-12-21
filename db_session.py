import json
import logging
from typing import List, Optional, Any
from agents import Agent, Runner
try:
    from agents.memory import Session
except ImportError:
    # Fallback or try to find where Session is defined if the SDK structure is different
    # Based on README: "from agents.memory import Session"
    # But just in case, let's define the Protocol if we can't import it, 
    # though we really should rely on the library.
    from typing import Protocol, List, Dict
    class Session(Protocol):
        async def get_items(self, limit: int | None = None) -> List[dict]: ...
        async def add_items(self, items: List[dict]) -> None: ...
        async def pop_item(self) -> dict | None: ...
        async def clear_session(self) -> None: ...
import database

logger = logging.getLogger(__name__)

class DBSession(Session):
    """
    Adapter to persist agent conversation history to the existing SQLite database
    via the database.py module.
    """
    def __init__(self):
        # We don't really use session_id because the current DB is single-session/global
        # for this MVP.
        pass

    async def get_items(self, limit: int | None = None) -> List[dict]:
        """Retrieve conversation history."""
        messages = database.load_messages()
        
        cleaned = []
        for m in messages:
            role = m["role"]
            content = m["content"] or ""
            
            # 1. User/System/Developer
            if role in ("user", "system", "developer"):
                cleaned.append({
                    "role": role,
                    "content": content,
                    "name": m.get("sender"),
                })
            
            # 2. Assistant
            elif role == "assistant":
                # To ensure content and tool calls are merged into one message by the Converter,
                # we must use the internal 'ResponseOutputMessage' structure for content,
                # followed by 'function_call' items.
                
                # Emit content if present
                if content:
                    cleaned.append({
                        "type": "message",
                        "role": "assistant",
                        "content": [{
                            "type": "output_text",
                            "text": content
                        }],
                        "name": m.get("sender"),
                    })
                
                # Emit tool calls as separate items
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        # Handle both dict and object (though DB load should give dicts)
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            cleaned.append({
                                "type": "function_call",
                                "name": fn.get("name"),
                                "arguments": fn.get("arguments"),
                                "call_id": tc.get("id"),
                                "name": m.get("sender"), # Assign sender to tool call too if needed
                            })
                        else:
                            # Fallback if somehow not a dict (shouldn't happen with updated load_messages)
                            pass

            # 3. Tool Outputs
            elif role == "tool":
                cleaned.append({
                    "type": "function_call_output",
                    "call_id": m.get("tool_call_id"),
                    "output": content,
                    # Restore sender/name as it might be required by some backends or SDK logic
                    "name": m.get("sender"),
                })
                
        if limit is not None:
            return cleaned[-limit:]
        return cleaned

    async def add_items(self, items: List[Any]) -> None:
        """Store new items."""
        logger.debug(f"DBSession: add_items called with {len(items)} items")
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
                logger.debug(f"DBSession: Assigned virtual role '{role}' to item type {item_type}")

            logger.debug(f"DBSession: processing item role={role} type={item_type}")
            
            # --- Content Extraction ---
            raw_content = item.get("content") if is_dict else getattr(item, "content", None)
            
            # Handle 'output' field for tool outputs
            if raw_content is None and (item_type == "function_call_output" or role == "tool"):
                raw_content = item.get("output") if is_dict else getattr(item, "output", None)

            content = ""
            # Handle structured content
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
            
            # Special handling for 'function_call' item type (single tool call)
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
            
            # Convert tool calls to serializable list if it's an object
            if tool_calls and not isinstance(tool_calls, list):
                # If it's a single tool call object or something else
                tool_calls = [tool_calls]
            
            # Ensure tool calls are JSON serializable
            final_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        final_tool_calls.append(tc)
                    else:
                        # Try to convert object to dict
                        try:
                            # OpenAI objects usually have .dict() or can be converted
                            if hasattr(tc, "model_dump"):
                                final_tool_calls.append(tc.model_dump())
                            elif hasattr(tc, "dict"):
                                final_tool_calls.append(tc.dict())
                            else:
                                # Fallback for unknown objects
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

            # CRITICAL: Do NOT skip any items. The Runner needs the full history
            # of tool calls and outputs to maintain its internal state machine.
            database.save_message(
                role=str(role),
                content=content if content.strip() else None,
                tool_calls=final_tool_calls if final_tool_calls else None,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                sender=None if sender is None else str(sender),
            )

    async def pop_item(self) -> dict | None:
        """Remove and return the most recent item."""
        # Database module doesn't have a 'pop' method.
        # We'll have to implement a manual delete of the last record.
        # This is rarely used in standard flow but good to have for protocol compliance.
        
        # 1. Get last message
        messages = database.load_messages()
        if not messages:
            return None
        
        last_msg = messages[-1]
        
        # 2. Delete it (we need a new function in database.py or execute raw sql here)
        # Since we want to keep logic in database.py, let's just execute raw SQL here 
        # using the connection string from config, or add a method to database.py.
        # Adding a method to database.py is cleaner, but for now I'll direct SQL here
        # to avoid modifying database.py too much unless necessary.
        import sqlite3
        from config import DB_PATH
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Assuming ID is the primary key and highest ID is the last message
        c.execute("DELETE FROM messages WHERE id = (SELECT MAX(id) FROM messages)")
        conn.commit()
        conn.close()
        
        return last_msg

    async def clear_session(self) -> None:
        """Clear all items."""
        database.clear_messages()

