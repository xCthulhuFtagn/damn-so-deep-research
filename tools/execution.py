import logging
import hashlib
import time
import subprocess
from agents import function_tool
from database import db_service
from utils.context import current_run_id

logger = logging.getLogger(__name__)

@function_tool
def execute_terminal_command(command: str) -> str:
    """
    Выполняет bash-команду в терминале.
    ВАЖНО: Перед выполнением требует подтверждения пользователя в UI.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."

    cmd_hash = hashlib.md5(command.encode()).hexdigest()
    logger.info("execute_terminal_command: run_id=%s requested hash=%s cmd=%s", run_id, cmd_hash, command)
    
    # 1. Check existing approval or create request
    status = db_service.get_approval_status(run_id, cmd_hash)
    
    if status is None:
        db_service.request_approval(run_id, cmd_hash, command)
        logger.info("execute_terminal_command: approval requested for run_id=%s hash=%s", run_id, cmd_hash)
        status = 0  # Pending

    # 2. Loop until approved, denied, or paused
    waited = 0
    while status == 0:
        if db_service.should_pause(run_id):
            logger.info("execute_terminal_command: pause signal received for run_id=%s", run_id)
            return "Execution paused by user signal."
            
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            logger.info("Waiting for approval... run_id=%s hash=%s time=%ds", run_id, cmd_hash, waited)
            
        # Re-check status
        new_status = db_service.get_approval_status(run_id, cmd_hash)
        status = new_status if new_status is not None else 0

    # 3. Handle decision
    if status == 1:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
            logger.info("execute_terminal_command: executed for run_id=%s hash=%s rc=%s", run_id, cmd_hash, result.returncode)
            
            combined_output = (result.stdout + "\n" + result.stderr).strip()
            if result.returncode == 0:
                return combined_output if combined_output else "Command executed successfully."
            else:
                return f"Error (exit code {result.returncode}):\n{combined_output}"
        except Exception as e:
            logger.info("execute_terminal_command failed for run_id=%s hash=%s", run_id, cmd_hash)
            return f"Execution Error: {e}"
            
    elif status == -1:
        logger.warning("execute_terminal_command: denied for run_id=%s hash=%s", run_id, cmd_hash)
        return f"Execution denied by user for command: {command}"
        
    return f"Unknown approval status '{status}'"

@function_tool
def read_file(file_path: str) -> str:
    """
    Читает содержимое локального файла.
    """
    try:
        logger.info("read_file: path=%s", file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            logger.debug("read_file: ok chars=%s", len(content))
            return content
    except FileNotFoundError:
        logger.warning("read_file: FileNotFoundError path=%s", file_path)
        return f"Error: File '{file_path}' not found. Verify the path or use other tools to find the correct file."
    except Exception as e:
        logger.exception("read_file failed: path=%s", file_path)
        return f"Error reading file: {e}"

@function_tool
def answer_from_knowledge(answer: str) -> str:
    """
    Эхо-инструмент: принимает сгенерированный текст и возвращает его как есть, чтобы зафиксировать ответ через tool_call.
    """
    return answer

@function_tool
def ask_user(question: str) -> str:
    """
    КРИТИЧЕСКИ ВАЖНО: Этот инструмент должен использоваться ТОЛЬКО в экстренных случаях, когда агент не может продолжить работу без уточнения от пользователя.
    
    Задает вопрос пользователю и ожидает ответа. Используйте этот инструмент только если:
    - Задача неоднозначна и требует уточнения
    - Недостаточно информации для продолжения работы
    - Возникла критическая ситуация, требующая вмешательства пользователя
    
    НЕ используйте этот инструмент для обычных вопросов или если можно продолжить работу с имеющейся информацией.
    """
    run_id = current_run_id.get()
    if not run_id:
        return "Error: No active run context."

    logger.info("ask_user: run_id=%s question=%s", run_id, question)
    
    # Set the pending question in run_state
    db_service._set_run_state(run_id, 'pending_question', question)
    
    # Wait for user response
    waited = 0
    while True:
        if db_service.should_pause(run_id):
            logger.info("ask_user: pause signal received for run_id=%s", run_id)
            db_service._set_run_state(run_id, 'pending_question', '')
            return "Question cancelled due to pause signal."
            
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            logger.info("Waiting for user answer... run_id=%s time=%ds", run_id, waited)
            
        # Check for response
        response = db_service._get_run_state(run_id, 'pending_question_response')
        if response:
            # Clear both question and response
            db_service._set_run_state(run_id, 'pending_question', '')
            db_service._set_run_state(run_id, 'pending_question_response', '')
            logger.info("ask_user: received answer for run_id=%s", run_id)
            return response