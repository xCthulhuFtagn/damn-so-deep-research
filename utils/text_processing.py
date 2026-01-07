from sentence_transformers import SentenceTransformer, CrossEncoder
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import MAX_CHUNK_SIZE, CHUNK_OVERLAP

# --- Инициализация глобальных моделей ---
# Загружаем один раз. Используем CPU, но если есть CUDA, torch сам может подхватить, если указать device='cuda'.
# Bi-Encoder: быстрый первичный поиск. Multilingual v2 отлично работает с русским.
bi_encoder = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', device='cpu')

# Cross-Encoder: точный реранкинг. MS Marco — стандарт для проверки релевантности "вопрос-ответ".
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', device='cpu')

# Глобальный сплиттер LangChain
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=MAX_CHUNK_SIZE,        # Размер смыслового блока
    chunk_overlap=CHUNK_OVERLAP,     # Перекрытие для связности
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len
)

