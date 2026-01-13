import logging
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from logging_setup import setup_logging
from agents import Agent, handoff, ModelSettings
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from tools.reporting import get_research_summary, submit_step_result, mark_step_failed, get_recovery_context
from tools.planning import get_current_plan_step, add_steps_to_plan, insert_corrective_steps
from tools.search import intelligent_web_search
from tools.execution import read_file, execute_terminal_command, answer_from_knowledge, ask_user, ask_user

setup_logging()
logger = logging.getLogger(__name__)

# --- Agent Definitions ---

# 1. REPORTER
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the Reporter. Your goal is to create the final research summary on the same language as the original request.

CRITICAL RULES:
1. Use EXACT tool names without any suffixes.
2. Available tools: get_research_summary
3. WORKFLOW:
   - First turn: Call `get_research_summary` (exact name, no arguments).
   - Second turn: Write a comprehensive Markdown report based on the findings provided by the tool.
   - The report MUST end with author attribution to "damn-so-deep-research" as the last line.
   - Output the report text directly.

FORBIDDEN: Do not add suffixes like <|channel|> to tool names.
""",
    tools=[get_research_summary],
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
3. Available tools: get_current_plan_step, intelligent_web_search, read_file, answer_from_knowledge, ask_user
4. RESTRICTION: Do NOT use `read_file` unless the task explicitly asks to read a specific local file. NEVER use it for URLs (http/https).
5. RESTRICTION: Limit `intelligent_web_search` calls to a maximum of 3 times.
6. EMERGENCY ONLY: Use `ask_user` ONLY in critical situations when you cannot proceed without user clarification. This is an emergency tool.

WORKFLOW:
1. ALWAYS start by calling `get_current_plan_step`.
2. If it returns "NO_MORE_STEPS": Call `answer_from_knowledge("Research Complete")`.
3. Otherwise, use research tools:
   - Call `intelligent_web_search` with your query if the task is very specific and you need to search the web to find the information for it.
   - Call `answer_from_knowledge` if the question is quite simple and you can answer it yourself or if the previously called research tools in this step have provided information from which a SHORT USEFUL INSIGHT can be drawn.
4. When you have enough information for the CURRENT step, hand off to Evaluator.

FORBIDDEN: You must NEVER output raw text. Do NOT output JSON strings. ALWAYS use a tool. If you need to signal completion, use `answer_from_knowledge` with the answer as the argument.
""",
    tools=[
        get_current_plan_step,
        intelligent_web_search,
        read_file,
        answer_from_knowledge,
        ask_user,
    ],
    handoffs=[], # Will be updated with Evaluator below
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
1. When a step fails, you MUST insert intermediate corrective steps BEFORE moving to the rest of the original plan.
2. Use `insert_corrective_steps` to inject new tasks immediately after the failed step. This shifts old future steps down.
3. FORBIDDEN: Do NOT add reporting, summarization, or synthesis steps. The final report is generated automatically by the Reporter.
4. NAMING CONVENTION: Corrective steps MUST be named 'Previous task [Task Name] failed because [Reason], so [New Action]'.
5. EMERGENCY ONLY: Use `ask_user` ONLY in critical situations when you cannot proceed without user clarification. This is an emergency tool.

WORKFLOW:
1. CHECK HISTORY: Call `get_recovery_context` ONLY IF you do not already see the recovery context in the chat history. If present, skip this.
2. Analyze the context provided to you to determine the corrective steps.
3. Call `insert_corrective_steps` with specific corrective steps.
4. STOP. Do NOT output any text after calling the tool.

Available tools: insert_corrective_steps, get_recovery_context, ask_user

FORBIDDEN: You must NEVER output raw text. Do NOT output JSON strings. ALWAYS use a tool.
""",
    tools=[
        get_recovery_context,
        insert_corrective_steps,
        ask_user
    ],
    handoffs=[], # No handoffs, returns to Runner to pick up new steps
    model_settings=ModelSettings(
        parallel_tool_calls=False, 
        tool_choice="required"
    )
)

# 4. EVALUATOR
evaluator_agent = Agent(
    name="Evaluator",
    model=MODEL,
    instructions=f"""
{RECOMMENDED_PROMPT_PREFIX}
You are the QA Evaluator. You validate research findings.

CRITICAL RULES:
1. Use EXACT tool names. Do NOT add suffixes like `<|channel|>` or `commentary`.
2. Available tools: submit_step_result, mark_step_failed

WORKFLOW:
1. Analyze the latest tool outputs from Executor.
2. DECISION:
   - IF VALID: 
     a) Call `submit_step_result` with the step_id and findings.
     b) STOP. Do NOT output any text after this.
   - IF FAILED/EMPTY: 
     a) Call `mark_step_failed` with the error.
     b) THEN (next turn): Hand off to Strategist.

FORBIDDEN: You must NEVER output raw text. Do NOT output JSON strings. ALWAYS use a tool.
""",
    tools=[
        get_current_plan_step, # Useful to confirm ID
        submit_step_result,
        mark_step_failed,
    ],
    handoffs=[handoff(strategist_agent)],
    model_settings=ModelSettings(
        parallel_tool_calls=False, 
        tool_choice="required"
    )
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
3. Available tools: add_steps_to_plan, ask_user
4. IMPORTANT: Plan steps should focus on actionable research tasks.
5. ISOLATION: Each step must be a fully self-contained research task. They should not rely on information from previous steps.
6. FORBIDDEN: Do NOT include ANY steps for "generating report", "summarizing findings", "compiling results", or "creating summary".
   - The final report is generated automatically by a separate Reporter agent after all steps are completed.
   - Your plan must ONLY contain research and investigation steps.
7. EMERGENCY ONLY: Use `ask_user` ONLY in critical situations when you cannot proceed without user clarification. This is an emergency tool.

WORKFLOW:
1. Call `add_steps_to_plan` with a list of 3-10 clear and actionable research tasks. 
2. In the next turn return "Plan Created".
""",
    tools=[add_steps_to_plan, ask_user],
    handoffs=[], # No handoffs, returns to Runner
    model_settings=ModelSettings(
        parallel_tool_calls=False,
        tool_choice="required"
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
