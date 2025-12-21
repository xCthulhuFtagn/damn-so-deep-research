import logging
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from logging_setup import setup_logging
from agents import Agent, function_tool, ModelSettings
import tools

setup_logging()
logger = logging.getLogger(__name__)

# --- Handoff Functions ---
# We define them as tools that return the target Agent.
# We must use lazy lookup or rely on Python's late binding for the return values.

@function_tool(name_override="transfer_to_executor")
def transfer_to_executor():
    """Hand off control to the Executor agent."""
    return executor_agent

@function_tool(name_override="transfer_to_evaluator")
def transfer_to_evaluator():
    """Hand off control to the Evaluator agent."""
    return evaluator_agent

@function_tool(name_override="transfer_to_strategist")
def transfer_to_strategist():
    """Hand off control to the Strategist agent."""
    return strategist_agent

@function_tool(name_override="transfer_to_reporter")
def transfer_to_reporter():
    """Hand off control to the Reporter agent."""
    return reporter_agent

@function_tool(name_override="transfer_to_planner")
def transfer_to_planner():
    """Hand off control to the Planner agent."""
    return planner_agent

# --- Agent Definitions ---

# 1. PLANNER
planner_agent = Agent(
    name="Planner",
    model=MODEL,
    instructions="""You are the Lead Planner. 
Your goal is ONLY to create a research plan and then IMMEDIATELY hand off control.

1. Create 3-5 tasks using `add_steps_to_plan`.
2. Hand off control to the Executor using `transfer_to_executor`.

IMPORTANT:
- You must perform BOTH tool calls in the same turn.
- Your response MUST consist ONLY of tool calls.
- Do NOT output any JSON text or thoughts outside of tool calls.
""",
    tools=[tools.add_steps_to_plan, transfer_to_executor],
    handoffs=[transfer_to_executor],
    model_settings=ModelSettings(
        parallel_tool_calls=True, # Enable to allow plan + handoff in one go
        tool_choice="required"
    )
)

# 2. EXECUTOR
executor_agent = Agent(
    name="Executor",
    model=MODEL,
    instructions="""You are the Executor. Your goal is to perform research steps.

FLOW:
1. Call `get_current_plan_step` to see your task.
2. If all steps are done, hand off control to the Reporter.
3. Use research tools to find information.
4. After gathering findings, IMMEDIATELY call `transfer_to_evaluator`.

RULES:
- Your response must be ONLY a tool call.
- Do not add any thoughts, comments, or text.
""",
    tools=[
        tools.get_current_plan_step,
        tools.get_completed_research_context,
        tools.web_search,
        tools.read_file,
        tools.execute_terminal_command,
        transfer_to_evaluator,
        transfer_to_reporter
    ],
    handoffs=[transfer_to_evaluator, transfer_to_reporter],
    model_settings=ModelSettings(
        parallel_tool_calls=True,
        tool_choice="auto"
    )
)

# 3. EVALUATOR
evaluator_agent = Agent(
    name="Evaluator",
    model=MODEL,
    instructions="""You are the QA Evaluator.

1. If the research data is valid, call `submit_step_result` and then MUST hand off control back to the Executor for the next step using `transfer_to_executor`.
2. If the data is bad, call `mark_step_failed` and hand off control to the Strategist using `transfer_to_strategist`.

RULES:
- You must ALWAYS call a handoff tool after making your decision.
- NEVER respond with plain text alone.
""",
    tools=[
        tools.get_current_plan_step,
        tools.submit_step_result,
        tools.mark_step_failed,
        transfer_to_executor,
        transfer_to_strategist
    ],
    handoffs=[transfer_to_executor, transfer_to_strategist],
    model_settings=ModelSettings(parallel_tool_calls=True)
)

# 4. STRATEGIST
strategist_agent = Agent(
    name="Strategist",
    model=MODEL,
    instructions="""You are the Strategist.

1. Analyze why a step failed and update the plan using `add_steps_to_plan`.
2. After updating the plan, hand off control back to the Executor using `transfer_to_executor`.

RULES:
- NEVER respond with plain text summarizing your plan changes.
- You MUST call the handoff tool to the Executor to continue the workflow.
""",
    tools=[tools.add_steps_to_plan, transfer_to_executor],
    handoffs=[transfer_to_executor],
    model_settings=ModelSettings(parallel_tool_calls=True)
)

# 5. REPORTER
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions="""You are the Reporter. Your goal is to create the final research summary.

1. Call `get_completed_research_context` to get all confirmed findings.
2. Write a comprehensive Markdown report based on these findings.
3. Output the report text directly in the chat.
""",
    tools=[tools.get_completed_research_context],
    model_settings=ModelSettings(tool_choice="auto")
)
