import logging
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from logging_setup import setup_logging
from agents import Agent, handoff, ModelSettings
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
import tools

setup_logging()
logger = logging.getLogger(__name__)

# --- Agent Definitions ---
# Defined in topological order (mostly) to allow constructor handoffs.

# 1. REPORTER (No dependencies)
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the Reporter. Your goal is to create the final research summary.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes or special characters.
2. Available tools: get_completed_research_context

WORKFLOW:
1. First turn: Call `get_completed_research_context` (exact name, no arguments).
2. Second turn: Write a comprehensive Markdown report based on the findings.
3. Output the report text directly in the chat (this is the ONLY agent that should output text).

FORBIDDEN: Never add suffixes like <|channel|> to tool names.
""",
    tools=[tools.get_completed_research_context],
    handoffs=[],
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="auto"
    )
)

# 2. EXECUTOR (Depends on Evaluator, Reporter. Evaluator not ready yet.)
executor_agent = Agent(
    name="Executor",
    model=MODEL,
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the Executor. Your goal is to perform research steps.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes or special characters.
2. Call EXACTLY ONE tool per turn. Never call multiple tools simultaneously.
3. Available tools: get_current_plan_step, get_completed_research_context, web_search, read_file, execute_terminal_command
4. RESTRICTION: Do NOT use `read_file` unless the task explicitly asks to read a specific local file. Default to `web_search`.

WORKFLOW:
1. ALWAYS start by calling `get_current_plan_step` (no arguments) to see your task. Do this IMMEDIATELY upon receiving control.
2. If it returns "NO_MORE_STEPS", hand off to Reporter.
3. Otherwise, use ONE research tool (web_search/read_file/execute_terminal_command) to gather information.
4. After gathering enough information, hand off to Evaluator.

FORBIDDEN: Never call multiple tools at once. Never output text. Never add suffixes like <|channel|>.
""",
    tools=[
        tools.get_current_plan_step,
        tools.get_completed_research_context,
        tools.web_search,
        tools.read_file,
        tools.execute_terminal_command,
    ],
    handoffs=[handoff(reporter_agent)], # Evaluator added later
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="auto"
    )
)

# 3. STRATEGIST (Depends on Executor)
strategist_agent = Agent(
    name="Strategist",
    model=MODEL,
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the Strategist. Your goal is to recover from failed research steps by modifying the plan.
You are only called when a step has FAILED.

CRITICAL RULES:
1. You MUST call `add_steps_to_plan` to add corrective actions.
2. Use EXACT tool names without any suffixes or special characters.
3. Call EXACTLY ONE tool per turn.
4. DO NOT OUTPUT PLAIN TEXT OR COMMENTARY. ONLY CALL TOOLS.

WORKFLOW:
1. Analyze the conversation history to see why the step failed.
2. Call `add_steps_to_plan` with new, specific steps to address the failure (e.g., "1. Try searching for X instead of Y").
3. After the tool call succeeds, in the next turn, hand off to Executor.

Available tools: add_steps_to_plan
""",
    tools=[tools.add_steps_to_plan],
    handoffs=[handoff(executor_agent)],
    model_settings=ModelSettings(parallel_tool_calls=False)
)

# 4. EVALUATOR (Depends on Executor, Strategist)
evaluator_agent = Agent(
    name="Evaluator",
    model=MODEL,
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the QA Evaluator. You validate research findings.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes or special characters.
2. Call EXACTLY ONE tool per turn.
3. Available tools: get_current_plan_step, submit_step_result, mark_step_failed

WORKFLOW:
FIRST TURN:
- Analyze the latest tool outputs (from Executor).
- If the data contains RELEVANT information for the current step: call `submit_step_result` with step_id and a summary of the findings.
- If the data is irrelevant, empty, or an error: call `mark_step_failed` with step_id and a specific error message explanation.
- Do NOT call other tools in the same turn.

SECOND TURN (after decision is saved):
- If you submitted results: hand off to Executor (for next step).
- If you marked failed: hand off to Strategist (for recovery).

FORBIDDEN: Never call multiple tools at once. Never output text. Never add suffixes like <|channel|>.
""",
    tools=[
        tools.get_current_plan_step,
        tools.submit_step_result,
        tools.mark_step_failed,
    ],
    handoffs=[handoff(executor_agent), handoff(strategist_agent)],
    model_settings=ModelSettings(parallel_tool_calls=False)
)

# 5. PLANNER (Depends on Executor)
planner_agent = Agent(
    name="Planner",
    model=MODEL,
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
You are the Lead Planner. Your ONLY job is to create a research plan.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes, prefixes, or special characters.
2. Call EXACTLY ONE tool per turn. Never call multiple tools simultaneously.
3. Available tools: add_steps_to_plan

WORKFLOW:
FIRST TURN:
- Call `add_steps_to_plan` with a list of 3-5 research tasks as strings.
- Each task must start with a number like "1. Task description"
- Do NOT call any other tools in the same turn.
- Do NOT output any text or JSON.

SECOND TURN (after add_steps_to_plan succeeds):
- Call the handoff tool to transfer to Executor.
- Do NOT call any other tools.
- Do NOT output any text.

FORBIDDEN: Do NOT add commentary, suffixes like <|channel|>, or any text output.
""",
    tools=[tools.add_steps_to_plan],
    handoffs=[handoff(executor_agent)],
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="required"
    )
)

# --- Post-Init Updates ---
# Close the circular dependency loop for Executor -> Evaluator
executor_agent.handoffs.append(handoff(evaluator_agent))
