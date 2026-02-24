"""Шаблон Python-навыка.

Каждая публичная функция автоматически становится tool для агента.
Type hints используются для генерации JSON Schema.
Docstring первой строки -- описание tool.
"""


async def example_skill(input_text: str, count: int = 1) -> str:
    """Пример навыка -- повторяет текст заданное количество раз."""
    return (input_text + "\n") * count
