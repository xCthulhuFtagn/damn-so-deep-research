from swarm import Swarm, Agent
from config import MODEL
import tools

client = Swarm()

# --- Handoff Functions ---
def transfer_to_executor(): return executor_agent
def transfer_to_evaluator(): return evaluator_agent
def transfer_to_strategist(): return strategist_agent
def transfer_to_reporter(): return reporter_agent

# --- Agent Definitions ---

# 1. PLANNER
planner_agent = Agent(
    name="Planner",
    model=MODEL,
    instructions="""Ты - Главный Планировщик.
    1. Проанализируй запрос пользователя.
    2. Разбей задачу на последовательные шаги исследования.
    3. Используй `add_steps_to_plan`, чтобы записать их в БД.
    4. Сразу после этого передай управление Исполнителю (Executor).
    """,
    functions=[tools.add_steps_to_plan, transfer_to_executor]
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
    ]
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
    ]
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
    functions=[tools.add_steps_to_plan, transfer_to_executor]
)

# 5. REPORTER
reporter_agent = Agent(
    name="Reporter",
    model=MODEL,
    instructions="""Ты - Репортер.
    Твоя задача - создать финальный отчет.
    1. НЕ смотри в историю чата (она может быть очищена).
    2. Используй `get_completed_research_context`, чтобы выгрузить все подтвержденные факты из БД.
    3. Напиши структурированный, детальный отчет в Markdown.
    """,
    functions=[tools.get_completed_research_context]
)

