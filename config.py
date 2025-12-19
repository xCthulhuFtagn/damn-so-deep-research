import os

# --- Configuration ---
# Замените на свой ключ
OPENAI_API_KEY = "sk-..." 
MODEL = "gpt-4o" 

# Имя файла базы данных
DB_NAME = "research_state.db"

# Максимальное кол-во ходов в одной итерации Swarm
MAX_TURNS = 25

# Применяем ключ к окружению
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

