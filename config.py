import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE")  # optional

# Настройки LLM
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") # Если None, будет использоваться стандартный OpenAI
MODEL = os.getenv("OPENAI_MODEL", "gpt-oss-20b")

# Инфраструктура
DB_NAME = os.getenv("DB_NAME", "research_state.db")
MAX_TURNS = int(os.getenv("MAX_TURNS", 25))
# Количество повторных попыток при сбоях модели
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", 6))
MAX_FINAL_TOP_CHUNKS = int(os.getenv("MAX_FINAL_TOP_CHUNKS", 3))

# Путь к базе данных
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / DB_NAME)