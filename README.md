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

- `main.py` — Streamlit UI и запуск Swarm.
- `agents.py` — определения агентов (Planner/Executor/Evaluator/Strategist/Reporter).
- `tools.py` — инструменты для агентов (поиск, чтение файлов, терминал с одобрениями, работа с контекстом).
- `database.py` — SQLite: таблицы `plan` и `approvals`.
- `config.py` — загрузка `.env` и настройки (ключи, модель, БД, лимиты).

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

Настройки в `.env` для приложения:
```bash
OPENAI_BASE_URL=http://localhost:8001/v1
OPENAI_API_KEY=EMPTY
OPENAI_MODEL=openai/gpt-oss-20b
```


