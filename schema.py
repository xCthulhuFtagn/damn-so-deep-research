from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ChatMessage(BaseModel):
    id: Optional[int] = None
    run_id: str
    role: str
    content: Optional[str] = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    sender: Optional[str] = None
    session_id: Optional[str] = 'default'
    task_number: Optional[int] = None
    timestamp: Optional[str] = None
