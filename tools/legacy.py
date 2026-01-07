import logging
from agents import function_tool
from database import db_service
from utils.context import current_run_id

logger = logging.getLogger(__name__)

@function_tool
def web_search_summary(summarized_content: str) -> str:
    """
    Сохраняет краткую сводку результатов поиска в контекст для текущего запуска.
    Автоматически удаляет полный текст исходного поиска из истории сообщений.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."

    logger.info("web_search_summary: run_id=%s saving content (len=%s) and pruning previous raw output", 
                run_id, len(summarized_content))
    
    # 1. Вызываем метод очистки в DatabaseService
    db_service.prune_last_tool_message(run_id)
    
    # 2. Возвращаем успех
    return "Summary saved. Raw search data has been removed from history to free up context window."