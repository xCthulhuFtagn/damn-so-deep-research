import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из .env
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Настройки LLM
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") # Если None, будет использоваться стандартный OpenAI
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Инфраструктура
DB_NAME = os.getenv("DB_NAME", "research_state.db")
MAX_TURNS = int(os.getenv("MAX_TURNS", 25))
# Путь к базе данных
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / DB_NAME)