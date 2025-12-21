# Changes Summary - Tool Name Sanitization & Handoff Fixes

## Date: 2025-12-21

## Problems Addressed

### 1. Model Hallucinating Tool Names
**Issue**: Model adds `<|channel|>` and other artifacts to tool names, causing "Tool not found" errors.

**Root Cause**: vLLM/DeepSeek models sometimes generate extra tokens after tool names.

**Solution**: Enhanced monkey patch (v3 → v4) with:
- Regex-based aggressive cleaning: `tool_name<|anything>` → `tool_name`
- Early interception in `process_model_response`
- Multi-layer sanitization (objects, dicts, ModelResponse items)

### 2. Agent Outputting Text Instead of Calling Tools
**Issue**: Planner outputs numbered list in chat instead of using `add_steps_to_plan`.

**Root Cause**: Ambiguous instructions that suggested waiting but also prohibited text output.

**Solution**: Rewrote all agent instructions with:
- Explicit turn-by-turn workflows
- "FIRST TURN: Call X" / "SECOND TURN: Call Y" structure
- Clear prohibition of text output (except Reporter)
- Explicit tool name listings

### 3. Parallel Tool Calls Attempts
**Issue**: Model tries to call multiple tools despite `parallel_tool_calls=False`.

**Root Cause**: Instructions implied sequential but didn't explicitly prohibit parallel calls.

**Solution**: 
- Added "Call EXACTLY ONE tool per turn" to all agents
- Reinforced in CRITICAL RULES section
- Kept `parallel_tool_calls=False` at both global and agent levels

## Files Modified

### 1. `research_agents.py`
**Changes**:
- ✅ Rewrote all 5 agent instructions with strict single-tool-per-turn rules
- ✅ Added CRITICAL RULES section to each agent
- ✅ Added explicit tool name lists
- ✅ Added "FORBIDDEN" section listing what NOT to do
- ✅ Enhanced handoff function docstrings

**Agents Updated**:
- Planner: Clear 2-turn workflow
- Executor: Sequential research workflow  
- Evaluator: 2-turn evaluation workflow
- Strategist: 2-turn recovery workflow
- Reporter: Research summary workflow

### 2. `main.py`
**Changes**:
- ✅ Upgraded monkey patch from v3 to v4
- ✅ Added `TOOL_NAME_ARTIFACT_PATTERN` regex
- ✅ Created `_clean_tool_name()` helper function
- ✅ More robust error handling with `exc_info=True`
- ✅ Better logging messages

**Monkey Patch Features**:
- Detects patterns like `tool_name<|channel|>commentary`
- Extracts base tool name before `<|` character
- Works across multiple response formats (OpenAI, agents library, etc.)

### 3. `runner.py`
**Changes**:
- ✅ Added comment clarifying global vs. agent settings
- ✅ Confirmed `parallel_tool_calls=False` is set globally

### 4. New Files
- ✅ `TROUBLESHOOTING.md`: Comprehensive debugging guide
- ✅ `CHANGES.md`: This file

## Technical Details

### Monkey Patch Architecture

```python
# Flow:
1. Model generates response with tool calls
2. Response enters process_model_response() 
3. Monkey patch intercepts BEFORE validation
4. _clean_tool_name() strips artifacts using regex
5. Clean response proceeds to validation
6. Tool lookup succeeds with correct name
```

### Key Regex Pattern
```python
TOOL_NAME_ARTIFACT_PATTERN = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)<\|.*$')
```
Captures: `transfer_to_executor` from `transfer_to_executor<|channel|>commentary`

### Agent Instruction Pattern
```
CRITICAL RULES:
1. Use EXACT tool names
2. Call EXACTLY ONE tool per turn
3. Available tools: [explicit list]

WORKFLOW:
FIRST TURN: Call X
SECOND TURN: Call Y

FORBIDDEN: [explicit don'ts]
```

## Testing Recommendations

1. **Test Planner Flow**:
   ```
   Input: "research Napoleon Bonaparte"
   Expected: 
   - Turn 1: add_steps_to_plan called
   - Turn 2: transfer_to_executor called
   - No text output in chat
   ```

2. **Monitor Logs**:
   ```bash
   LOG_LEVEL=DEBUG streamlit run main.py
   ```
   Look for:
   - `✅ Applied MonkeyPatch (v4)`
   - No `🔧 Cleaned tool name` (ideal case)
   - Or see cleaning in action (fallback working)

3. **Check Agent Transitions**:
   - DB messages should show clean handoffs
   - No errors about "Tool not found"
   - Each agent calls one tool per turn

## Configuration Validation

### ✅ Confirmed Settings

**Global (runner.py)**:
- `parallel_tool_calls=False` ✓
- `temperature=0.0` ✓
- `tool_choice="auto"` ✓

**Per Agent**:
- Planner: `parallel_tool_calls=False`, `tool_choice="required"` ✓
- Executor: `parallel_tool_calls=False`, `tool_choice="auto"` ✓
- Evaluator: `parallel_tool_calls=False` ✓
- Strategist: `parallel_tool_calls=False` ✓
- Reporter: `parallel_tool_calls=False` ✓

## Known Limitations

1. **Model-Specific Behavior**: Some models may still try to hallucinate despite best efforts.
2. **Monkey Patch Overhead**: Small performance cost for regex matching on every response.
3. **Instruction Compliance**: Weaker models may ignore turn-by-turn structure.

## Rollback Plan

If these changes cause issues:

1. **Revert Agent Instructions**:
   ```bash
   git checkout HEAD~1 research_agents.py
   ```

2. **Disable Monkey Patch**:
   Comment out lines 37-117 in `main.py`

3. **Check Model Compatibility**:
   Switch to `gpt-4o` or another known-good model

## Next Steps

1. Test with actual queries
2. Monitor logs for any remaining artifacts
3. Fine-tune instructions based on model behavior
4. Consider adding model-specific instruction variants
5. Document working model configurations

## Questions to Address

- What model are you using? (Check `.env` → `OPENAI_MODEL`)
- Is it vLLM-served or official OpenAI API?
- Do you see `🔧 Cleaned tool name` messages in logs?
- Are handoffs working now?

## Success Criteria

✅ No `<|channel|>` artifacts in error messages
✅ Planner creates plan via tool call (not text output)
✅ Successful handoffs between agents
✅ Each agent calls one tool per turn
✅ No "Tool not found" errors

