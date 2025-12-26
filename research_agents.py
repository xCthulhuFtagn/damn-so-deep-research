import logging
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from logging_setup import setup_logging
from agents import Agent, handoff, ModelSettings
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
import tools

setup_logging()
logger = logging.getLogger(__name__)

# --- Agent Definitions ---

# 1. REPORTER
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the Reporter. Your goal is to create the final research summary.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes.
2. Available tools: get_research_summary

WORKFLOW:
1. First turn: Call `get_research_summary` (exact name, no arguments).
2. Second turn: Write a comprehensive Markdown report based on the findings provided by the tool.
3. Output the report text directly.

FORBIDDEN: Do not add suffixes like <|channel|> to tool names.
""",
    tools=[tools.get_research_summary],
    handoffs=[], # No handoffs, Runner handles completion
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="auto"
    )
)

# 2. EXECUTOR
executor_agent = Agent(
    name="Executor",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the Executor. Your goal is to perform research steps.

CRITICAL RULES:
1. Use EXACT tool names.
2. Call EXACTLY ONE tool per turn.
3. Available tools: get_current_plan_step, intelligent_web_search, summary, read_file, execute_terminal_command, answer_from_knowledge
4. RESTRICTION: Do NOT use `read_file` unless the task explicitly asks to read a specific local file.
5. RESTRICTION: Limit `intelligent_web_search` calls to a maximum of 3 per research step, includinng curl in terminal commands.

WORKFLOW:
1. ALWAYS start by calling `get_current_plan_step`.
2. If it returns "NO_MORE_STEPS": Output "Research Complete".
3. Otherwise, use research tools:
   - Call `intelligent_web_search` with your query if the task is very specific and you need to search the web to find the information for it.
   - Call `execute_terminal_command` if the task requires you to execute a terminal command.
   - Call `answer_from_knowledge` if the question is quite simple and you can answer it yourself or if the previously called research tools in this step have provided information from which a SHORT USEFUL INSIGHT can be drawn.
4. When you have enough information for the CURRENT step, hand off to Evaluator.

FORBIDDEN: Never output text unless finishing.
""",
    tools=[
        tools.get_current_plan_step,
        tools.intelligent_web_search,
        tools.read_file,
        tools.execute_terminal_command,
        tools.answer_from_knowledge,
    ],
    handoffs=[handoff(reporter_agent)], # Will be updated with Evaluator below
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="required"
    )
)

# 3. STRATEGIST
strategist_agent = Agent(
    name="Strategist",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the Strategist. Your goal is to recover from failed research steps.

CRITICAL RULES:
1. You MUST call `add_steps_to_plan` to add corrective actions.
2. Use EXACT tool names.
3. IMPORTANT: Corrective steps should focus on actionable research tasks to fix the failure.
4. FORBIDDEN: Do NOT add steps like "generate report", "summarize findings", or "create summary" as corrective actions. Reporting and summarization MUST only occur at the very end of the overall research process.

WORKFLOW:
1. Analyze the context (the system will provide the failure details).
2. Call `add_steps_to_plan` with specific corrective steps.
3. In the next turn, hand off to Executor to try again.

Available tools: add_steps_to_plan, get_recovery_context
""",
    tools=[
        tools.add_steps_to_plan,
        tools.get_recovery_context
    ],
    handoffs=[handoff(executor_agent)],
    model_settings=ModelSettings(parallel_tool_calls=False, tool_choice="required")
)

# 4. EVALUATOR
evaluator_agent = Agent(
    name="Evaluator",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the QA Evaluator. You validate research findings.

CRITICAL RULES:
1. Use EXACT tool names.
2. Available tools: submit_step_result, mark_step_failed

WORKFLOW:
1. Analyze the latest tool outputs from Executor.
2. DECISION:
   - IF VALID: 
     a) Call `submit_step_result` with the step_id and findings.
     b) THEN (next turn): Output "Step Verified" to finish the step.
   - IF FAILED/EMPTY: 
     a) Call `mark_step_failed` with the error.
     b) THEN (next turn): Hand off to Strategist.

FORBIDDEN: Do not output text UNLESS the step is valid and you are finishing.
""",
    tools=[
        tools.get_current_plan_step, # Useful to confirm ID
        tools.submit_step_result,
        tools.mark_step_failed,
    ],
    handoffs=[handoff(executor_agent), handoff(strategist_agent)],
    model_settings=ModelSettings(parallel_tool_calls=False, tool_choice="required")
)

# 5. PLANNER
planner_agent = Agent(
    name="Planner",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the Lead Planner. Your ONLY job is to create a research plan.

CRITICAL RULES:
1. Use EXACT tool names.
2. Call EXACTLY ONE tool per turn.
3. Available tools: add_steps_to_plan
4. IMPORTANT: Plan steps should focus on actionable research tasks.
5. FORBIDDEN: Do NOT include steps like "generate report", "summarize findings", or "create summary" in the intermediate steps of the plan. Reporting and summarization MUST only occur as the very last step.

WORKFLOW:
1. Call `add_steps_to_plan` with a list of 3-10 clear and actionable research tasks. "
"Generate the final research report step should not be included in the plan, it is done by the Reporter agent by himself".
2. In the next turn, output "Plan Created".

FORBIDDEN: Do not hand off. Do not add commentary.
""",
    tools=[tools.add_steps_to_plan],
    handoffs=[], # No handoffs, returns to Runner
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="auto" # Can output text
    )
)

# --- Post-Init Updates ---
# Close the circular dependency loop for Executor -> Evaluator
# Also remove Reporter handoff from Executor (it was placeholder)
executor_agent.handoffs = [handoff(evaluator_agent)]

# --- Helper: resolve agent by name (for recovery logic) ---
_AGENT_MAP = {
    "Planner": planner_agent,
    "Executor": executor_agent,
    "Evaluator": evaluator_agent,
    "Reporter": reporter_agent,
    "Strategist": strategist_agent,
}


def get_agent_by_name(name: str):
    """
    Resolve agent object by its name (as stored in DB sender field or error text).
    Returns None if not found.
    """
    if not name:
        return None
    return _AGENT_MAP.get(name)
