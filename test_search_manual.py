
import logging
import sys
import os

# Добавляем текущую директорию в путь, чтобы импорты работали
sys.path.append(os.getcwd())

from tools.search import intelligent_web_search

# Настраиваем логгирование в консоль, чтобы видеть наши новые INFO логи
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
)

def test_search():
    queries = [
        "Lenin mushroom hoax",
        "Кот Шредингера простыми словами"
    ]
    
    for q in queries:
        print(f"\n{'='*50}")
        print(f"ТЕСТИРУЕМ ЗАПРОС: {q}")
        print(f"{'='*50}")
        
        # Вызываем через .fn, так как это FunctionTool
        result = intelligent_web_search.fn(q)
        
        # Печатаем первые 300 символов результата для проверки
        print("\nПЕРВЫЕ 300 СИМВОЛОВ РЕЗУЛЬТАТА:")
        print(result[:300] + "...")
        
        if "Источник:" in result:
            print("\n✅ УСПЕХ: Источники найдены!")
        else:
            print("\n❌ НЕУДАЧА: Результат не содержит источников.")

if __name__ == "__main__":
    test_search()
