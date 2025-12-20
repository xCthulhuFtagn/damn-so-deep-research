from openai import OpenAI
from swarm import Swarm, Agent
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
import tools
import logging

from logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

custom_client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)
client = Swarm(client=custom_client)
logger.info(
    "Agents initialized: model=%s base_url=%s",
    MODEL,
    "custom" if OPENAI_BASE_URL else "default",
)

# --- Handoff Functions ---
def transfer_to_executor(**kwargs): return executor_agent
def transfer_to_evaluator(**kwargs): return evaluator_agent
def transfer_to_strategist(**kwargs): return strategist_agent
def transfer_to_reporter(**kwargs): return reporter_agent

# --- Agent Definitions ---

# 1. PLANNER
planner_agent = Agent(
    name="Planner",
    model=MODEL,
    instructions="""You are the Lead Planner.
GOAL: Create a research plan based on the user's request.

INSTRUCTIONS:
1. Analyze the user's request.
2. Create a list of 5-10 specific, actionable research steps.
3. CALL THE FUNCTION `add_steps_to_plan` with these steps.
4. DO NOT output the plan as text/markdown. ONLY call the function.
5. After adding steps, call `transfer_to_executor` to start the work.
""",
    functions=[tools.add_steps_to_plan, transfer_to_executor],
    tool_choice="required",
)

# 2. EXECUTOR
executor_agent = Agent(
    name="Executor",
    model=MODEL,
    instructions="""Ты - Исследователь (Executor).
    1. Сначала вызови `get_current_plan_step`, чтобы узнать задачу.
    2. Если ответ "NO_MORE_STEPS" -> передай управление Репортеру (Reporter).
    3. Вызови `get_completed_research_context`, чтобы узнать, что мы уже нашли (чтобы не повторяться).
    4. Выполни задачу, используя поиск, файлы или терминал.
    5. Если инструмент требует одобрения (терминал), сообщи пользователю.
    6. Когда данные получены, передай управление Оценщику (Evaluator). НЕ сохраняй результат сам, просто передай контекст.
    """,
    functions=[
        tools.get_current_plan_step,
        tools.get_completed_research_context,
        tools.web_search,
        tools.read_file,
        tools.execute_terminal_command,
        transfer_to_evaluator,
        transfer_to_reporter
    ],
    tool_choice="required",
)

# 3. EVALUATOR
evaluator_agent = Agent(
    name="Evaluator",
    model=MODEL,
    instructions="""Ты - QA Оценщик.
    Ты получаешь результат от Исполнителя.
    1. Проверь валидность данных для текущего шага плана.
    2. Если данные ОК:
       - Вызови `submit_step_result` (это запишет данные в БД).
       - Передай управление Исполнителю (Executor) для следующего шага.
    3. Если данные плохие или шаг провален:
       - Вызови `mark_step_failed`.
       - Передай управление Стратегу (Strategist).
    """,
    functions=[
        tools.get_current_plan_step,
        tools.submit_step_result,
        tools.mark_step_failed,
        transfer_to_executor,
        transfer_to_strategist
    ],
    tool_choice="required",
)

# 4. STRATEGIST
strategist_agent = Agent(
    name="Strategist",
    model=MODEL,
    instructions="""Ты - Стратег.
    Тебя вызывают, если шаг плана провалился.
    1. Проанализируй ситуацию.
    2. Добавь новые, более дробные или альтернативные шаги в план через `add_steps_to_plan`.
    3. Передай управление обратно Исполнителю (Executor).
    """,
    functions=[tools.add_steps_to_plan, transfer_to_executor],
    tool_choice="required",
)

# 5. REPORTER
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions="""Ты - Репортер.
    Твоя задача - создать финальный отчет.
    1. Сначала вызови `get_completed_research_context`, чтобы выгрузить все подтвержденные факты из БД.
    2. Используя эти факты, напиши структурированный, детальный отчет в Markdown.
    3. ЭТО ФИНАЛ. Просто выведи текст отчета. Не вызывай больше никаких инструментов.
    """,
    functions=[tools.get_completed_research_context],
    # tool_choice не ставим в required, чтобы агент мог вывести текст
)

