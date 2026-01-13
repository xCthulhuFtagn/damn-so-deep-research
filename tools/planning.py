import logging
import json
import re
from typing import List
from agents import function_tool
from database import db_service
from utils.context import current_run_id

logger = logging.getLogger(__name__)

@function_tool
def add_steps_to_plan(steps: List[str]) -> str:
    """
    Добавляет новые задачи в план исследования.
    ВАЖНО: Передавайте только текст задачи БЕЗ порядкового номера в начале строки.
    
    Args:
        steps (List[str]): Список описаний задач (например, ["Найти X", "Проверить Y"])
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
        
    logger.info("add_steps_to_plan: run_id=%s count=%s", run_id, len(steps) if isinstance(steps, list) else "N/A")
    
    steps_list: list[str] = []
    if isinstance(steps, list):
        steps_list = [str(s).strip() for s in steps if s]
    elif isinstance(steps, str):
        try:
            decoded = json.loads(steps)
            steps_list = [str(s).strip() for s in decoded if s] if isinstance(decoded, list) else [steps.strip()]
        except Exception:
            steps_list = [s.strip() for s in steps.splitlines() if s.strip()]
    else:
        return "Error: 'steps' must be a list of strings."

    count = 0
    max_num = db_service.get_max_step_number(run_id)

    for desc in steps_list:
        if not desc: continue
        step_num = max_num + 1
        db_service.add_plan_step(run_id, desc, step_num)
        max_num = step_num
        count += 1

    logger.info("add_steps_to_plan: added=%s to run_id=%s", count, run_id)
    return f"{count} steps added to database."

@function_tool
def get_current_plan_step() -> str:
    """
    Возвращает текущую активную задачу из плана для текущего запуска.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
        
    logger.info("get_current_plan_step called for run_id=%s", run_id)
    step = db_service.get_next_step(run_id)
    
    if step is None:
        logger.info("get_current_plan_step: NO_MORE_STEPS for run_id=%s", run_id)
        db_service.set_active_task(run_id, None)
        return "NO_MORE_STEPS"
    
    db_service.set_active_task(run_id, int(step["step_number"]))
    
    logger.info("get_current_plan_step: run_id=%s step_id=%s step_number=%s", run_id, step["id"], step["step_number"])
    return f"Current Step ID: {step['id']}, Step Number: {step['step_number']}, Task: {step['description']}"

@function_tool
def insert_corrective_steps(steps: List[str]) -> str:
    """
    Вставляет НОВЫЕ корректирующие шаги сразу после текущего АКТИВНОГО шага.
    ВАЖНО: Передавайте только текст задачи БЕЗ порядкового номера в начале строки.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
        
    active_task_num = db_service.get_active_task(run_id)
    if active_task_num is None:
        return "ERROR: No active task found. Corrective steps require an active (failed) task."

    steps_list = []
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except json.JSONDecodeError:
            steps = [steps]
            
    if isinstance(steps, list):
        for s in steps:
            clean_s = str(s).strip()
            if clean_s:
                steps_list.append(clean_s)
    
    if not steps_list:
        return "ERROR: No valid text provided for steps."

    try:
        db_service.insert_plan_steps_atomic(run_id, steps_list, insert_after_step=active_task_num)
        return f"SUCCESS: Inserted {len(steps_list)} corrective steps after Step {active_task_num} for run {run_id}."
    except Exception as e:
        logger.error(f"Failed to insert steps for run {run_id}: {e}")
        return f"SYSTEM ERROR during database update: {e}"
