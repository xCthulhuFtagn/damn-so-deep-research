import logging
from agents import function_tool
from database import db_service
from utils.context import current_run_id

logger = logging.getLogger(__name__)

@function_tool
def get_research_summary() -> str:
    """
    Возвращает структурированный список всех уже выполненных шагов и их результаты для текущего запуска.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
    logger.debug("get_research_summary called for run_id=%s", run_id)
    return db_service.get_done_results_text(run_id)

@function_tool
def submit_step_result(step_id: int, result_text: str) -> str:
    """
    Сохраняет финальный результат выполнения текущего шага.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
        
    logger.info("submit_step_result: run_id=%s step_id=%s result_chars=%s", run_id, step_id, len(result_text or ""))
    db_service.update_step_status(step_id, "DONE", result_text)
    db_service.set_active_task(run_id, None)
    return "Result saved to Database. Step marked as DONE."

@function_tool
def mark_step_failed(step_id: int, error_msg: str) -> str:
    """
    Помечает шаг как проваленный.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."
        
    logger.warning("mark_step_failed: run_id=%s step_id=%s error_chars=%s", run_id, step_id, len(error_msg or ""))
    db_service.update_step_status(step_id, "FAILED", error_msg)
    return "Step marked as FAILED."

@function_tool
def get_recovery_context() -> str:
    """
    Возвращает контекст для восстановления: исходный запрос + план + детали провала для текущего запуска.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."

    prompt = db_service.get_run_title(run_id) or "N/A"
    
    plan_df = db_service.get_all_plan(run_id)
    if plan_df.empty:
        plan_summary = "Plan is empty."
    else:
        summary_lines = []
        for _, row in plan_df.iterrows():
            summary_lines.append(f"Step {row['step_number']}: {row['status']} - {row['description']}")
        plan_summary = "\n".join(summary_lines)

    active_task_num = db_service.get_active_task(run_id)
    failed_context = ""
    if active_task_num:
        msgs = db_service.get_messages_for_task(run_id, active_task_num)
        failed_context = f"Step {active_task_num} logs:\n"
        for m in msgs[-5:]:
             failed_context += f"{m['role']}: {m.get('content', '')[:200]}...\n"
    
    return f"""RECOVERY CONTEXT for Run ID {run_id}:
Original Request: {prompt}
Plan Status:
{plan_summary}

Failed Step Context:
{failed_context}
"""