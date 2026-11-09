# 🎮 AI Game Studio (ai_multi_agent)

Автономная мультиагентная система на базе **LangGraph**, которая проектирует, пишет код и тестирует браузерные логические игры.

## 🏗 Архитектура (StateGraph)
1. **Planner (LLM)** — придумывает концепт игры, запрещая 20 популярных клише.
2. **Coder (LLM)** — генерирует `index.html`, `style.css`, `game.js`. Возвращает структурированный JSON (Pydantic).
3. **Reviewer (Deterministic)** — проверяет синтаксис через `node --check` и баланс скобок, отсекая галлюцинации LLM.
4. **Tester (Playwright + Vision)** — запускает игру в headless-браузере, выполняет сгенерированный `test_sequence` (массив кликов/движений), проверяет изменение состояния `window.debugState` и сравнивает скриншоты до/после.

## 🛠 Стек
- Python 3.14, LangGraph, Pydantic
- FastAPI (для будущего API)
- Playwright, Node.js (для проверки синтаксиса)
- DeepSeek (APInex) / Ollama (fallback), Gemini 3.8 Flash (Vision)
- Docker, Docker Compose

## 🚀 Запуск
1. Скопируй `.env.example` в `.env` и добавь `APINEX_BOND_KEY`.
2. Установи зависимости: `pip install -r requirements.txt`
3. Запусти: `python main.py`

*Сгенерированные игры сохраняются в папку `workspace/`.*