import threading
import logging
import time
from typing import Optional
from agents import Runner, Agent, RunConfig, ModelSettings
from agents.models.openai_provider import OpenAIProvider
import database
from db_session import DBSession
from config import MAX_TURNS, OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger(__name__)

class SwarmRunner:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None

    def run_in_background(self, agent: Agent, input_text: str, max_turns: int = MAX_TURNS):
        """Starts the swarm execution in a background thread."""
        if database.is_swarm_running():
            logger.warning("Swarm is already running. Cannot start another instance.")
            return

        database.set_swarm_running(True)
        database.set_stop_signal(False)
        
        self.thread = threading.Thread(
            target=self._run_wrapper,
            args=(agent, input_text, max_turns),
            daemon=True
        )
        self.thread.start()
        logger.info("Swarm background thread started with max_turns=%d", max_turns)

    def _run_wrapper(self, agent: Agent, input_text: str, max_turns: int):
        """Wrapper to run the synchronous Runner in a thread."""
        try:
            logger.info("Starting Runner.run_sync with input length: %s", len(input_text) if input_text else 0)
            
            # Create the session adapter
            session = DBSession()

            # vLLM-friendly configuration:
            # 1. We use standard OpenAIProvider.
            # 2. We use 'stop' sequences to cut off vLLM garbage like <|channel|>...
            # 3. We disable 'use_responses' as vLLM usually only supports Chat Completions.
            def vllm_provider_wrapper(provider):
                original_get_model = provider.get_model
                def patched_get_model(model_name=None):
                    model = original_get_model(model_name)
                    original_get_response = model.get_response
                    
                    async def patched_get_response(*args, **kwargs):
                        if 'input' in kwargs and isinstance(kwargs['input'], list):
                            for msg in kwargs['input']:
                                if isinstance(msg, dict) and msg.get('role') == 'user' and 'name' in msg:
                                    del msg['name']

                        response = await original_get_response(*args, **kwargs)
                        
                        logger.info(f"DEBUG: Response output type: {type(response.output) if response and hasattr(response, 'output') else 'No output'}")
                        if response and hasattr(response, 'output'):
                            for i, item in enumerate(response.output):
                                logger.info(f"DEBUG: Item {i} type: {type(item)}")
                                logger.info(f"DEBUG: Item {i} vars: {vars(item) if hasattr(item, '__dict__') else item}")

                        def _clean_str(s):
                            if isinstance(s, str) and '<|' in s:
                                cleaned = s.split('<|')[0]
                                logger.info(f"✨ [VLLM FIX] Cleaned '{s}' -> '{cleaned}'")
                                return cleaned
                            return s

                        if response and hasattr(response, 'output'):
                            for item in response.output:
                                # Helper to get attr or dict value
                                def get_val(obj, key):
                                    return getattr(obj, key, None) or (obj.get(key) if isinstance(obj, dict) else None)

                                item_text = get_val(item, 'text')
                                
                                # 1. Ремонт: если vLLM выдала JSON текстом вместо tool_call
                                if item_text and ('"name":' in item_text or '"arguments":' in item_text):
                                    try:
                                        import json
                                        import re
                                        # Пытаемся найти JSON внутри текста
                                        # Use a loop to find the largest valid JSON object if greedy fails
                                        # But first try the simple greedy match which usually works if only JSON is present
                                        json_match = re.search(r'(\{.*\})', item_text, re.DOTALL)
                                        # Check for multiple JSONs concatenated
                                        json_pattern = r'(\{(?:[^{}]|(?R))*\})' 
                                        # Simple recursive matching isn't supported by re, using balanced brace heuristic or just greedy
                                        # But simple regex for JSON object is hard. Let's rely on the fact that they are distinct objects
                                        
                                        # If we didn't find a single clear JSON, or if we want to support multiple:
                                        # Let's try to parse the whole string as a sequence of JSON objects
                                        try:
                                            # Quick hack: try to decode as much as possible
                                            idx = 0
                                            valid_objects = []
                                            dec = json.JSONDecoder()
                                            while idx < len(item_text):
                                                item_text_slice = item_text[idx:].strip()
                                                if not item_text_slice: break
                                                try:
                                                    obj, end = dec.raw_decode(item_text_slice)
                                                    valid_objects.append(obj)
                                                    idx += end
                                                except json.JSONDecodeError:
                                                    # Skip garbage until next brace
                                                    next_brace = item_text_slice.find('{')
                                                    if next_brace == -1: break
                                                    idx += next_brace
                                                    # If we are stuck at the same brace, skip it
                                                    if next_brace == 0: idx += 1
                                            
                                            if valid_objects:
                                                 # We found valid objects. If there are multiple tool calls, we have a problem:
                                                 # The current loop processes one `item`. We can't easily expand it into multiple items here
                                                 # without modifying `response.output` in place which is risky while iterating.
                                                 # However, usually the first one is the most important or we can try to merge.
                                                 # But for "add_steps" and "transfer", we need both.
                                                 
                                                 # Workaround: If we find multiple, we pick the first one to assign to THIS item,
                                                 # and we append new items to `response.output` for the others.
                                                 # `response.output` is a list, so we can append to it.
                                                 
                                                 for i, data in enumerate(valid_objects):
                                                     if isinstance(data, dict) and 'name' in data and 'arguments' in data:
                                                         logger.info(f"🛠️ [VLLM REPAIR] Found text JSON tool call #{i+1}: {data['name']}")
                                                         from agents.tools import ToolCall
                                                         new_tc = ToolCall(
                                                            id=f"repair-{int(time.time())}-{i}",
                                                            name=_clean_str(data['name']),
                                                            arguments=data['arguments'] if isinstance(data['arguments'], str) else json.dumps(data['arguments'])
                                                         )
                                                         
                                                         if i == 0:
                                                             # Replace current item
                                                             if isinstance(item, dict):
                                                                 item['tool_call'] = new_tc
                                                                 item['text'] = None
                                                             else:
                                                                 item.tool_call = new_tc
                                                                 item.text = None
                                                         else:
                                                             # Append new item to response.output
                                                             # We need to construct a new item of the same type as `item` ideally
                                                             # But for now, let's assume it's okay to append a generic object or dict
                                                             # equivalent to the current one.
                                                             
                                                             # Clone item structure
                                                             import copy
                                                             if isinstance(item, dict):
                                                                 new_item = copy.copy(item)
                                                                 new_item['tool_call'] = new_tc
                                                                 new_item['text'] = None
                                                                 response.output.append(new_item)
                                                             else:
                                                                 # Try to clone object
                                                                 try:
                                                                     new_item = copy.copy(item)
                                                                     new_item.tool_call = new_tc
                                                                     new_item.text = None
                                                                     response.output.append(new_item)
                                                                 except:
                                                                     logger.warning("Could not clone item for multi-tool repair")
                                        except Exception as parse_e:
                                            logger.debug(f"Deep parse failed: {parse_e}")

                                    except Exception as e:
                                        logger.debug(f"Failed to repair JSON text: {e}")

                                # 2. SDK level
                                tc = get_val(item, 'tool_call')
                                if tc:
                                    # Check direct name
                                    tc_name = getattr(tc, 'name', None) or (tc.get('name') if isinstance(tc, dict) else None)
                                    if tc_name:
                                        clean = _clean_str(tc_name)
                                        if hasattr(tc, 'name'): 
                                            tc.name = clean
                                        elif isinstance(tc, dict): 
                                            tc['name'] = clean
                                    
                                    # Check function.name (OpenAI format)
                                    fn = getattr(tc, 'function', None) or (tc.get('function') if isinstance(tc, dict) else None)
                                    if fn:
                                        fn_name = getattr(fn, 'name', None) or (fn.get('name') if isinstance(fn, dict) else None)
                                        if fn_name:
                                            clean = _clean_str(fn_name)
                                            if hasattr(fn, 'name'): 
                                                fn.name = clean
                                            elif isinstance(fn, dict): 
                                                fn['name'] = clean
                                
                                # 3. Raw OpenAI level
                                raw = get_val(item, 'raw_item')
                                if raw:
                                    msg = getattr(raw, 'message', None) or (raw.get('message') if isinstance(raw, dict) else None)
                                    tcs = getattr(msg, 'tool_calls', None) or (msg.get('tool_calls') if isinstance(msg, dict) else None)
                                    if not tcs:
                                        tcs = getattr(raw, 'tool_calls', None) or (raw.get('tool_calls') if isinstance(raw, dict) else None)
                                    
                                    if tcs:
                                        for rtc in tcs:
                                            fn = getattr(rtc, 'function', None) or (rtc.get('function') if isinstance(rtc, dict) else None)
                                            if fn:
                                                fn_name = getattr(fn, 'name', None) or (fn.get('name') if isinstance(fn, dict) else None)
                                                if fn_name:
                                                    clean_fn_name = _clean_str(fn_name)
                                                    if hasattr(fn, 'name'): fn.name = clean_fn_name
                                                    elif isinstance(fn, dict): fn['name'] = clean_fn_name

                                # 4. Direct tool call object (OpenAI types)
                                if hasattr(item, 'name') and hasattr(item, 'arguments'):
                                     item_name = getattr(item, 'name', None)
                                     if item_name:
                                        clean = _clean_str(item_name)
                                        item.name = clean
                                elif isinstance(item, dict) and 'name' in item and 'arguments' in item:
                                     item['name'] = _clean_str(item['name'])

                        return response
                    
                    model.get_response = patched_get_response
                    return model
                provider.get_model = patched_get_model
                return provider

            run_config = RunConfig(
                model_provider=vllm_provider_wrapper(OpenAIProvider(
                    api_key=OPENAI_API_KEY,
                    base_url=OPENAI_BASE_URL,
                    use_responses=False,
                )),
                tracing_disabled=True,
                model_settings=ModelSettings(
                    temperature=0.0,
                    parallel_tool_calls=False, # Disable for better stability on vLLM
                    tool_choice="auto",
                ),
            )
            
            # The Runner will handle the loop, tool calls, and state updates (via session)
            result = Runner.run_sync(
                agent,
                input=input_text,
                session=session,
                max_turns=max_turns,
                run_config=run_config,
            )
            
            logger.info("Runner finished. Final output chars: %s", len(result.final_output) if result.final_output else 0)
            
        except Exception as e:
            logger.exception("Error in swarm background thread: %s", e)
            database.save_message("system", f"Error in background runner: {str(e)}")
        finally:
            database.set_swarm_running(False)
            logger.info("Swarm background thread finished.")

# Global instance
runner = SwarmRunner()
