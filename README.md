# Deep Research Swarm MVP — запуск

Небольшое приложение на **Streamlit** для “deep research” на базе **OpenAI Swarm**. Хранит состояние/план в SQLite и показывает прогресс в сайдбаре.

## Требования

- Python 3.10+ (желательно 3.11)
- `git` (нужен, потому что `swarm` ставится из GitHub)

## Установка

В корне репозитория:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Настройка переменных окружения

Создайте файл `.env` рядом с `main.py`:

```bash
OPENAI_API_KEY=ваш_ключ

# опционально:
# OPENAI_BASE_URL=https://...
# OPENAI_MODEL=gpt-4o
# DB_NAME=research_state.db
# MAX_TURNS=25
# LOG_LEVEL=INFO
# LOG_FILE=logs/app.log
```

Что означает:

- **`OPENAI_API_KEY`**: обязателен.
- **`OPENAI_BASE_URL`**: опционально (например, если используете совместимый прокси/шлюз).
- **`OPENAI_MODEL`**: модель (по умолчанию `gpt-4o`).
- **`DB_NAME`**: имя файла SQLite (по умолчанию `research_state.db`, создаётся в папке проекта).
- **`MAX_TURNS`**: лимит ходов в одном запуске Swarm (по умолчанию `25`).
- **`LOG_LEVEL`**: уровень логов (`DEBUG`, `INFO`, `WARNING`, `ERROR`). По умолчанию `INFO`.
- **`LOG_FILE`**: путь до файла логов (если задан — логи пишутся и в консоль, и в файл с ротацией).

## Запуск

```bash
streamlit run main.py
```

После запуска откройте страницу Streamlit (ссылка будет выведена в терминале).

## Как пользоваться

- Введите тему исследования в поле ввода чата.
- Сайдбар **“Research Plan”** показывает план и статусы шагов (TODO/IN_PROGRESS/DONE/FAILED).
- Сайдбар **“Security Approvals”** нужен для команд терминала: если агент хочет выполнить команду, она попадает в approvals, и её нужно вручную **Approve**.
- Кнопка **“Reset Research”** очищает БД и историю в UI для новой сессии.

## Логи (важно)

Логи выводятся в консоль, где запущен Streamlit. Чтобы включить подробности:

```bash
LOG_LEVEL=DEBUG streamlit run main.py
```

Чтобы писать в файл:

```bash
LOG_FILE=logs/app.log streamlit run main.py
```

## Структура проекта (кратко)

- `main.py`: The main Streamlit application interface, responsible for user interaction and orchestrating the agent swarm.
- `research_agents.py`: Defines the various AI agents (`Planner`, `Executor`, `Evaluator`, `Strategist`, `Reporter`) and their specific instructions, tools, and handoff mechanisms.
- `tools.py`: Provides a collection of tools that agents can use, such as web search, file reading, terminal command execution (with user approval), and context management.
- `database.py`: Manages the SQLite database interactions, including schema definition for `plan`, `approvals`, `messages`, and `global_state` tables, and methods for data manipulation.
- `db_session.py`: Acts as an adapter between the `agents` SDK's session memory and the `DatabaseManager` for persisting conversation history and research state.
- `config.py`: Handles loading environment variables from `.env` and provides application-wide configuration settings like API keys, model names, database path, and execution limits.
- `runner.py`: Contains the core logic for running the agent swarm, managing agent handoffs, and integrating with the Streamlit UI.
- `logging_setup.py`: Configures the application's logging system.
- `requirements.txt`: Lists all Python dependencies required for the project.
- `docker-compose.yml`: Docker Compose configuration for setting up a local vLLM server.
- `Dockerfile`: Defines the Docker image for the main application.
- `searxng/`: Contains configuration files for the SearXNG metasearch engine, which can be used for web searches.

### Логика работы и Контекст Агентов

Проект использует архитектуру **OpenAI Swarm**, разделяя процесс на три фазы. Вот пошаговое объяснение того, что получает и генерирует каждый агент:

#### **Фаза 1: Планирование**

**Агент: `Planner` (Планировщик)**
*   **Триггер:** Пользователь вводит тему исследования (например, "Проанализировать жизнеспособность...").
*   **Контекст (Входные данные):**
    *   **Запрос пользователя:** Исходная тема исследования.
    *   **Статус проекта:** Изначально пуст (или статус предыдущего плана при итерации).
    *   **Инструкции:** "Вы — Главный Планировщик. Ваша ЕДИНСТВЕННАЯ работа — создать план исследования."
*   **Генерирует:**
    *   **Вызов инструмента:** `add_steps_to_plan(steps=[...])`. Создает структурированный список из 3-10 конкретных исследовательских задач в базе данных.
    *   **Текст:** "Plan Created".

---

#### **Фаза 2: Выполнение (Цикл)**

Эта фаза выполняется в цикле для каждого шага, определенного в плане. Агенты используют "Память в рамках задачи" (`DBSession("main_research")`), что означает, что они видят только историю, относящуюся к *текущему* активному шагу.

**Агент: `Executor` (Исполнитель)**
*   **Триггер:** Система выбирает следующий шаг со статусом `TODO` из базы данных.
*   **Контекст (Входные данные):**
    *   **Системный триггер:** "Execute Step X: [Описание шага]".
    *   **Статус проекта:** Сводка всего плана и детали текущего шага.
    *   **История задачи:** Выводы предыдущих инструментов и попытки *только для этого конкретного шага*.
*   **Генерирует:**
    *   **Вызовы инструментов:**
        *   `get_current_plan_step` (Всегда вызывается первым).
        *   `intelligent_web_search`, `read_file`, `execute_terminal_command`, `answer_from_knowledge`.
    *   **Передача управления (Handoff):** Когда собрано достаточно данных, передает управление агенту **Evaluator**.

**Агент: `Evaluator` (Оценщик)**
*   **Триггер:** Передача управления от `Executor` с собранными данными.
*   **Контекст (Входные данные):**
    *   **Полный контекст:** Тот же, что у Executor, плюс самые последние данные/выводы инструментов, которые только что сгенерировал Executor.
    *   **Инструкции:** "Вы — QA Оценщик. Вы проверяете результаты исследования."
*   **Генерирует:**
    *   **Решение (Успех):** Вызывает `submit_step_result(step_id, findings)` для сохранения результата в БД и помечает шаг как `DONE`.
    *   **Решение (Неудача):** Вызывает `mark_step_failed(error_msg)` и передает управление агенту **Strategist**.

**Агент: `Strategist` (Стратег) (Запускается только при неудаче шага)**
*   **Триггер:** Передача управления от `Evaluator` после неудачи.
*   **Контекст (Входные данные):**
    *   **Контекст сбоя:** Конкретное сообщение об ошибке или причина, по которой шаг не удался.
    *   **Статус плана:** Текущее состояние плана.
*   **Генерирует:**
    *   **Вызовы инструментов:**
        *   `insert_corrective_steps(steps=[...])`: Вставляет новые, более мелкие промежуточные шаги для исправления проблемы.
        *   `add_steps_to_plan(...)`: Добавляет шаги в конец, если масштаб был недооценен.
    *   **Передача управления (Handoff):** Возвращает управление агенту **Executor** для попытки выполнения (теперь уже обновленного) плана.

---

#### **Фаза 3: Отчетность**

**Агент: `Reporter` (Репортер)**
*   **Триггер:** Все шаги в плане помечены как `DONE`.
*   **Контекст (Входные данные):**
    *   **Системный триггер:** "All steps completed. Generate the final report."
    *   **Статус проекта:** Показывает, что план выполнен на 100%.
*   **Генерирует:**
    *   **Вызов инструмента:** `get_research_summary`. Извлекает все сохраненные `findings` (результаты) из каждого завершенного шага в базе данных.
    *   **Финальный вывод:** Исчерпывающий отчет в формате Markdown, синтезирующий все полученные данные.

### Использование Базы Данных (SQLite)

Проект активно использует базу данных SQLite (`research_state.db`) для управления состоянием исследования и обеспечения персистентности между сессиями. Основные таблицы и их функции:

- **`plan`**: Хранит план исследования. Каждая запись представляет собой шаг с описанием, текущим статусом (`TODO`, `IN_PROGRESS`, `DONE`, `FAILED`) и результатом выполнения.
- **`approvals`**: Используется для управления одобрениями команд терминала. Если агент предлагает выполнить команду, она сначала сохраняется здесь, ожидая ручного одобрения пользователем через UI.
- **`messages`**: Сохраняет всю историю сообщений и взаимодействий между агентами, включая роли, контент, вызовы инструментов и их результаты. Это обеспечивает возможность отслеживания всего процесса.
- **`global_state`**: Хранит общие флаги состояния, такие как `swarm_running` (индикатор активности роя) и `stop_requested` (флаг для остановки выполнения).

База данных инициализируется и управляется через `database.py`, а `db_session.py` предоставляет интерфейс для сохранения и загрузки истории сообщений агентов, адаптируя ее к формату, ожидаемому SDK агентов.


## Docker

### Запуск приложения

```bash
docker build -t research-swarm .
docker run -p 8501:8501 --env-file .env -v $(pwd)/logs:/app/logs -v $(pwd)/research_state.db:/app/research_state.db research-swarm
```

### Запуск vLLM (Локальный LLM)

Мы подготовили `docker-compose.yml` с правильными настройками для модели `gpt-oss-20b` (включен `auto-tool-choice` и парсер `openai`).

1. Убедитесь, что у вас установлен Docker и NVIDIA Container Toolkit.
2. Задайте токен Hugging Face (если модель требует доступа):
   ```bash
   export HUGGING_FACE_HUB_TOKEN=your_token_here
   ```
3. Запустите vLLM:
   ```bash
   docker compose up -d
   ```

Сервер будет доступен по адресу `http://localhost:8001/v1`.

Настройки в `.env` для приложения включают, но не ограничены:
```bash
OPENAI_BASE_URL=http://localhost:8001/v1
OPENAI_API_KEY=EMPTY
OPENAI_MODEL=openai/gpt-oss-20b
```


